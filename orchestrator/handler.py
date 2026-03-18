from __future__ import annotations
import json
import re
from groq import AsyncGroq
from common.config import get_settings
from common.logging import get_logger
from common.execution_plan import ExecutionPlan, NodeMeta, validate_no_cycles
from common.a2a_types import Task, TaskState, TaskStatus, Message, TextPart, Artifact, DataPart
from orchestrator.executor import execute_plan

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Planner prompt
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """
You are an orchestration planner for a multi-agent system.

Available agents:
- sql_agent      → answers questions about the Chinook music database (SQL)
- rag_agent      → answers Indian law questions via semantic search
- news_agent     → fetches and summarises latest news on any topic
- weather_agent  → fetches current weather for a city
- report_agent   → compiles data from other agents into a structured report
- composio_tool  → sends emails / Slack / Telegram messages (always last if delivery needed)

Given a user query, return ONLY a valid JSON ExecutionPlan with this exact structure:

{
  "nodes": {
    "<agent_name>": {
      "depends_on": ["<upstream_agent_name>"],
      "condition": "<optional runtime condition e.g. weather_agent.temperature > 35>",
      "input_from": ["<agent whose output to pass as context>"]
    }
  },
  "entry_points": ["<agents with no dependencies>"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}

Rules:
1. Include ONLY agents actually needed for this query.
2. No cycles — dependencies must always point forward.
3. composio_tool always comes last if email/send is requested.
4. report_agent always depends on all data-gathering agents that run before it.
5. Use "condition" only when the next step must depend on a runtime output value.
6. "input_from" lists agents whose outputs should be forwarded to this node.
7. Keep it minimal — fewer nodes is better.
8. Return ONLY the JSON object, no markdown fences, no explanation.
""".strip()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class OrchestratorHandler:
    """
    LLM-powered planner:
    1. Receives a user Task.
    2. Calls Groq to produce an ExecutionPlan JSON.
    3. Validates + executes the plan via execute_plan().
    4. Returns a completed Task with aggregated results.
    """

    def __init__(self):
        self.settings = get_settings()
        self.llm = AsyncGroq(api_key=self.settings.groq_api_key)

    # ── Public entry point (called by base_a2a_server) ───────────────────────

    async def handle(self, task: Task) -> Task:
        user_text = ""
        if task.history:
            last = next((m for m in reversed(task.history) if m.role == "user"), None)
            if last:
                user_text = last.text()

        if not user_text:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(role="agent", parts=[TextPart(text="Empty query received.")]),
            )
            return task

        logger.info("orchestrator_received", query=user_text)

        # Step 1: plan
        try:
            plan = await self._plan(user_text)
        except Exception as exc:
            logger.error("orchestrator_plan_failed", error=str(exc))
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(role="agent", parts=[TextPart(text=f"Planning failed: {exc}")]),
            )
            return task

        logger.info(
            "orchestrator_plan_ready",
            nodes=list(plan.nodes.keys()),
            entry_points=plan.entry_points,
        )

        # Step 2: execute
        try:
            results = await execute_plan(plan, user_text)
        except Exception as exc:
            logger.error("orchestrator_exec_failed", error=str(exc))
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(role="agent", parts=[TextPart(text=f"Execution failed: {exc}")]),
            )
            return task

        # Step 3: aggregate results → single response
        summary = self._aggregate(results)

        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message(role="agent", parts=[TextPart(text=summary)]),
        )
        task.artifacts = [
            Artifact(
                name="orchestration_result",
                parts=[DataPart(data={
                    "plan": {
                        "nodes": {k: v.model_dump() for k, v in plan.nodes.items()},
                        "entry_points": plan.entry_points,
                    },
                    "agent_results": {
                        name: (
                            res.model_dump() if hasattr(res, "model_dump") else str(res)
                        )
                        for name, res in results.items()
                    },
                })],
            )
        ]
        return task

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _plan(self, query: str) -> ExecutionPlan:
        """Call the LLM and parse the returned JSON into an ExecutionPlan."""
        response = await self.llm.chat.completions.create(
            model=self.settings.groq_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user",   "content": query},
            ],
            max_tokens=1024,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()
        logger.debug("planner_raw_output", raw=raw)

        # Strip accidental markdown fences
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {exc}\nRaw: {raw}") from exc

        # Validate cycle-freedom before constructing the model (belt + suspenders)
        if not validate_no_cycles(data.get("nodes", {})):
            raise ValueError("LLM returned a cyclic execution plan — rejected.")

        plan = ExecutionPlan(**data)
        return plan

    def _aggregate(self, results: dict) -> str:
        """Collect the text message from each agent result into a readable summary."""
        parts: list[str] = []
        for agent_name, res in results.items():
            if res is None:
                parts.append(f"[{agent_name}]: skipped (condition not met or error)")
                continue
            try:
                if hasattr(res, "status") and res.status.message:
                    text = res.status.message.text()
                elif isinstance(res, dict):
                    text = res.get("status", {}).get("message", {}).get("parts", [{}])[0].get("text", str(res))
                else:
                    text = str(res)
            except Exception:
                text = str(res)
            parts.append(f"### {agent_name}\n{text}")

        return "\n\n".join(parts) if parts else "No results returned."