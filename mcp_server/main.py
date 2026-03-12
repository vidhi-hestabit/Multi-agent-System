import uvicorn
from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing
from mcp_server.tool_registry import ToolRegistry, ToolDefinition
from mcp_server.server import create_app

from mcp_server.tools import (
    fetch_news,
    fetch_weather,
    generate_report,
    composio_tool,
)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(ToolDefinition(
        name=fetch_news.TOOL_NAME,
        description=fetch_news.TOOL_DESCRIPTION,
        input_schema=fetch_news.TOOL_SCHEMA,
        handler=fetch_news.handle,
        tags=["news", "information"],
    ))

    registry.register(ToolDefinition(
        name=fetch_weather.TOOL_NAME,
        description=fetch_weather.TOOL_DESCRIPTION,
        input_schema=fetch_weather.TOOL_SCHEMA,
        handler=fetch_weather.handle,
        tags=["weather", "information"],
    ))

    registry.register(ToolDefinition(
        name=generate_report.TOOL_NAME,
        description=generate_report.TOOL_DESCRIPTION,
        input_schema=generate_report.TOOL_SCHEMA,
        handler=generate_report.handle,
        tags=["report", "document"],
    ))

    # Composio: OAuth connection manager
    registry.register(ToolDefinition(
        name=composio_tool.TOOL_NAME,
        description=composio_tool.TOOL_DESCRIPTION,
        input_schema=composio_tool.TOOL_SCHEMA,
        handler=composio_tool.handle,
        tags=["composio", "auth", "connect"],
    ))

    registry.register(ToolDefinition(
        name=composio_tool.TOOL_NAME,
        description=composio_tool.TOOL_DESCRIPTION,
        input_schema=composio_tool.TOOL_SCHEMA,
        handler=composio_tool.handle,
        tags=["composio", "connect", "execute"],
    ))

    return registry

def main():
    setup_logging()
    logger = get_logger("mcp_server")
    settings = get_settings()
    init_tracing("mcp-server")

    registry = build_registry()
    app = create_app(registry)

    logger.info(
        "mcp_server_starting",
        host="0.0.0.0",
        port=settings.mcp_server_port,
        tools=registry.all_names(),
        transport=settings.mcp_transport,
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.mcp_server_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
