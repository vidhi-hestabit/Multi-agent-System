from __future__ import annotations
import os
import aiosqlite
from groq import AsyncGroq
from common.config import get_settings
from common.logging import get_logger

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

# DB_PATH = os.environ.get("CHINOOK_DB_PATH", "/app/data/chinook.db")

CHINOOK_SCHEMA = """
Tables:
- Artist(ArtistId, Name)
- Album(AlbumId, Title, ArtistId)
- Track(TrackId, Name, AlbumId, MediaTypeId, GenreId, Composer, Milliseconds, Bytes, UnitPrice)
- Genre(GenreId, Name)
- MediaType(MediaTypeId, Name)
- Playlist(PlaylistId, Name)
- PlaylistTrack(PlaylistId, TrackId)
- Employee(EmployeeId, LastName, FirstName, Title, ReportsTo, BirthDate, HireDate, Address, City, State, Country, PostalCode, Phone, Fax, Email)
- Customer(CustomerId, FirstName, LastName, Company, Address, City, State, Country, PostalCode, Phone, Fax, Email, SupportRepId)
- Invoice(InvoiceId, CustomerId, InvoiceDate, BillingAddress, BillingCity, BillingState, BillingCountry, BillingPostalCode, Total)
- InvoiceItem(InvoiceLineId, InvoiceId, TrackId, UnitPrice, Quantity)
"""

SQL_SYSTEM_PROMPT = f"""You are a SQLite SQL expert. Given a natural language question, return ONLY a valid SQLite SQL query. No explanation, no markdown fences.

Schema:
{CHINOOK_SCHEMA}
"""


async def handle(natural_language_query: str) -> dict:
    settings = get_settings()
    db_path = getattr(settings, "chinook_db_path", None) or os.environ.get(
        "CHINOOK_DB_PATH", "/home/chandramohan/Desktop/Multi-agent-System/data/chinook.db"
    )

    try:
        llm = AsyncGroq(api_key=settings.groq_api_key)
        resp = await llm.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SQL_SYSTEM_PROMPT},
                {"role": "user", "content": natural_language_query},
            ],
            max_tokens=512,
            temperature=0.0,
        )
        sql = resp.choices[0].message.content.strip()
        if sql.startswith("```"):
            sql = sql.split("```")[1]
            if sql.startswith("sql"):
                sql = sql[3:]
        sql = sql.strip()
    except Exception as exc:
        logger.error("query_sql_llm_failed", error=str(exc))
        return {"error": f"LLM failed: {exc}", "rows": [], "sql": ""}

    try:
        async with aiosqlite.connect(settings.chinook_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql) as cursor:
                rows = await cursor.fetchall()
                columns = [d[0] for d in cursor.description] if cursor.description else []
                result = [dict(zip(columns, row)) for row in rows]
    except Exception as exc:
        logger.error("query_sql_db_failed", error=str(exc), sql=sql)
        return {"error": f"DB error: {exc}", "rows": [], "sql": sql}

    return {"sql": sql, "rows": result, "total": len(result)}
