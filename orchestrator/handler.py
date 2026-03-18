from __future__ import annotations

import json
from typing import Any

from groq import AsyncGroq

from agents.base_agent.base_handler import BaseHandler, AgentState
from common.config import get_settings
from common.execute_plan import ExecutionPlan
from common.logging import get_logger
from orchestrator.executor import execute_plan

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Planner prompt
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You are an orchestration planner for a multi-agent system.

Available agents:
- sql_agent     — answers natural language questions about the Chinook music database
- rag_agent     — answers Indian law questions using semantic search
- news_agent    — fetches and summarises news articles on any topic
- weather_agent — fetches current weather conditions for a city
- report_agent  — compiles outputs from other agents into a structured report

Given a user query, return ONLY a valid JSON ExecutionPlan with this exact structure (no markdown, no explanation):

{
  "nodes": {
    "<agent_name>": {
      "depends_on": ["<upstream_agent_name>"],
      "condition": null,
      "input_from": ["<agent_name_whose_output_to_forward>"]
    }
  },
  "entry_points": ["<agent_names_with_no_dependencies>"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}

Rules:
1. Only include agents actually needed for this query.
2. No cycles — dependencies must always point forward (downstream).
3. "entry_points" must list every node whose "depends_on" is empty [].
4. "report_agent" must depend on ALL data-gathering agents when a report/email/summary is needed.
5. "input_from" should list agents whose text output should be forwarded to this agent.
6. Use "condition" (a Python expression string) ONLY when the next step depends on a runtime value,
   e.g. "weather_agent.temperature > 35". Set to null otherwise.
7. Keep plans minimal — use the fewest agents that satisfy the query.
8. If the query is entirely self-contained for one agent, return a single-node plan.

Examples:

Query: "Get AI news"
{
  "nodes": {"news_agent": {"depends_on": [], "condition": null, "input_from": []}},
  "entry_points": ["news_agent"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}

Query: "Email a summary of today's weather and top news"
{
  "nodes": {
    "weather_agent": {"depends_on": [], "condition": null, "input_from": []},
    "news_agent":    {"depends_on": [], "condition": null, "input_from": []},
    "report_agent":  {"depends_on": ["weather_agent", "news_agent"], "condition": null, "input_from": ["weather_agent", "news_agent"]}
  },
  "entry_points": ["weather_agent", "news_agent"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}

Query: "Check weather in Delhi; if it's hot get heatwave news, then email a report"
{
  "nodes": {
    "weather_agent": {"depends_on": [], "condition": null, "input_from": []},
    "news_agent":    {"depends_on": ["weather_agent"], "condition": "weather_agent.temperature > 35", "input_from": ["weather_agent"]},
    "report_agent":  {"depends_on": ["news_agent"], "condition": null, "input_from": ["weather_agent", "news_agent"]}
  },
  "entry_points": ["weather_agent"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}
"""


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class OrchestratorHandler(BaseHandler):
    """
    LangGraph-based orchestrator handler.

    Graph:  plan → execute → format_result
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.llm = AsyncGroq(api_key=self.settings.groq_api_key)
        super().__init__()

    # ------------------------------------------------------------------
    # LangGraph graph definition
    # ------------------------------------------------------------------

    def _build_graph(self) -> None:
        self.add_node("plan", self._plan)
        self.add_node("execute", self._execute)
        self.add_node("format_result", self._format_result)

        self.set_entry("plan")
        self.add_edge("plan", "execute")
        self.add_edge("execute", "format_result")
        self.finish("format_result")

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _plan(self, state: AgentState) -> AgentState:
        """Call the LLM planner and build an ExecutionPlan."""
        query = state["message"]
        state.setdefault("metadata", {})

        try:
            resp = await self.llm.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                max_tokens=1024,
                temperature=0.1,
            )

            raw = resp.choices[0].message.content.strip()

            # Strip markdown code fences if the LLM wraps its output
            if raw.startswith("```"):
                lines = raw.splitlines()
                # Remove opening fence (```json or ```) and closing fence
                raw = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )

            plan_dict: dict[str, Any] = json.loads(raw)
            plan = ExecutionPlan(**plan_dict)

            state["metadata"]["execution_plan"] = plan.model_dump()
            logger.info(
                "orchestrator_plan_ready",
                nodes=list(plan.nodes.keys()),
                entry_points=plan.entry_points,
            )

        except json.JSONDecodeError as exc:
            logger.error("orchestrator_plan_json_error", error=str(exc))
            state["error"] = f"Planner returned invalid JSON: {exc}"

        except Exception as exc:
            logger.error("orchestrator_plan_failed", error=str(exc))
            state["error"] = f"Planning failed: {exc}"

        return state

    async def _execute(self, state: AgentState) -> AgentState:
        """Run the ExecutionPlan via the topological executor."""
        if state.get("error"):
            return state

        plan_dict = state.get("metadata", {}).get("execution_plan")
        if not plan_dict:
            state["error"] = "No execution plan was created."
            return state

        try:
            plan = ExecutionPlan(**plan_dict)
            raw_results = await execute_plan(plan, state["message"])

            # Serialise results so they can be stored in state metadata
            serialised: dict[str, dict] = {}
            for agent_name, result in raw_results.items():
                if result is None:
                    serialised[agent_name] = {"skipped": True, "text": "", "state": "skipped"}
                elif isinstance(result, Exception):
                    serialised[agent_name] = {
                        "error": str(result),
                        "text": f"Agent '{agent_name}' failed: {result}",
                        "state": "failed",
                    }
                else:
                    text = (
                        result.status.message.text()
                        if result.status.message
                        else ""
                    )
                    serialised[agent_name] = {
                        "text": text,
                        "state": result.status.state.value,
                    }

            state["metadata"]["agent_results"] = serialised
            logger.info(
                "orchestrator_execution_complete",
                agents=list(serialised.keys()),
            )

        except Exception as exc:
            logger.error("orchestrator_execute_failed", error=str(exc))
            state["error"] = f"Execution failed: {exc}"

        return state

    async def _format_result(self, state: AgentState) -> AgentState:
        """Merge all agent outputs into a single human-readable result."""
        if state.get("error"):
            return state

        agent_results: dict[str, dict] = state.get("metadata", {}).get(
            "agent_results", {}
        )

        sections: list[str] = []
        for agent_name, result in agent_results.items():
            if result.get("skipped"):
                continue
            if result.get("error"):
                sections.append(f" **{agent_name}** encountered an error: {result['error']}")
            else:
                text = result.get("text", "").strip()
                if text:
                    label = agent_name.replace("_", " ").title()
                    sections.append(f"### {label}\n\n{text}")

        combined = (
            "\n\n---\n\n".join(sections)
            if sections
            else "No results were returned from the agents."
        )

        state["result"] = combined
        state["result_data"] = {
            "agent_results": agent_results,
            "execution_plan": state.get("metadata", {}).get("execution_plan", {}),
        }
        return state