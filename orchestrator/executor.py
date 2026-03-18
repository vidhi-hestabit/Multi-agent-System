from __future__ import annotations

import asyncio
from typing import Any

from common.a2a_types import TaskSendResponse
from common.agent_registry import get_agent_client
from common.execute_plan import ExecutionPlan
from common.logging import get_logger

logger = get_logger(__name__)


# Topological sort

def topological_sort(plan: ExecutionPlan) -> list[list[str]]:
    """
    Returns execution levels. All nodes within one level have their dependencies
    satisfied by earlier levels and can run in parallel.

    Example result: [["weather_agent","news_agent"], ["report_agent"]]
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
            raise ValueError(
                "Cycle detected during topological sort — execution aborted."
            )
        steps.append(ready)
        completed.update(ready)

    return steps


# Condition evaluator

def evaluate_condition(condition: str, results: dict[str, Any]) -> bool:
    """
    Evaluate a simple runtime condition against collected agent results.

    Supported format:  <agent_name>.<field> <op> <value>
    Example:           weather_agent.temperature > 35

    The agent namespace is built from the DataPart of each agent's artifacts.
    Falls back to True (execute) if the condition cannot be evaluated.
    """
    try:
        # Build a namespace: agent_name → SimpleNamespace of its data fields
        namespace: dict[str, Any] = {}
        for agent_name, result in results.items():
            if result is None or isinstance(result, Exception):
                namespace[agent_name] = type("_NS", (), {})()
                continue

            agent_data: dict[str, Any] = {}
            if hasattr(result, "artifacts") and result.artifacts:
                for artifact in result.artifacts:
                    for part in artifact.parts:
                        if hasattr(part, "data") and isinstance(part.data, dict):
                            agent_data.update(part.data)

            # Also expose top-level weather dict fields directly
            if "weather" in agent_data and isinstance(agent_data["weather"], dict):
                agent_data.update(agent_data["weather"])

            namespace[agent_name] = type("_NS", (), agent_data)()

        return bool(eval(condition, {"__builtins__": {}}, namespace))  # noqa: S307

    except Exception as exc:
        logger.warning(
            "condition_eval_failed",
            condition=condition,
            error=str(exc),
        )
        return True 

# Plan executor

async def execute_plan(
    plan: ExecutionPlan,
    initial_query: str,
) -> dict[str, TaskSendResponse | Exception | None]:
    """
    Execute the plan level-by-level.
    Nodes within the same level run concurrently via asyncio.gather.

    Returns a mapping of agent_name → TaskSendResponse (or Exception / None).
    """
    levels = topological_sort(plan)
    results: dict[str, Any] = {}

    for level in levels:
        coros: dict[str, Any] = {}

        for node in level:
            meta = plan.nodes[node]

            #  Conditional skip 
            if meta.condition:
                if not evaluate_condition(meta.condition, results):
                    logger.info("node_skipped_condition", node=node, condition=meta.condition)
                    results[node] = None
                    continue

            #  Cycle guard 
            visited: list[str] = plan.metadata.setdefault("visited", [])
            if node in visited:
                raise RuntimeError(f"Cycle guard triggered: '{node}' was already visited.")
            visited.append(node)

            #  Depth / hop guard 
            depth: int = plan.metadata.get("depth", 0)
            max_hops: int = plan.metadata.get("max_hops", 6)
            if depth >= max_hops:
                raise RuntimeError(
                    f"Max hops ({max_hops}) exceeded before reaching '{node}'."
                )
            plan.metadata["depth"] = depth + 1

            #  Build enriched query 
            # Collect upstream text outputs to pass as context
            upstream_texts: dict[str, str] = {}
            for dep in meta.input_from:
                dep_result = results.get(dep)
                if dep_result is None or isinstance(dep_result, Exception):
                    continue
                if hasattr(dep_result, "status") and dep_result.status.message:
                    upstream_texts[dep] = dep_result.status.message.text()

            if upstream_texts:
                context_block = "\n".join(
                    f"[{k}]: {v}" for k, v in upstream_texts.items()
                )
                query_text = (
                    f"{initial_query}\n\n"
                    f"Context from upstream agents:\n{context_block}"
                )
            else:
                query_text = initial_query

            #  Schedule the A2A call 
            client = get_agent_client(node)
            coros[node] = client.send_task(
                text=query_text,
                session_id=None,
                metadata={
                    "orchestrated": True,
                    "upstream_agents": list(upstream_texts.keys()),
                },
            )

        #  Run level in parallel 
        if coros:
            level_results = await asyncio.gather(*coros.values(), return_exceptions=True)
            for name, result in zip(coros.keys(), level_results):
                if isinstance(result, Exception):
                    logger.error("node_execution_failed", node=name, error=str(result))
                results[name] = result

    return results