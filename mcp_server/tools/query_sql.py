from __future__ import annotations
import json
import os
import aiosqlite
from groq import AsyncGroq
from common.config import get_settings
from common.logging import get_logger
from common.prompts.sql_prompts import SQL_GENERATION_SYSTEM, SQL_ANSWER_SYSTEM
from mcp_server.app import mcp

logger = get_logger(__name__)

TOOL_NAME = "query_sql"
TOOL_DESCRIPTION = "Convert a natural language question to SQL and execute it on the Chinook SQLite database."
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "natural_language_query": {
            "type": "string",
            "description": "The natural language question to answer from the database",
        },
    },
    "required": ["natural_language_query"],
}


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(natural_language_query: str) -> dict:
    settings = get_settings()
    db_path = getattr(settings, "chinook_db_path", None) or os.environ.get(
        "CHINOOK_DB_PATH", "/home/vidhiajmera/Desktop/multi-agent-system/data/chinook.db"
    )
    llm = AsyncGroq(api_key=settings.groq_api_key)

    try:
        sql_resp = await llm.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SQL_GENERATION_SYSTEM},
                {"role": "user",   "content": natural_language_query},
            ],
            max_tokens=512,
            temperature=0.0,
        )
        sql = sql_resp.choices[0].message.content.strip()

        # Strip any residual markdown fences the model may have added
        if sql.startswith("```"):
            sql = sql.split("```")[1]
            if sql.startswith("sql"):
                sql = sql[3:]
        sql = sql.strip()

    except Exception as exc:
        logger.error("query_sql_llm_failed", error=str(exc))
        return {"error": f"LLM failed: {exc}", "rows": [], "sql": "", "answer": ""}

    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql) as cursor:
                rows = await cursor.fetchall()
                columns = [d[0] for d in cursor.description] if cursor.description else []
                result = [dict(zip(columns, row)) for row in rows]

    except Exception as exc:
        logger.error("query_sql_db_failed", error=str(exc), sql=sql)
        return {"error": f"DB error: {exc}", "rows": [], "sql": sql, "answer": ""}
    try:
        rows_text = json.dumps(result, ensure_ascii=False) if result else "No rows returned."

        answer_resp = await llm.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SQL_ANSWER_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"User question: {natural_language_query}\n\n"
                        f"Query results:\n{rows_text}"
                    ),
                },
            ],
            max_tokens=200,
            temperature=0.3,
        )
        answer = answer_resp.choices[0].message.content.strip()

    except Exception as exc:
        logger.error("query_sql_answer_llm_failed", error=str(exc))
        answer = f"Query returned {len(result)} row(s)."

    return {
        "sql":    sql,
        "rows":   result,
        "total":  len(result),
        "answer": answer
    }