from __future__ import annotations
import httpx
from common.a2a_types import (AgentCard, TaskSendRequest, TaskSendResponse, Message, TextPart)
from common.logging import get_logger

logger = get_logger(__name__)

class BaseA2AClient:
    def __init__(self, agent_url: str, timeout: int = 60):
        self.agent_url = agent_url.rstrip("/")
        self.timeout = timeout

    async def send_task(self, text: str, session_id: str | None, metadata: dict | None) -> TaskSendResponse:
        request = TaskSendRequest(
            session_id=session_id,
            message=Message(role="user", parts=[TextPart(text=text)]),
            metadata=metadata or {},
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post( f"{self.agent_url}/tasks/send", json=request.model_dump())
            resp.raise_for_status()

        return TaskSendResponse.model_validate(resp.json())

    async def resume_task( self, task_id: str, text: str, metadata: dict | None = None) -> TaskSendResponse:
        """Send a follow-up message to continue an input-required task."""
        payload = {
            "id": task_id,
            "message": { "role": "user", "parts": [{"type": "text", "text": text}]},
            "metadata": metadata or {},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post( f"{self.agent_url}/tasks/send",json=payload )
            resp.raise_for_status()
        return TaskSendResponse.model_validate(resp.json())

    async def get_agent_card(self) -> AgentCard:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.agent_url}/agent-card")
            resp.raise_for_status()
        return AgentCard.model_validate(resp.json())

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.agent_url}/health")
            return resp.status_code == 200
        except Exception:
            return False
