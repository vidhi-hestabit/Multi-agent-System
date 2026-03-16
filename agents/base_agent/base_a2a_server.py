from __future__ import annotations
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Optional
from common.a2a_types import ( AgentCard, Task, TaskStatus, TaskState, Message, TextPart)
from common.logging import get_logger

logger = get_logger(__name__)

# In-memory task store keyed by task id
_tasks: dict[str, Task] = {}

class SendPayload(BaseModel):
    id: Optional[str] = None
    session_id: Optional[str] = None
    message: dict
    metadata: dict[str, Any] = {}

def create_agent_app(handler, agent_card: AgentCard) -> FastAPI:
    app = FastAPI( title=agent_card.name, description=agent_card.description, version=agent_card.version )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": agent_card.name}

    @app.get("/agent-card")
    async def get_agent_card():
        return agent_card.model_dump()

    @app.post("/tasks/send")
    async def send_task(payload: SendPayload) -> dict:
        task_id = payload.id or str(uuid.uuid4())

        # Build the incoming message
        raw_msg = payload.message
        parts = []
        for p in raw_msg.get("parts", []):
            if p.get("type") == "text":
                parts.append(TextPart(text=p["text"]))
        incoming = Message(role="user", parts=parts)

        # Resume existing task or start a new one
        if task_id in _tasks:
            task = _tasks[task_id]
            task.history.append(incoming)
            # Merge any persisted langgraph state back into metadata
            stored_state = task.metadata.pop("__langgraph_state__", {})
            if stored_state:
                task.metadata.update(stored_state.get("metadata", {}))
                # Re-inject persisted keys so the handler can continue
                for k, v in stored_state.items():
                    if k != "metadata":
                        task.metadata[f"__state_{k}"] = v
        else:
            task = Task( id=task_id, session_id=payload.session_id, history=[incoming], metadata=payload.metadata )
            _tasks[task_id] = task
        task.status = TaskStatus(state=TaskState.WORKING)

        try:
            task = await handler.handle(task)
        except Exception as exc:
            logger.error("task_handler_error", task_id=task_id, error=str(exc))
            task.status = TaskStatus(state=TaskState.FAILED, message=Message(role="agent", parts=[TextPart(text=str(exc))]))
        _tasks[task_id] = task
        return {"id": task.id, "status": task.status.model_dump(), "artifacts": [a.model_dump() for a in task.artifacts]}

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> dict:
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "id": task.id,
            "status": task.status.model_dump(),
            "artifacts": [a.model_dump() for a in task.artifacts],
            "history": [m.model_dump() for m in task.history]
        }
    return app
