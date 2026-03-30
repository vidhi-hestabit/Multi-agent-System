from __future__ import annotations
import logging
import os
import httpx
import uvicorn
from agents.base import BaseAgent
from agents.llm_utils import ask_llm, rewrite_query
from common.config import get_settings
from common.prompts.rag_prompts import _RAG_SYSTEM, RAG_FALLBACK_SYSTEM, RAG_FALLBACK_PREFIX

logger = logging.getLogger(__name__)
settings = get_settings()
PORT = settings.rag_agent_port
HOST = settings.rag_agent_host
MCP = settings.mcp_server_url


class RAGAgent(BaseAgent):
    @property
    def agent_card(self) -> dict:
        return {
            "name": "RAG Agent",
            "description": "Answers Indian law questions. Uses FAISS index if built, else LLM knowledge.",
            "url": f"http://{HOST}:{PORT}",
            "version": "1.0.0",
            "protocolVersion": "0.3.0",
            "requires": [],
            "produces": ["rag_answer"],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "query_rag",
                    "name": "Query Indian Law",
                    "description": "Semantic search over Indian Law dataset.",
                    "tags": ["law", "india", "rag"],
                }
            ],
        }

    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        history = context.get("history", "")
        search_query = await rewrite_query(instruction, history)
        
        chunks = await self._try_mcp(search_query)
        if chunks:
            logger.info("RAGAgent: %d chunks from FAISS task=%s", len(chunks), task_id[:8])
            answer = await ask_llm(
                _RAG_SYSTEM,
                f"History:\n{history}\n\nQuestion: {instruction}\n\nLegal excerpts:\n{chr(10).join(chunks)}\n\nAnswer:",
                max_tokens=800,
                temperature=0.1,
            )
        else:
            logger.warning(
                "RAGAgent: FAISS unavailable for task=%s — using LLM fallback. "
                "Run: python scripts/build_rag_index.py to build the index.",
                task_id[:8],
            )
            answer = await ask_llm(RAG_FALLBACK_SYSTEM, instruction, max_tokens=800, temperature=0.1)
            answer = RAG_FALLBACK_PREFIX + answer

        return {"rag_answer": answer}

    async def _try_mcp(self, query: str) -> list[str]:
        """Call MCP query_rag. Returns [] if unavailable — never raises."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{MCP}/tools/call",
                    json={"tool": "query_rag", "arguments": {"query": query, "top_k": 5}},
                )
            if resp.status_code != 200:
                logger.warning("RAGAgent: MCP query_rag HTTP %s", resp.status_code)
                return []
            body = resp.json()
            result = body.get("result", {})
            if result.get("error"):
                logger.warning("RAGAgent: query_rag error: %s", result["error"])
                return []
            return [
                chunk
                for chunk in result.get("chunks", [])
                if isinstance(chunk, str) and chunk.strip()
            ]
        except Exception as exc:
            logger.warning("RAGAgent: _try_mcp failed: %s", exc)
            return []

    def build_app(self):
        app = super().build_app()

        @app.get("/debug")
        async def debug():
            result = {
                "mcp_url":           MCP,
                "groq_key_set":      bool(settings.groq_api_key),
                "faiss_index_path":  str(settings.faiss_index_path),
                "faiss_chunks_path": str(settings.faiss_chunks_path),
            }
            for key in ("faiss_index_path", "faiss_chunks_path"):
                result[f"{key}_exists"] = os.path.exists(result[key])
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(
                        f"{MCP}/tools/call",
                        json={
                            "tool": "query_rag",
                            "arguments": {"query": "data privacy India", "top_k": 2},
                        },
                    )
                body = r.json()
                res = body.get("result", {})
                result["mcp_rag_test"] = {
                    "http_status":  r.status_code,
                    "chunks_found": len(res.get("chunks", [])),
                    "error":        res.get("error", ""),
                }
            except Exception as e:
                result["mcp_rag_test"] = {"error": str(e)}
            return result

        return app


app = RAGAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)