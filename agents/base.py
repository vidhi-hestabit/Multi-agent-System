from __future__ import annotations
import logging
import os
import traceback
from abc import ABC, abstractmethod
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

ENTRY_URL = os.environ.get("ENTRY_AGENT_URL", "http://localhost:8010").rstrip("/")


class BaseAgent(ABC):
    @property
    @abstractmethod
    def agent_card(self) -> dict:
        ...
    @abstractmethod
    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        ...

    #  FastAPI app factory ─
    def build_app(self) -> FastAPI:
        app = FastAPI(title=self.agent_card["name"])
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
        )

        # Route 1: A2A spec discovery
        @app.get("/.well-known/agent.json")
        async def agent_json():
            return self.agent_card

        # Route 2: JSON-RPC 2.0 task receiver
        @app.post("/")
        async def rpc(request: Request):
            body   = await request.json()
            rpc_id = body.get("id", "1")
            method = body.get("method", "")
            params = body.get("params", {})
            if method != "tasks/send":
                return JSONResponse({
                    "jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32601, "message": f"Unknown method: {method}"},
                })
            task_id     = params.get("id", "")
            instruction = params.get("instruction", "")

            if not task_id:
                return JSONResponse({
                    "jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32602, "message": "Missing task id in params"},
                })
            # Read full context from the blackboard
            context = await self._read_context(task_id)

            logger.info(
                "[%s] task=%s  instruction=%r",
                self.agent_card["name"], task_id[:8], instruction[:60],
            )
            try:
                updates = await self.run(task_id, instruction, context)
                if updates:
                    await self._write_context(task_id, updates)
                    logger.info(
                        "[%s] task=%s  wrote keys=%s",
                        self.agent_card["name"], task_id[:8], list(updates.keys()),
                    )
                return JSONResponse({
                    "jsonrpc": "2.0", "id": rpc_id,
                    "result": {"status": "done", "keys_written": list((updates or {}).keys())},
                })
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(
                    "[%s] task=%s FAILED:\n%s",
                    self.agent_card["name"], task_id[:8], tb,
                )
                # Return "failed" status so the resolver can mark this agent failed
                return JSONResponse({
                    "jsonrpc": "2.0", "id": rpc_id,
                    "result": {"status": "failed", "error": str(exc)},
                })

        # Route 3: Liveness
        @app.get("/health")
        async def health():
            return {"status": "ok", "agent": self.agent_card["name"]}

        # Route 4: Detailed health — useful for debugging
        @app.get("/health/detail")
        async def health_detail():
            entry_reachable = await self._ping_entry()
            return {
                "agent":           self.agent_card["name"],
                "url":             self.agent_card.get("url"),
                "requires":        self.agent_card.get("requires", []),
                "produces":        self.agent_card.get("produces", []),
                "entry_agent_url": ENTRY_URL,
                "entry_reachable": entry_reachable,
            }
        return app

    #  Blackboard helpers 
    async def _read_context(self, task_id: str) -> dict:
        """GET /tasks/{id}/context from the entry agent task store."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{ENTRY_URL}/tasks/{task_id}/context")
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            logger.error(
                "[%s] _read_context failed task=%s  entry=%s  err=%s",
                self.agent_card["name"], task_id[:8], ENTRY_URL, exc,
            )
            return {}

    async def _write_context(self, task_id: str, updates: dict) -> None:
        """PATCH /tasks/{id}/context on the entry agent task store."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.patch(
                    f"{ENTRY_URL}/tasks/{task_id}/context",
                    json={"updates": updates},
                )
                r.raise_for_status()
        except Exception as exc:
            logger.error(
                "[%s] _write_context FAILED task=%s  entry=%s  updates=%s  err=%s",
                self.agent_card["name"], task_id[:8], ENTRY_URL, list(updates.keys()), exc,
            )
            # Re-raise so the caller knows the write failed
            raise

    async def _ping_entry(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{ENTRY_URL}/health")
            return r.status_code == 200
        except Exception:
            return False