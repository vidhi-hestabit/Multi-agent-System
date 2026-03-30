from __future__ import annotations
import logging, os, httpx, uvicorn
from agents.base import BaseAgent
from agents.llm_utils import rewrite_query

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
        history = context.get("history", "")
        search_query = await rewrite_query(instruction, history)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{MCP}/tools/call", json={
                "tool": "query_sql",
                "arguments": {
                    "natural_language_query": search_query,
                    "history": history
                },
            })
            resp.raise_for_status()
        result = resp.json().get("result", {})

        if result.get("error"):
            return {"sql_answer": f"Sorry, I couldn't answer that: {result['error']}"}

        answer = result.get("answer", "").strip()
        if answer:
            return {"sql_answer": answer}
        rows = result.get("rows", [])
        if not rows:
            return {"sql_answer": "No results found for your query."}
        
        lines =[]
        for i,row in enumerate(rows[:15], start =1):
            if isinstance(row,dict):
                parts =  ", ".join(f"{k}: {v}" for k, v in row.items())
                lines.append(f"{i}. {parts}")
            else:
                lines.append(f"{i}. {row}")
            
        total = len(rows)
        summary = f"Found {total} result{'s' if total != 1 else ''}:\n\n" + "\n".join(lines)
        if total > 15:
            summary += f"\n\n...and {total - 15} more."
        return {"sql_answer": summary}

app = SQLAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)