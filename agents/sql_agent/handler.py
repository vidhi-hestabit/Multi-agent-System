from __future__ import annotations
from groq import AsyncGroq
from common.config import get_settings
from common.logging import get_logger, setup_logging
from agents.base_agent.base_handler import BaseHandler, AgentState
from agents.base_agent.base_mcp_client import BaseMCPClient

setup_logging()
logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a SQL Data Analyst Agent. You have queried a Chinook music database.
Given the SQL query that was run and the rows returned, provide a clear, concise natural language answer.
Format numbers nicely. If rows are empty, say no results were found."""


class SQLAgentHandler(BaseHandler):

    def __init__(self):
        self.settings = get_settings()
        self.mcp = BaseMCPClient()
        self.llm = AsyncGroq(api_key=self.settings.groq_api_key)
        super().__init__()

    def _build_graph(self):
        self.add_node("run_query", self._run_query)
        self.add_node("format_answer", self._format_answer)
        self.set_entry("run_query")
        self.add_edge("run_query", "format_answer")
        self.finish("format_answer")

    async def _run_query(self, state: AgentState) -> AgentState:
        query = state["message"]
        try:
            result = await self.mcp.call_tool("query_sql", {"natural_language_query": query})
            state.setdefault("metadata", {})["sql_result"] = result
        except Exception as exc:
            logger.error("sql_agent_mcp_failed", error=str(exc))
            state.setdefault("metadata", {})["sql_result"] = {"error": str(exc), "rows": [], "sql": ""}
        return state

    async def _format_answer(self, state: AgentState) -> AgentState:
        query = state["message"]
        raw = state.get("metadata", {}).get("sql_result", {})
        result = raw.get("result", raw)

        if result.get("error"):
            state["result"] = f"Sorry, I could not answer that: {result['error']}"
            state["result_data"] = result
            return state

        rows = result.get("rows", [])
        sql = result.get("sql", "")

        rows_text = "\n".join(str(r) for r in rows[:20]) if rows else "No rows returned."
        user_content = (
            f"User question: {query}"
            f"SQL executed: {sql}"
            f"Rows returned ({len(rows)} total):{rows_text}"
            "Provide a clear natural language answer."
        )

        try:
            resp = await self.llm.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=512,
                temperature=0.2,
            )
            answer = resp.choices[0].message.content
        except Exception as exc:
            logger.error("sql_agent_llm_failed", error=str(exc))
            answer = rows_text

        state["result"] = answer
        state["result_data"] = {"sql": sql, "rows": rows, "total": result.get("total", len(rows))}
        return state
