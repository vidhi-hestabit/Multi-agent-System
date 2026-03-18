import uvicorn
from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing
from common.a2a_types import AgentCard, AgentCapabilities
from agents.rag_agent.handler import RAGAgentHandler
from agents.rag_agent.skills import SKILLS
from agents.base_agent.base_a2a_server import create_agent_app


def main():
    setup_logging()
    logger = get_logger("rag_agent")
    settings = get_settings()
    init_tracing("rag-agent")

    agent_card = AgentCard(
        name="RAG Agent",
        description="Answers Indian law questions using semantic search over the Indian Law dataset.",
        url=f"http://{settings.rag_agent_host}:{settings.rag_agent_port}",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=SKILLS

    )

    handler = RAGAgentHandler()
    app = create_agent_app(handler, agent_card)

    logger.info("rag_agent_starting", port=settings.rag_agent_port)

    uvicorn.run(app, host="0.0.0.0", port=settings.rag_agent_port, log_config=None)

if __name__ == "__main__":
    main()
