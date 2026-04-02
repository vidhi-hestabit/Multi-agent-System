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
from common.db import get_db
from common.vector_store import get_vector_store
from common.prompts.entry_prompts import ALL_OUTPUT_KEYS, PLANNER_SYSTEM

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
    settings.chat_agent_url,
]

_llm = AsyncGroq(api_key=settings.groq_api_key)
_model = settings.groq_model


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    session_id: str = ""  # ID for the conversation session
    user_email: str = ""  # email from auth session
    
    # Optional direct hints — injected into context before resolver runs
    composio_app: str = ""         # e.g. GMAIL | SLACK | TELEGRAM | DISCORD
    composio_recipient: str = ""   # email / channel id / chat id

    # Convenience alias kept for compatibility
    email_recipient: str = ""


class QueryResponse(BaseModel):
    task_id: str
    status: str
    result: str | None = None
    error: str | None = None
    agents_called: list[str] = []


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(title="Entry Agent / Coordinator", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        )
        await registry.discover(AGENT_URLS)
        logger.info("Agents discovered: %s", [c["name"] for c in registry.all()])

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

        hints: dict[str, str] = {}
        if req.user_email:
            hints["user_email"] = req.user_email
            # Fetch user_id from MongoDB
            try:
                db = get_db()
                u = await db.users.find_one({"email": req.user_email})
                if u:
                    hints["user_id"] = str(u["_id"])
                    logger.info("Found MongoDB user_id=%s for email=%s", hints["user_id"], req.user_email)
            except Exception as e:
                logger.warning("Failed to lookup user_id for %s: %s", req.user_email, e)
            
            # Fetch session history if session_id is provided
            if req.session_id:
                try:
                    db = get_db()
                    # Fetch linear session history from Pinecone (replaces MongoDB)
                    vs = get_vector_store()
                    history_docs = await vs.get_session_history(req.session_id)
                    
                    # Also fetch relevant semantic context from ALL previous chats across all sessions
                    # Perform async search
                    semantic_context = await vs.query_context(user_email=req.user_email, query=req.query)
                    
                    if history_docs or semantic_context:
                        logger.info("Found %d previous chats + semantic search results from Pinecone", len(history_docs))
                        
                        linear_history = "\n".join([f"User: {c['query']}\nNexus: {c['result']}" for c in history_docs])
                        
                        full_history = ""
                        if semantic_context:
                            full_history += f"Relevant background from previous conversations:\n{semantic_context}\n\n"
                        
                        if linear_history:
                            full_history += f"Recent session history:\n{linear_history}"
                            
                        hints["history"] = full_history.strip()
                        
                        # Restore previous context data from the latest message that HAS context
                        prev_ctx = {}
                        for doc in reversed(history_docs):
                            if doc.get("context_data"):
                                prev_ctx = doc["context_data"]
                                logger.info("Restoring context from latest valid doc: %s", doc.get("query"))
                                break
                        
                        if prev_ctx:
                            logger.info("Keys in found context: %s", list(prev_ctx.keys()))
                            keys_to_skip = {
                                "chat", "composio_app", "history", "user_email",
                                "report_markdown", "news_summary", "weather_data_text",
                                "sql_answer", "rag_answer", "message_sent_confirmation"
                            }
                            restore_ctx = {}
                            for k, v in prev_ctx.items():
                                if k in keys_to_skip: continue
                                # Don't restore failed message confirmations
                                if k == "message_sent_confirmation" and ("failed" in str(v).lower() or "not connected" in str(v).lower()):
                                    continue
                                restore_ctx[k] = v

                            if restore_ctx:
                                logger.info("Restoring keys from session: %s", list(restore_ctx.keys()))
                                store.update_context(task_id, restore_ctx)
                            else:
                                logger.info("No reusable keys found in session context (all were skipped or failed)")
                        else:
                            logger.info("No history document has context_data")
                    else:
                        logger.info("No history documents found for session=%s", req.session_id)
                except Exception as e:
                    logger.error("Failed to fetch session history: %s", e, exc_info=True)
            else:
                # Fallback: Fetch last 5 global chats for this user (legacy/global context)
                try:
                    db = get_db()
                    cursor = db.chats.find({"user_email": req.user_email}).sort("created_at", -1).limit(5)
                    history_docs = await cursor.to_list(length=5)
                    if history_docs:
                        history_str = "\n".join([f"User: {c['query']}\nNexus: {c['result']}" for c in reversed(history_docs)])
                        hints["history"] = history_str
                        prev_ctx = history_docs[0].get("context_data", {})
                        if prev_ctx:
                            keys_to_skip = {"chat", "composio_app", "history", "user_email"}
                            restore_ctx = {k:v for k,v in prev_ctx.items() if k not in keys_to_skip}
                            if restore_ctx:
                                store.update_context(task_id, restore_ctx)
                except Exception as e:
                    logger.warning("Failed to fetch global history: %s", e)

        if req.composio_app:
            hints["composio_app"] = req.composio_app.upper()
        if req.composio_recipient:
            hints["composio_recipient"] = req.composio_recipient
        if req.email_recipient:
            hints["email_recipient"] = req.email_recipient
            hints.setdefault("composio_app", "GMAIL")
        if hints:
            store.update_context(task_id, hints)

        asyncio.create_task(resolve_and_trigger(task_id))

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

        # Save to Pinecone if successful and session_id/user_email are present
        if task["final_status"] == "completed" and req.user_email and req.session_id:
            try:
                vs = get_vector_store()
                # Prepare metadata including context data for restoration
                # We exclude temporary or agent-specific outputs to keep context clean
                context = store.get_context(task_id)
                keys_to_skip = {"chat", "history", "user_email"}
                clean_context = {k: v for k, v in context.items() if k not in keys_to_skip}
                
                await vs.upsert_session(
                    user_email=req.user_email,
                    session_id=req.session_id,
                    query=req.query,
                    result=task.get("result", ""),
                    metadata={
                        "agents_called": agents_called,
                        "status": "completed",
                        "context_data": clean_context
                    }
                )
                logger.info("Saved interaction to Pinecone session=%s", req.session_id)
            except Exception as e:
                logger.error("Failed to save to Pinecone: %s", e)

        return QueryResponse(
            task_id=task_id,
            status=task["final_status"],
            result=task.get("result"),
            error=task.get("error"),
            agents_called=agents_called,
        )

    # ------------------------------------------------------------------
    # Task Store REST API (used by specialised agents via blackboard)
    # ------------------------------------------------------------------

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

        asyncio.create_task(resolve_and_trigger(task_id))
        return {"ok": True, "keys_written": list(updates.keys())}

    @app.get("/tasks")
    async def list_tasks():
        return store.all()

    # ------------------------------------------------------------------
    # Agent admin
    # ------------------------------------------------------------------

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
        return registry.summary()

    @app.post("/agents/refresh")
    async def refresh_agents():
        await registry.discover(AGENT_URLS)
        return registry.summary()

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "agents": len(registry.all()),
            "active_tasks": sum(
                1 for t in store.all() if t["final_status"] == "running"
            ),
        }

    return app


# ---------------------------------------------------------------------------
# LLM planner
# ---------------------------------------------------------------------------

async def _plan_outputs(query: str) -> list[str]:
    try:
        r = await _llm.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user",   "content": query},
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)