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
    send_message,
    query_sql,
    query_rag,
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

    registry.register(ToolDefinition(
        name=composio_tool.TOOL_NAME,
        description=composio_tool.TOOL_DESCRIPTION,
        input_schema=composio_tool.TOOL_SCHEMA,
        handler=composio_tool.handle,
        tags=["composio", "auth", "connect"],
    ))

    registry.register(ToolDefinition(
        name=send_message.TOOL_NAME,
        description=send_message.TOOL_DESCRIPTION,
        input_schema=send_message.TOOL_SCHEMA,
        handler=send_message.handle,
        tags=["composio", "messaging", "email", "slack", "telegram", "discord"],
    ))

    registry.register(ToolDefinition(
        name=query_sql.TOOL_NAME,
        description=query_sql.TOOL_DESCRIPTION,
        input_schema=query_sql.TOOL_SCHEMA,
        handler=query_sql.handle,
        tags=["sql", "database", "chinook"],
    ))

    registry.register(ToolDefinition(
        name=query_rag.TOOL_NAME,
        description=query_rag.TOOL_DESCRIPTION,
        input_schema=query_rag.TOOL_SCHEMA,
        handler=query_rag.handle,
        tags=["rag", "law", "india", "search"],
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
        port=settings.mcp_server_port,
        transport=settings.mcp_transport,
        tools=registry.all_names(),
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.mcp_server_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
