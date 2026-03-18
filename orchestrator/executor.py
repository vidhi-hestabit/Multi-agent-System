from __future__ import annotations
import asyncio
import operator
from common.execution_plan import ExecutionPlan
from common.agent_registry import get_agent_client
from common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

def topological_sort(plan: ExecutionPlan) -> list[list[str]]:
    """
    Returns execution levels. Nodes within the same level have no inter-
    dependencies and can run in parallel.

    Example:
        nodes: weather_agent→[], news_agent→[], report_agent→[weather,news]
        result: [["weather_agent","news_agent"], ["report_agent"]]
    """
    steps: list[list[str]] = []
    completed: set[str] = set()
    nodes = plan.nodes

    while len(completed) < len(nodes):
        ready = [
            n for n, meta in nodes.items()
            if n not in completed
            and all(dep in completed for dep in meta.depends_on)
        ]
        if not ready:
            # Should not happen if validate_no_cycles passed, but guard anyway
            remaining = set(nodes) - completed
            raise ValueError(
                f"Cycle detected during execution — nodes blocked: {remaining}"
            )
        steps.append(ready)
        completed.update(ready)

    return steps


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

_OPS = {
    ">":  operator.gt,
    ">=": operator.ge,
    "<":  operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def evaluate_condition(condition: str, results: dict) -> bool:
    """
    Evaluate a simple condition like "weather_agent.temperature > 35".
    Supports: agent_name.field  OP  literal_value
    Falls back to True on parse errors so the pipeline is not silently blocked.
    """
    if not condition:
        return True

    try:
        for op_str, op_fn in sorted(_OPS.items(), key=lambda x: -len(x[0])):
            if op_str in condition:
                lhs_raw, rhs_raw = condition.split(op_str, 1)
                lhs_raw = lhs_raw.strip()
                rhs_raw = rhs_raw.strip()

                # Resolve left-hand side: "agent.field" or just "field"
                parts = lhs_raw.split(".", 1)
                if len(parts) == 2:
                    agent_name, field = parts
                    agent_result = results.get(agent_name)
                    if agent_result is None:
                        logger.warning(
                            "condition_lhs_agent_missing",
                            condition=condition,
                            agent=agent_name,
                        )
                        return False
                    # agent_result may be a TaskSendResponse or a plain dict
                    if hasattr(agent_result, "model_dump"):
                        agent_result = agent_result.model_dump()
                    lhs_value = _deep_get(agent_result, field)
                else:
                    lhs_value = results.get(lhs_raw)

                # Resolve right-hand side literal
                try:
                    rhs_value = float(rhs_raw)
                    lhs_value = float(lhs_value)
                except (TypeError, ValueError):
                    rhs_value = rhs_raw.strip("'\"")

                result = op_fn(lhs_value, rhs_value)
                logger.info(
                    "condition_evaluated",
                    condition=condition,
                    lhs=lhs_value,
                    rhs=rhs_value,
                    result=result,
                )
                return result
    except Exception as exc:
        logger.warning("condition_eval_failed", condition=condition, error=str(exc))

    # Default: let the step run
    return True


def _deep_get(obj: dict, key: str):
    """Recursively search nested dicts for a key."""
    if key in obj:
        return obj[key]
    for v in obj.values():
        if isinstance(v, dict):
            found = _deep_get(v, key)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

async def execute_plan(plan: ExecutionPlan, initial_query: str) -> dict:
    """
    Execute the DAG plan:
    1. Topologically sort nodes into levels.
    2. Within each level run agents in parallel via asyncio.gather.
    3. Pass upstream outputs to downstream agents via context/metadata.
    4. Guard against cycles (visited list) and runaway depth (max_hops).

    Returns dict: agent_name → TaskSendResponse (or None if skipped/failed).
    """
    levels = topological_sort(plan)
    results: dict = {}

    # Initialise bookkeeping in metadata
    plan.metadata.setdefault("visited", [])
    plan.metadata.setdefault("depth", 0)
    plan.metadata.setdefault("max_hops", 6)

    logger.info(
        "execute_plan_start",
        levels=[[n for n in lvl] for lvl in levels],
        max_hops=plan.metadata["max_hops"],
    )

    for level in levels:
        tasks: dict[str, asyncio.coroutine] = {}

        for node in level:
            meta = plan.nodes[node]

            # ── Condition guard ──────────────────────────────────────────────
            if meta.condition and not evaluate_condition(meta.condition, results):
                logger.info("node_skipped_condition", node=node, condition=meta.condition)
                results[node] = None
                continue

            # ── Cycle guard ──────────────────────────────────────────────────
            if node in plan.metadata["visited"]:
                raise RuntimeError(
                    f"Cycle guard triggered: '{node}' has already been visited. "
                    f"Visited: {plan.metadata['visited']}"
                )
            plan.metadata["visited"].append(node)

            # ── Depth guard ──────────────────────────────────────────────────
            depth = plan.metadata["depth"]
            max_hops = plan.metadata["max_hops"]
            if depth >= max_hops:
                raise RuntimeError(
                    f"Max hops ({max_hops}) exceeded at node '{node}'. "
                    "Increase max_hops in the plan metadata if deeper chains are needed."
                )
            plan.metadata["depth"] = depth + 1

            # ── Collect upstream outputs ─────────────────────────────────────
            upstream_outputs: dict = {}
            for dep in meta.input_from:
                dep_result = results.get(dep)
                if dep_result is not None:
                    upstream_outputs[dep] = (
                        dep_result.model_dump()
                        if hasattr(dep_result, "model_dump")
                        else dep_result
                    )

            # Build query text, enriched with upstream context if available
            context_text = ""
            if upstream_outputs:
                context_parts = []
                for dep_name, dep_data in upstream_outputs.items():
                    # Try to pull the text message out of TaskSendResponse shape
                    msg = (
                        dep_data.get("status", {}).get("message", {}).get("parts", [{}])[0].get("text", "")
                        if isinstance(dep_data, dict) else ""
                    )
                    if msg:
                        context_parts.append(f"[{dep_name}]: {msg}")
                if context_parts:
                    context_text = "\n".join(context_parts)

            full_query = (
                f"{initial_query}\n\nContext from upstream agents:\n{context_text}"
                if context_text else initial_query
            )

            client = get_agent_client(node)
            tasks[node] = client.send_task(
                text=full_query,
                session_id=None,
                metadata={"upstream": upstream_outputs, "plan_depth": plan.metadata["depth"]},
            )
            logger.info("node_scheduled", node=node, depth=plan.metadata["depth"])

        if not tasks:
            continue

        # ── Run this level in parallel ───────────────────────────────────────
        level_results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for name, result in zip(tasks.keys(), level_results):
            if isinstance(result, Exception):
                logger.error("node_failed", node=name, error=str(result))
                results[name] = None
            else:
                results[name] = result
                logger.info("node_completed", node=name)

    logger.info("execute_plan_done", visited=plan.metadata["visited"])
    return results