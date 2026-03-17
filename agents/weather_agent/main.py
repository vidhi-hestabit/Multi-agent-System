import uvicorn
from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing
from common.a2a_types import AgentCard, AgentCapabilities
from agents.weather_agent.handler import WeatherAgentHandler
from agents.weather_agent.skills import SKILLS
from agents.base_agent.base_a2a_server import create_agent_app

def main():
    setup_logging()
    logger = get_logger("weather_agent")
    settings = get_settings()
    init_tracing("weather-agent")

    agent_card = AgentCard(
        name="Weather Agent",
        description="Fetches current weather conditions and generates weather maps for any city.",
        url=f"http://{settings.weather_agent_host}:{settings.weather_agent_port}",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=SKILLS,
    )
    handler = WeatherAgentHandler()
    app = create_agent_app(handler, agent_card)
    logger.info("weather_agent_starting", port=settings.weather_agent_port)

    uvicorn.run( app, host="0.0.0.0", port=settings.weather_agent_port, log_config=None)


if __name__ == "__main__":
    main()
