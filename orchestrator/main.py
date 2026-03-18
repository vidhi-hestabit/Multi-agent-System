import uvicorn
from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing
from common.a2a_types import AgentCard, AgentCapabilities, AgentSkill
from orchestrator.handler import OrchestratorHandler
from agents.base_agent.base_a2a_server import create_agent_app


def main():
    setup_logging()
    logger = get_logger("orchestrator")
    settings = get_settings()
    init_tracing("orchestrator")

    agent_card = AgentCard(
        name="Orchestrator",
        description=(
            "Multidirectional DAG orchestrator. Accepts a natural language query, "
            "uses an LLM to build a per-query execution plan, then runs agents in "
            "topological order — parallel within each dependency level."
        ),
        url=f"http://{settings.orchestrator_host}:{settings.orchestrator_port}",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="orchestrate",
                name="Orchestrate Agents",
                description="Plan and execute a multi-agent DAG for any user query.",
                input_modes=["text"],
                output_modes=["text", "data"],
                tags=["orchestration", "planning", "dag", "multi-agent"],
                examples=[
                    "Get AI news and email a report",
                    "Email weather and news summary together",
                    "Check weather, if hot get heatwave news, then email report",
                    "Query the music database and summarise top artists",
                ],
            )
        ],
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