from __future__ import annotations
from groq import AsyncGroq
from common.config import get_settings
from common.logging import get_logger, setup_logging
from agents.base_agent.base_handler import BaseHandler, AgentState
from agents.base_agent.base_mcp_client import BaseMCPClient

setup_logging()
logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an Indian Law Expert Agent. You are given relevant excerpts from Indian legal texts.
Use ONLY the provided context to answer the question. Be precise and cite the relevant law or section when possible.
If the context does not contain enough information, say so clearly."""

class RAGAgentHandler(BaseHandler):
    def __init__(self):
        self.settings = get_settings()
        self.mcp = BaseMCPClient()
        self.llm = AsyncGroq(api_key=self.settings.groq_api_key)
        super().__init__()

    def _build_graph(self):
        self.add_node("retrieve", self._retrieve)
        self.add_node("answer", self._answer)
        self.set_entry("retrieve")
        self.add_edge("retrieve", "answer")
        self.finish("answer")

    async def _retrieve(self, state: AgentState) -> AgentState:
        query = state["message"]
        try:
            raw = await self.mcp.call_tool("query_rag", {"query": query, "top_k": 5})
            result = raw.get("result", raw)
            state.setdefault("metadata", {})["chunks"] = result.get("chunks", [])
        except Exception as exc:
            logger.error("rag_agent_mcp_failed", error=str(exc))
            state.setdefault("metadata", {})["chunks"] = []
        return state

    async def _answer(self, state: AgentState) -> AgentState:
        query = state["message"]
        chunks = state.get("metadata", {}).get("chunks", [])
        if not chunks:
            state["result"] = "No relevant legal information found for your query."
            state["result_data"] = {"chunks": [], "total": 0}
            return state
        context = " ".join(chunks)
        user_content = (
            f"Legal question: {query}"
            f"Relevant legal excerpts:{context}"
            "Answer the question based on the excerpts above."
        )
        try:
            resp = await self.llm.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=1024,
                temperature=0.2,
            )
            answer = resp.choices[0].message.content
        except Exception as exc:
            logger.error("rag_agent_llm_failed", error=str(exc))
            answer = context

        state["result"] = answer
        state["result_data"] = {"chunks": chunks, "total": len(chunks)}
        return state
