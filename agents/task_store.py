from __future__ import annotations
import asyncio
import uuid
from datetime import datetime
from typing import Optional

class InMemoryTaskStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        # asyncio.Event per task — lets entry agent await completion
        self._events: dict[str, asyncio.Event] = {}

    #  Write 
    def create(self, query: str, required_outputs: list[str]) -> str:
        task_id = str(uuid.uuid4())
        self._data[task_id] = {
            "context":          {},
            "required_outputs": required_outputs,
            "agent_runs":       {},       # url → "running"|"done"|"failed"
            "final_status":     "running",
            "original_query":   query,
            "created_at":       datetime.utcnow().isoformat(),
            "result":           None,
            "error":            None,
        }
        self._events[task_id] = asyncio.Event()
        return task_id

    def update_context(self, task_id: str, updates: dict) -> None:
        self._data[task_id]["context"].update(updates)

    def mark_agent(self, task_id: str, agent_url: str, status: str) -> None:
        self._data[task_id]["agent_runs"][agent_url] = status

    def complete(self, task_id: str, result: str) -> None:
        task = self._data[task_id]
        task["final_status"] = "completed"
        task["result"]       = result
        self._events[task_id].set()

    def fail(self, task_id: str, error: str) -> None:
        task = self._data[task_id]
        task["final_status"] = "failed"
        task["error"]        = error
        self._events[task_id].set()

    #  Read 

    def get(self, task_id: str) -> Optional[dict]:
        return self._data.get(task_id)

    def get_context(self, task_id: str) -> dict:
        return dict(self._data[task_id]["context"])

    def get_event(self, task_id: str) -> asyncio.Event:
        return self._events[task_id]

    def all(self) -> list[dict]:
        return [{"task_id": k, **v} for k, v in self._data.items()]

store = InMemoryTaskStore()