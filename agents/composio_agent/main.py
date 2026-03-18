import uvicorn
from common.config import get_settings
from common.logging import setup_logging, get_logger
from common.tracing import init_tracing
from common.a2a_types import AgentCard, AgentCapabilities
from agents.composio_agent.handler import ComposioAgentHandler
from agents.composio_agent.skills import SKILLS
from agents.base_agent.base_a2a_server import create_agent_app


def main():
   setup_logging()
   logger = get_logger("composio_agent")
   settings = get_settings()
   init_tracing("composio-agent")


   agent_card = AgentCard(
       name="Composio Agent",
       description=(
           "Sends messages and reports via Gmail, Slack, Telegram, or Discord "
           "using Composio integrations. Works independently or with report generation."
       ),
       url=f"http://{settings.composio_agent_host}:{settings.composio_agent_port}",
       version="1.0.0",
       capabilities=AgentCapabilities(
           streaming=False,
           state_transition_history=True,
       ),
       skills=SKILLS,
   )


   handler = ComposioAgentHandler()
   app = create_agent_app(handler, agent_card)


   logger.info("composio_agent_starting",
              host=settings.composio_agent_host,
              port=settings.composio_agent_port)


   uvicorn.run(
       app,
       host="0.0.0.0",
       port=settings.composio_agent_port,
       log_config=None,
   )


if __name__ == "__main__":
   main()