from __future__ import annotations
from agents.base_agent.base_a2a_client import BaseA2AClient
from common.config import get_settings

settings = get_settings()

AGENT_REGISTRY: dict[str, str] = {
    "sql_agent":     f"http://{settings.sql_agent_host}:{settings.sql_agent_port}",
    "rag_agent":     f"http://{settings.rag_agent_host}:{settings.rag_agent_port}",
    "news_agent":    f"http://{settings.news_agent_host}:{settings.news_agent_port}",
    "weather_agent": f"http://{settings.weather_agent_host}:{settings.weather_agent_port}",
    "report_agent":  f"http://{settings.report_agent_host}:{settings.report_agent_port}",
}


def get_agent_client(name: str) -> BaseA2AClient:
    """Return a lazy BaseA2AClient for the named agent."""
    if name not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: '{name}'. Registered agents: {list(AGENT_REGISTRY.keys())}")
    return BaseA2AClient(AGENT_REGISTRY[name])


def register_agent(name: str, url: str) -> None:
    """Dynamically register a new agent without touching other files."""
    AGENT_REGISTRY[name] = url