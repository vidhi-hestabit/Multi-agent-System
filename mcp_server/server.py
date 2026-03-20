from __future__ import annotations
import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from common.logging import get_logger
from mcp_server.app import mcp

logger = get_logger(__name__)

_routes_registered = False


def create_app(transport: str = "sse"):
    global _routes_registered

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "mcp-server"})

    async def list_tools(request: Request) -> JSONResponse:
        tools = await mcp.list_tools()
        return JSONResponse({
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.parameters,
                }
                for t in tools
            ]
        })

    async def call_tool(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"code": "INVALID_JSON", "message": "Request body must be JSON"},
                status_code=422,
            )

        tool_name = body.get("tool")
        arguments  = body.get("arguments", {})

        if not tool_name:
            return JSONResponse(
                {"code": "MISSING_TOOL", "message": "'tool' field is required"},
                status_code=422,
            )

        try:
            result = await mcp.call_tool(tool_name, arguments)
        except Exception as exc:
            logger.error("tool_call_failed", tool=tool_name, error=str(exc))
            return JSONResponse(
                {"code": "TOOL_ERROR", "message": str(exc)},
                status_code=422,
            )

        # Prefer structured_content (already a dict/list), fall back to
        # parsing the text content block (which may be a JSON string).
        if result.structured_content is not None:
            payload = result.structured_content
        else:
            payload = None
            for block in result.content:
                text = getattr(block, "text", None)
                if text is not None:
                    try:
                        payload = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        payload = text
                    break

        return JSONResponse({"tool": tool_name, "result": payload})

    if not _routes_registered:
        mcp._additional_http_routes.extend([
            Route("/health",     endpoint=health,     methods=["GET"]),
            Route("/tools",      endpoint=list_tools, methods=["GET"]),
            Route("/tools/list", endpoint=list_tools, methods=["GET"]),
            Route("/tools/call", endpoint=call_tool,  methods=["POST"]),
        ])
        _routes_registered = True

    return mcp.http_app(transport=transport)