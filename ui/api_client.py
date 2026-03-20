from __future__ import annotations
import httpx
from common.config import get_settings

settings = get_settings()

class OrchestratorClient:

    def __init__(self):
        self.base_url = settings.orchestrator_url
        self.timeout  = settings.request_timeout

    async def query(self, user_query: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.base_url}/query",
                json={"query": user_query, "stream": False},
            )
            r.raise_for_status()
        return r.json()

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{self.base_url}/health")
            r.raise_for_status()
        return r.json()

    async def list_agents(self) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base_url}/agents")
            r.raise_for_status()
        return r.json()


class AgentDirectClient:
    """
    Sends a follow-up message directly to an agent that is in input-required state,
    bypassing the orchestrator so the task context is preserved.
    """

    _AGENT_URLS: dict[str, str] = {
        "news_agent":    settings.news_agent_url,
        "weather_agent": settings.weather_agent_url,
        "report_agent":  settings.report_agent_url,
        
    }

    def __init__(self, agent_name: str):
        self.base_url = self._AGENT_URLS.get(agent_name, settings.report_agent_url)
        self.timeout  = 90

    async def resume(self, task_id: str, reply: str) -> dict:
        payload = {
            "id":      task_id,
            "message": {
                "role":  "user",
                "parts": [{"type": "text", "text": reply}],
            },
            "metadata": {}
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post( f"{self.base_url}/tasks/send", json=payload )
            r.raise_for_status()
        return r.json()
