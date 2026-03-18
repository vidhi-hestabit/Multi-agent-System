import uvicorn

from agents.base_agent.base_a2a_server import create_agent_app
from common.a2a_types import AgentCard, AgentCapabilities, AgentSkill
from common.config import get_settings
from common.logging import get_logger, setup_logging
from common.tracing import init_tracing
from orchestrator.handler import OrchestratorHandler


SKILLS = [
    AgentSkill(
        id="orchestrate",
        name="Multi-Agent Orchestration",
        description=(
            "Routes a user query to the correct combination of agents "
            "(news, weather, SQL, RAG, report) by building a dynamic DAG plan."
        ),
        input_modes=["text"],
        output_modes=["text", "data"],
        tags=["orchestrator", "planning", "multi-agent"],
        examples=[
            "Get AI news and email a report",
            "Email weather and news summary together",
            "Check weather, if hot get heatwave news, then email report",
            "How many albums does AC/DC have?",
            "What does Indian law say about cybercrime?",
        ],
    ),
]


def main() -> None:
    setup_logging()
    logger = get_logger("orchestrator")
    settings = get_settings()
    init_tracing("orchestrator")

    agent_card = AgentCard(
        name="Orchestrator",
        description=(
            "Multi-agent orchestrator. Plans a per-query DAG via LLM and "
            "executes agents in parallel topological levels."
        ),
        url=settings.orchestrator_url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=SKILLS,
    )

    handler = OrchestratorHandler()
    app = create_agent_app(handler, agent_card)

    logger.info("orchestrator_starting", port=settings.orchestrator_port)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.orchestrator_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()