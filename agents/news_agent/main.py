import uvicorn
from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing
from common.a2a_types import AgentCard, AgentCapabilities
from agents.news_agent.handler import NewsAgentHandler
from agents.news_agent.skills import SKILLS
from agents.base_agent.base_a2a_server import create_agent_app


def main():
    setup_logging()
    logger = get_logger("news_agent")
    settings = get_settings()
    init_tracing("news-agent")

    agent_card = AgentCard(
        name="News Agent",
        description="Fetches and summarizes news articles on any topic using NewsAPI.",
        url=f"http://{settings.news_agent_host}:{settings.news_agent_port}",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=SKILLS,
    )

    handler = NewsAgentHandler()
    app = create_agent_app(handler, agent_card)

    logger.info("news_agent_starting", port=settings.news_agent_port)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.news_agent_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()