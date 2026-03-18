from __future__ import annotations

from agents.base_agent.base_a2a_client import BaseA2AClient
from common.config import get_settings


def _build_registry() -> dict[str, str]:
    """Build name → URL mapping from settings. Called lazily so settings are resolved at use-time."""
    settings = get_settings()
    return {
        "sql_agent":     f"http://{settings.sql_agent_host}:{settings.sql_agent_port}",
        "rag_agent":     f"http://{settings.rag_agent_host}:{settings.rag_agent_port}",
        "news_agent":    f"http://{settings.news_agent_host}:{settings.news_agent_port}",
        "weather_agent": f"http://{settings.weather_agent_host}:{settings.weather_agent_port}",
        "report_agent":  f"http://{settings.report_agent_host}:{settings.report_agent_port}",
        "composio_agent": f"http://{settings.composio_agent_host}:{settings.composio_agent_port}"
    }


def get_agent_client(name: str) -> BaseA2AClient:
    """Return a BaseA2AClient for the named agent. Raises ValueError for unknown agents."""
    registry = _build_registry()
    if name not in registry:
        raise ValueError(
            f"Unknown agent: '{name}'. Registered agents: {list(registry.keys())}"
        )
    return BaseA2AClient(registry[name])


def list_agents() -> list[str]:
    """Return all registered agent names."""
    return list(_build_registry().keys())