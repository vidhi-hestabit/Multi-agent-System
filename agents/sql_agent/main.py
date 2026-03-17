import uvicorn
from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing
from common.a2a_types import AgentCard, AgentCapabilities
from agents.sql_agent.handler import SQLAgentHandler
from agents.sql_agent.skills import SKILLS
from agents.base_agent.base_a2a_server import create_agent_app


def main():
    setup_logging()
    logger = get_logger("sql_agent")
    settings = get_settings()
    init_tracing("sql-agent")

    agent_card = AgentCard(
        name="SQL Agent",
        description="Answers natural language questions about the Chinook music database using SQL.",
        url=f"http://{settings.sql_agent_host}:{settings.sql_agent_port}",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=SKILLS,
    )

    handler = SQLAgentHandler()
    app = create_agent_app(handler, agent_card)

    logger.info("sql_agent_starting", port=settings.sql_agent_port)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.sql_agent_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
