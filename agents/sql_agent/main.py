from __future__ import annotations
import logging, os, httpx, uvicorn
from agents.base import BaseAgent

logger = logging.getLogger(__name__)
PORT   = int(os.environ.get("SQL_AGENT_PORT", 8005))
HOST   = os.environ.get("SQL_AGENT_HOST", "localhost")
MCP    = os.environ.get("MCP_SERVER_URL", "http://localhost:8000")

class SQLAgent(BaseAgent):
    @property
    def agent_card(self) -> dict:
        return {
            "name":            "SQL Agent",
            "description":     "Answers natural language questions about the Chinook music database.",
            "url":             f"http://{HOST}:{PORT}",
            "version":         "1.0.0",
            "protocolVersion": "0.3.0",
            "requires":        [],
            "produces":        ["sql_answer"],
            "capabilities":    {"streaming": False},
            "skills": [
                {
                    "id":          "query_sql",
                    "name":        "Query SQL",
                    "description": "Natural language → SQL → Chinook DB → friendly answer.",
                    "tags":        ["sql", "database", "music"],
                }
            ],
        }

    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{MCP}/tools/call", json={
                "tool": "query_sql",
                "arguments": {"natural_language_query": instruction},
            })
            resp.raise_for_status()
        result = resp.json().get("result", {})

        if result.get("error"):
            return {"sql_answer": f"Sorry, I couldn't answer that: {result['error']}"}

        answer = result.get("answer", "").strip()
        if not answer:
            rows = result.get("rows", [])
            sql  = result.get("sql", "")
            if not rows:
                answer = "No results found for your query."
            else:
                rows_text = "\n".join(str(r) for r in rows[:10])
                answer = f"SQL: {sql}\n\nResults ({len(rows)} rows):\n{rows_text}"

        return {"sql_answer": answer}


app = SQLAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)