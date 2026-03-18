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


PLANNER_SYSTEM_PROMPT = """You are an orchestration planner for a multi-agent system.

Available agents:
- sql_agent       — answers natural language questions about the Chinook music database
- rag_agent       — answers Indian law questions using semantic search
- news_agent      — fetches and summarises news articles on any topic
- weather_agent   — fetches current weather conditions for a city
- composio_agent  — sends or delivers content via connected apps such as Gmail, Slack, Telegram, Discord, etc.

You will receive a refined task object in JSON.
Return ONLY a valid JSON ExecutionPlan with this exact structure (no markdown, no explanation):

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
1. Only include agents actually needed.
2. No cycles.
3. "entry_points" must include every node whose "depends_on" is [].
4. Use composio_agent whenever the user asks to send, email, mail, message, post, share, or deliver output through Gmail, Slack, Telegram, Discord, or another connected app/channel.
5. If composio_agent is used after multiple upstream agents, it must depend on all required upstream agents.
6. If only one agent's output needs to be sent directly, composio_agent may depend directly on that single agent.
7. "input_from" must list the agents whose text output should be forwarded to that node.
8. Use "condition" only for runtime branching. Otherwise set it to null.
9. Keep plans minimal.
10. If a refined task already includes "requires_agents", do not add unrelated agents.

Examples:

Input:
{
  "refined_query": "Fetch the latest AI news.",
  "intent": "single_agent",
  "requires_agents": ["news_agent"],
  "delivery_target": {"needed": false, "platform": null, "recipient_or_channel": null},
  "notes": "Single retrieval task for news_agent."
}

Output:
{
  "nodes": {
    "news_agent": {"depends_on": [], "condition": null, "input_from": []}
  },
  "entry_points": ["news_agent"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}

Input:
{
  "refined_query": "Fetch the latest AI news and send it via Gmail.",
  "intent": "multi_agent_with_delivery",
  "requires_agents": ["news_agent", "composio_agent"],
  "delivery_target": {"needed": true, "platform": "gmail", "recipient_or_channel": null},
  "notes": "News must be fetched first, then delivered through composio_agent."
}

Output:
{
  "nodes": {
    "news_agent": {"depends_on": [], "condition": null, "input_from": []},
    "composio_agent": {"depends_on": ["news_agent"], "condition": null, "input_from": ["news_agent"]}
  },
  "entry_points": ["news_agent"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}

Input:
{
  "refined_query": "Fetch the current weather in Delhi and top AI news, then send both to Slack.",
  "intent": "multi_agent_with_delivery",
  "requires_agents": ["weather_agent", "news_agent", "composio_agent"],
  "delivery_target": {"needed": true, "platform": "slack", "recipient_or_channel": null},
  "notes": "Multiple agent outputs must be combined before delivery."
}

Output:
{
  "nodes": {
    "weather_agent": {"depends_on": [], "condition": null, "input_from": []},
    "news_agent": {"depends_on": [], "condition": null, "input_from": []},
    "composio_agent": {"depends_on": ["weather_agent", "news_agent"], "condition": null, "input_from": ["weather_agent", "news_agent"]}
  },
  "entry_points": ["weather_agent", "news_agent"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}

Input:
{
  "refined_query": "Check weather in Delhi. If it is hot, fetch heatwave news and email the result.",
  "intent": "multi_agent_with_delivery",
  "requires_agents": ["weather_agent", "news_agent", "composio_agent"],
  "delivery_target": {"needed": true, "platform": "gmail", "recipient_or_channel": null},
  "notes": "Conditional branching based on weather result."
}

Output:
{
  "nodes": {
    "weather_agent": {"depends_on": [], "condition": null, "input_from": []},
    "news_agent": {"depends_on": ["weather_agent"], "condition": "weather_agent.temperature > 35", "input_from": ["weather_agent"]},
    "composio_agent": {"depends_on": ["weather_agent", "news_agent"], "condition": null, "input_from": ["weather_agent", "news_agent"]}
  },
  "entry_points": ["weather_agent"],
  "metadata": {"visited": [], "depth": 0, "max_hops": 6}
}
"""


REFINER_SYSTEM_PROMPT = """You are a query refiner and router for a multi-agent orchestration system.

Your job:
1. Rewrite the user's request into a clear, explicit internal task.
2. Detect whether the task involves:
   - data retrieval
   - delivery/sending via Gmail, Slack, Telegram, Discord, or another connected app
3. Identify which agent capabilities are likely required.

Available agents:
- sql_agent
- rag_agent
- news_agent
- weather_agent
- composio_agent

Return ONLY valid JSON with this exact structure:

{
  "refined_query": "<clear rewritten task>",
  "intent": "<one of: direct_answer, single_agent, multi_agent, multi_agent_with_delivery>",
  "requires_agents": ["<agent_name>"],
  "delivery_target": {
    "needed": true,
    "platform": "<gmail|slack|telegram|discord|unknown|null>",
    "recipient_or_channel": "<recipient if explicitly mentioned, else null>"
  },
  "notes": "<short reasoning summary>"
}

Rules:
1. Preserve the user's original meaning.
2. If the user asks to send, email, mail, post, message, share, or deliver content, include composio_agent in requires_agents.
3. If the delivery platform is mentioned as Gmail, email, Slack, channel, Telegram, Discord, identify it in delivery_target.platform.
4. If recipient/channel is not specified, set it to null.
5. Keep the refined_query concrete and execution-ready.
6. If the task clearly needs multiple retrieval agents, include all of them in requires_agents.
7. If the user asks for "channel", "Slack", "mail", "gmail", "email", "send", or "post", treat it as delivery-related.

Examples:

User: "latest AI news"
{
  "refined_query": "Fetch the latest AI news.",
  "intent": "single_agent",
  "requires_agents": ["news_agent"],
  "delivery_target": {"needed": false, "platform": null, "recipient_or_channel": null},
  "notes": "Single retrieval task for news_agent."
}

User: "send latest AI news to gmail"
{
  "refined_query": "Fetch the latest AI news and send it via Gmail.",
  "intent": "multi_agent_with_delivery",
  "requires_agents": ["news_agent", "composio_agent"],
  "delivery_target": {"needed": true, "platform": "gmail", "recipient_or_channel": null},
  "notes": "News must be fetched first, then delivered through composio_agent."
}

User: "weather in Delhi and top news, send it to slack channel"
{
  "refined_query": "Fetch the current weather in Delhi and top news, then send both to Slack.",
  "intent": "multi_agent_with_delivery",
  "requires_agents": ["weather_agent", "news_agent", "composio_agent"],
  "delivery_target": {"needed": true, "platform": "slack", "recipient_or_channel": null},
  "notes": "Multiple agent outputs are required before delivery."
}
"""


class OrchestratorHandler(BaseHandler):
    """
    LangGraph-based orchestrator handler.

    Graph:
        refine -> plan -> execute -> format_result
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.llm = AsyncGroq(api_key=self.settings.groq_api_key)
        super().__init__()

    def _build_graph(self) -> None:
        self.add_node("refine", self._refine)
        self.add_node("plan", self._plan)
        self.add_node("execute", self._execute)
        self.add_node("format_result", self._format_result)

        self.set_entry("refine")
        self.add_edge("refine", "plan")
        self.add_edge("plan", "execute")
        self.add_edge("execute", "format_result")
        self.finish("format_result")

    @staticmethod
    def _strip_code_fences(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()
        return raw

    async def _refine(self, state: AgentState) -> AgentState:
        """Refine the raw user query into a structured task."""
        query = state["message"]
        state.setdefault("metadata", {})

        try:
            resp = await self.llm.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": REFINER_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                max_tokens=800,
                temperature=0.1,
            )

            raw = resp.choices[0].message.content or ""
            raw = self._strip_code_fences(raw)

            refined: dict[str, Any] = json.loads(raw)

            state["metadata"]["refined_task"] = refined
            logger.info(
                "orchestrator_refine_ready",
                refined_query=refined.get("refined_query"),
                intent=refined.get("intent"),
                requires_agents=refined.get("requires_agents", []),
            )

        except json.JSONDecodeError as exc:
            logger.error("orchestrator_refine_json_error", error=str(exc))
            state["error"] = f"Refiner returned invalid JSON: {exc}"

        except Exception as exc:
            logger.error("orchestrator_refine_failed", error=str(exc))
            state["error"] = f"Refinement failed: {exc}"

        return state

    async def _plan(self, state: AgentState) -> AgentState:
        """Call the planner and build an ExecutionPlan from the refined task."""
        if state.get("error"):
            return state

        state.setdefault("metadata", {})
        refined_task = state.get("metadata", {}).get("refined_task")

        if not refined_task:
            state["error"] = "No refined task was created."
            return state

        try:
            planner_input = json.dumps(refined_task, ensure_ascii=False)

            resp = await self.llm.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": planner_input},
                ],
                max_tokens=1024,
                temperature=0.1,
            )

            raw = resp.choices[0].message.content or ""
            raw = self._strip_code_fences(raw)

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

        metadata = state.get("metadata", {})
        plan_dict = metadata.get("execution_plan")
        refined_task = metadata.get("refined_task", {})

        if not plan_dict:
            state["error"] = "No execution plan was created."
            return state

        execution_query = refined_task.get("refined_query", state["message"])

        try:
            plan = ExecutionPlan(**plan_dict)
            raw_results = await execute_plan(plan, execution_query)

            serialised: dict[str, dict[str, Any]] = {}

            for agent_name, result in raw_results.items():
                if result is None:
                    serialised[agent_name] = {
                        "skipped": True,
                        "text": "",
                        "state": "skipped",
                    }
                elif isinstance(result, Exception):
                    serialised[agent_name] = {
                        "error": str(result),
                        "text": f"Agent '{agent_name}' failed: {result}",
                        "state": "failed",
                    }
                else:
                    text = ""
                    if getattr(result, "status", None) and getattr(result.status, "message", None):
                        try:
                            text = result.status.message.text()
                        except Exception:
                            text = str(result.status.message)

                    state_value = "unknown"
                    if getattr(result, "status", None) and getattr(result.status, "state", None):
                        try:
                            state_value = result.status.state.value
                        except Exception:
                            state_value = str(result.status.state)

                    serialised[agent_name] = {
                        "text": text,
                        "state": state_value,
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
            state["result"] = state["error"]
            state["result_data"] = {
                "error": state["error"],
                "execution_plan": state.get("metadata", {}).get("execution_plan", {}),
                "refined_task": state.get("metadata", {}).get("refined_task", {}),
            }
            return state

        metadata = state.get("metadata", {})
        agent_results: dict[str, dict[str, Any]] = metadata.get("agent_results", {})

        sections: list[str] = []

        for agent_name, result in agent_results.items():
            if result.get("skipped"):
                continue

            label = agent_name.replace("_", " ").title()

            if result.get("error"):
                sections.append(f"### {label}\n\nError: {result['error']}")
                continue

            text = (result.get("text") or "").strip()
            if text:
                sections.append(f"### {label}\n\n{text}")

        combined = (
            "\n\n---\n\n".join(sections)
            if sections
            else "No results were returned from the agents."
        )

        state["result"] = combined
        state["result_data"] = {
            "refined_task": metadata.get("refined_task", {}),
            "execution_plan": metadata.get("execution_plan", {}),
            "agent_results": agent_results,
        }
        return state