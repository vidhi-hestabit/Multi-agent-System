from __future__ import annotations
import json
import asyncio
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from common.logging import get_logger
from common.errors import MCPError
from mcp_server.tool_registry import ToolRegistry

logger = get_logger(__name__)

class ToolCallRequest(BaseModel):
    tool: str
    arguments: dict = {}

def create_app(registry: ToolRegistry) -> FastAPI:
    app = FastAPI(title="MCP Tool Server", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "mcp-server", "tools": registry.all_names()}

    @app.get("/tools")
    async def list_tools():
        return {"tools": registry.list_tools()}

    @app.post("/tools/call")
    async def call_tool(request: ToolCallRequest):
        definition = registry.get(request.tool)
        if definition is None:
            raise HTTPException(status_code=404, detail=f"Tool '{request.tool}' not found")

        try:
            logger.info("tool_call", tool=request.tool, arguments=request.arguments)
            result = await definition.handler(**request.arguments)
            # Serialize Pydantic models to dict for JSON response
            if hasattr(result, "model_dump"):
                result = result.model_dump(mode="json")
            return {"tool": request.tool, "result": result}
        except MCPError as e:
            logger.error("tool_error", tool=request.tool, error=str(e))
            raise HTTPException(status_code=422, detail=e.to_dict())
        except TypeError as e:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_ARGUMENTS", "message": str(e)},
            )
        except Exception as e:
            logger.exception("tool_unexpected_error", tool=request.tool)
            raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})

    @app.get("/sse")
    async def sse_endpoint(request: Request):
        async def event_generator() -> AsyncGenerator[str, None]:
            tools_event = {
                "type": "tools",
                "tools": registry.list_tools(),
            }
            yield f"data: {json.dumps(tools_event)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(15)
                ping = {"type": "ping"}
                yield f"data: {json.dumps(ping)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    return app
