import uvicorn

from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing

# Tool imports trigger @mcp.tool() registration at import time.
from mcp_server.tools import (fetch_news,
    fetch_weather,
    generate_report,
    composio_tool,
    send_message,
    query_sql,
    query_rag,
)

from mcp_server.server import create_app


def main():
    setup_logging()
    logger = get_logger("mcp_server")
    settings = get_settings()
    init_tracing("mcp-server")

    transport = settings.mcp_transport  # "sse" or "http"
    app = create_app(transport=transport)

    mcp_endpoint = "/sse" if transport == "sse" else "/mcp"
    logger.info(
        "mcp_server_starting",
        host="0.0.0.0",
        port=settings.mcp_server_port,
        transport=transport,
        mcp_endpoint=mcp_endpoint,
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.mcp_server_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()