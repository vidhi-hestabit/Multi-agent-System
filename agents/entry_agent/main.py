from __future__ import annotations

import asyncio
import json
import logging

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from groq import AsyncGroq
from pydantic import BaseModel

from agents.task_store import store
from agents.registry import registry
from agents.resolver import resolve_and_trigger
from common.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
PORT = settings.entry_agent_port
HOST = settings.entry_agent_host

AGENT_URLS = [
    settings.weather_agent_url,
    settings.news_agent_url,
    settings.report_agent_url,
    settings.composio_agent_url,
    settings.sql_agent_url,
    settings.rag_agent_url,
    settings.chat_agent_url
]

# LLM setup from config
_llm = AsyncGroq(api_key=settings.groq_api_key)
_model = settings.groq_model

# All possible output keys across all agents
ALL_OUTPUT_KEYS = {
    "weather_data": "Current weather for a city (temperature, humidity, conditions)",
    "weather_data_text": "Human-readable weather summary string",
    "news_summary": "Summary of recent news articles on a topic",
    "news_articles": "Raw list of news articles (title, url, description)",
    "report_markdown": "A complete formatted Markdown report",
    "message_sent_confirmation": "Confirmation that a message was sent via Composio",
    "sql_answer": "Answer to a Chinook music database question",
    "rag_answer": "Answer to an Indian law question",
    "chat": "A friendly conversational reply (greetings, jokes, general questions, normal chat)",
}

PLANNER_SYSTEM = f"""You are a task planner for a multi-agent AI system.

Available output keys and their meanings:
{chr(10).join(f"  - {k}: {v}" for k, v in ALL_OUTPUT_KEYS.items())}

Given a user query, return ONLY a JSON array of the output keys needed to fully answer it.
No explanation. No markdown fences. Just the raw JSON array.

Rules:
- "message_sent_confirmation" is needed whenever the user says:
  send, email, mail, post to Slack, message via Telegram, Discord, deliver, share, notify.
- "report_markdown" is needed before "message_sent_confirmation" if a report is requested.
- "news_summary" is needed before "report_markdown" for news-based reports.
- Never include keys unrelated to the query.

Examples:
  "What is the weather in Mumbai?"
    → ["weather_data","weather_data_text"]

  "Get AI news"
    → ["news_summary"]

  "Weather in Delhi and latest news, make a report"
    → ["weather_data","weather_data_text","news_summary","report_markdown"]

  "Get weather and news, make a report, send it via Gmail"
    → ["weather_data","weather_data_text","news_summary","report_markdown","message_sent_confirmation"]

  "Latest AI news, post it on Slack"
    → ["news_summary","report_markdown","message_sent_confirmation"]

  "How many albums does AC/DC have?"
    → ["sql_answer"]

  "What does Indian law say about theft?"
    → ["rag_answer"]

  "hi", "hello", "how are you", "tell me a joke", "good morning", "what is 2+2"
    → ["chat"]

  "email me a poem on cow at me@gmail.com"
    → ["chat", "report_markdown", "message_sent_confirmation"]
"""


# Request / Response models

class QueryRequest(BaseModel):
    query: str

    # Optional direct hints — injected into context before resolver runs
    composio_app: str = ""        # e.g. GMAIL | SLACK | TELEGRAM | DISCORD
    composio_recipient: str = ""  # email / channel id / chat id

    # Convenience alias kept for compatibility
    email_recipient: str = ""


class QueryResponse(BaseModel):
    task_id: str
    status: str
    result: str | None = None
    error: str | None = None
    agents_called: list[str] = []


# App factory

def create_app() -> FastAPI:
    app = FastAPI(title="Entry Agent / Coordinator", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    #  Startup: discover all agent cards via /.well-known/agent.json
    @app.on_event("startup")
    async def startup():
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        )
        await registry.discover(AGENT_URLS)
        logger.info("Agents discovered: %s", [c["name"] for c in registry.all()])

    #  User-facing query endpoint 
    @app.post("/query", response_model=QueryResponse)
    async def query(req: QueryRequest):
        """
        1. LLM decides which output keys are needed.
        2. Create task in blackboard.
        3. Inject optional hints (app, recipient) into context.
        4. Fire resolver — starts the dynamic agent chain.
        5. Wait up to request_timeout seconds for completion.
        6. Return final result.
        """
        required = await _plan_outputs(req.query)
        if not required:
            return QueryResponse(
                task_id="",
                status="failed",
                error="Could not determine required outputs from query.",
                agents_called=[],
            )

        task_id = store.create(req.query, required)
        logger.info("Created task %s required=%s", task_id[:8], required)

        # Inject routing hints into context so composio_agent can read them
        hints: dict[str, str] = {}

        if req.composio_app:
            hints["composio_app"] = req.composio_app.upper()

        if req.composio_recipient:
            hints["composio_recipient"] = req.composio_recipient

        if req.email_recipient:
            hints["email_recipient"] = req.email_recipient
            hints.setdefault("composio_app", "GMAIL")

        if hints:
            store.update_context(task_id, hints)

        # Fire resolver as background task
        asyncio.create_task(resolve_and_trigger(task_id))

        # Wait for completion
        event = store.get_event(task_id)
        try:
            await asyncio.wait_for(event.wait(), timeout=settings.request_timeout)
        except asyncio.TimeoutError:
            store.fail(task_id, f"Timeout after {settings.request_timeout} seconds")

        task = store.get(task_id)
        agents_called = [
            agent_name
            for agent_name, status in task.get("agent_runs", {}).items()
            if status in ("done", "failed")
        ]

        return QueryResponse(
            task_id=task_id,
            status=task["final_status"],
            result=task.get("result"),
            error=task.get("error"),
            agents_called=agents_called,
        )

    #  Task Store REST API (used by specialized agents) 

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        task = store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        return {"task_id": task_id, **task}

    @app.get("/tasks/{task_id}/context")
    async def get_context(task_id: str):
        task = store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        return store.get_context(task_id)

    @app.patch("/tasks/{task_id}/context")
    async def patch_context(task_id: str, body: dict):
        """Agents call PATCH here to write their outputs into the blackboard."""
        task = store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        updates = body.get("updates", {})
        if not isinstance(updates, dict):
            raise HTTPException(status_code=400, detail="'updates' must be a dictionary")

        store.update_context(task_id, updates)
        logger.info("Context updated task=%s keys=%s", task_id[:8], list(updates.keys()))

        # Re-run resolver after every context write so next eligible agents fire
        asyncio.create_task(resolve_and_trigger(task_id))
        return {"ok": True, "keys_written": list(updates.keys())}

    @app.get("/tasks")
    async def list_tasks():
        return store.all()

    #  Agent admin ─

    @app.get("/.well-known/agent.json")
    async def entry_card():
        return {
            "name": "Entry Agent",
            "description": "User-facing coordinator. Plans tasks with LLM, resolves agents.",
            "url": settings.entry_agent_url,
            "version": "1.0.0",
            "protocolVersion": "0.3.0",
            "requires": [],
            "produces": [],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "route",
                    "name": "Route Query",
                    "description": "Plan and execute any multi-agent task.",
                }
            ],
        }

    @app.get("/agents")
    async def list_agents():
        """Show all discovered agents with their requires/produces."""
        return registry.summary()

    @app.post("/agents/refresh")
    async def refresh_agents():
        """Re-discover all agents."""
        await registry.discover(AGENT_URLS)
        return registry.summary()

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "agents": len(registry.all()),
            "active_tasks": sum(
                1 for t in store.all()
                if t["final_status"] == "running"
            ),
        }

    return app


#  LLM planner 

async def _plan_outputs(query: str) -> list[str]:
    try:
        r = await _llm.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": query},
            ],
            max_tokens=120,
            temperature=0.0,
        )

        raw = r.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        keys = json.loads(raw)

        if not isinstance(keys, list):
            logger.warning("Planner response is not a list: %s", raw)
            return []

        valid = [k for k in keys if k in ALL_OUTPUT_KEYS]
        logger.info("Planner → required_outputs=%s", valid)
        return valid

    except Exception as exc:
        logger.exception("LLM planner failed: %s", exc)
        return []


#  Entry point ─

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)