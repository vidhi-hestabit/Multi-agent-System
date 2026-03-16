from __future__ import annotations
import httpx
from common.config import get_settings
from common.errors import MCPError
from common.logging import get_logger

logger = get_logger(__name__)

class BaseMCPClient:
    """Thin HTTP client that calls the central MCP tool server."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.mcp_server_url

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        payload = {"tool": tool_name, "arguments": arguments}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{self.base_url}/tools/call", json=payload)
        except httpx.RequestError as exc:
            raise MCPError(f"MCP server unreachable: {exc}") from exc

        if resp.status_code != 200:
            raise MCPError( f"MCP tool '{tool_name}' failed with status {resp.status_code}: {resp.text}")
        return resp.json()

    async def list_tools(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.base_url}/tools/list")
            resp.raise_for_status()
        return resp.json().get("tools", [])
