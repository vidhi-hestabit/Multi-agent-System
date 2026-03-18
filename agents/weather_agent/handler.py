from __future__ import annotations
import re
import asyncio
from groq import AsyncGroq
from common.config import get_settings
from common.logging import get_logger
from agents.base_agent.base_handler import BaseHandler, AgentState
from agents.base_agent.base_mcp_client import BaseMCPClient
from agents.base_agent.base_a2a_client import BaseA2AClient

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a Weather Agent.
Present weather data clearly and naturally.
Do not invent failures if valid weather data is provided.
If weather data is unavailable, say that live weather could not be fetched.
"""

class WeatherAgentHandler(BaseHandler):
    def __init__(self):
        self.settings = get_settings()
        self.mcp = BaseMCPClient()
        self.llm = AsyncGroq(api_key=self.settings.groq_api_key)
        super().__init__()

    def _build_graph(self):
        self.add_node("fetch_weather", self._fetch_weather)
        self.add_node("enrich_with_news", self._enrich_with_news)
        self.add_node("summarize", self._summarize)

        self.set_entry("fetch_weather")

        self.add_conditional_edges(
            "fetch_weather",
            self._needs_news,
            {"yes": "enrich_with_news", "no": "summarize"},
        )

        self.add_edge("enrich_with_news", "summarize")
        self.finish("summarize")

    def _normalize_city(self, city: str) -> str:
        return city.lower().strip()

    def _needs_news(self, state: AgentState) -> str:
        msg = state.get("message", "").lower()
        keywords = {"news", "latest", "events", "happening", "headlines"}
        return "yes" if any(k in msg for k in keywords) else "no"

    def _extract_city(self, query: str) -> str:
        query = query.strip()

        patterns = [
            r"weather (?:in|for|at|of)\s+([A-Za-z\s]+)",
            r"(?:temperature|forecast|conditions?) (?:in|for|at|of)\s+([A-Za-z\s]+)",
            r"(?:is it|what(?:'s| is) it like) (?:in|at)\s+([A-Za-z\s]+)",
            r"([A-Za-z\s]+?) weather",
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                city = match.group(1).strip().rstrip("?.,")
                if city:
                    return city

        cleaned = re.sub(r"[^A-Za-z\s]", " ", query).strip()
        words = cleaned.split()
        if words:
            return words[-1]

        return ""

    async def _fetch_weather(self, state: AgentState) -> AgentState:
        query = state["message"]
        city_raw = self._extract_city(query)
        city = self._normalize_city(city_raw)

        state.setdefault("metadata", {})["city"] = city

        try:
            weather_data = await asyncio.wait_for(
                self.mcp.call_tool("fetch_weather", {"city": city, "units": "metric"}),
                timeout=10,
            )

            logger.info("raw_weather_response", weather_data=weather_data)

            if isinstance(weather_data, dict):
                if "data" in weather_data and isinstance(weather_data["data"], dict):
                    weather_data = weather_data["data"]
                elif "result" in weather_data and isinstance(weather_data["result"], dict):
                    weather_data = weather_data["result"]

            if not isinstance(weather_data, dict):
                raise ValueError(f"Unexpected weather response type: {type(weather_data)}")

            expected_keys = {"temperature", "humidity", "wind_speed", "description"}
            if not any(k in weather_data for k in expected_keys):
                raise ValueError(f"Weather response missing expected keys: {weather_data}")

            weather_data.setdefault("city", city.title())
            weather_data.setdefault("country", "")
            weather_data.setdefault("feels_like", weather_data.get("temperature"))
            weather_data.setdefault("humidity", 0)
            weather_data.setdefault("wind_speed", 0)
            weather_data.setdefault("description", "Unknown")
            weather_data["_mock"] = False

        except Exception as e:
            logger.exception("weather_fetch_failed", error=str(e))
            weather_data = {
                "city": city.title(),
                "country": "Unknown",
                "temperature": 0,
                "feels_like": 0,
                "humidity": 0,
                "wind_speed": 0,
                "description": "unavailable",
                "icon": "",
                "_mock": True,
            }

        state["metadata"]["weather"] = weather_data
        state["metadata"]["is_mock"] = weather_data.get("_mock", False)
        return state

    async def _enrich_with_news(self, state: AgentState) -> AgentState:
        if not self.settings.news_agent_url:
            state["metadata"]["news_context"] = ""
            return state

        city = state["metadata"].get("city", "")
        query = state["message"]
        news_query = f"weather news {city}" if city else query

        try:
            client = BaseA2AClient(self.settings.news_agent_url, timeout=30)
            response = await client.send_task(news_query)
            news_text = ""
            if response.status.message:
                news_text = response.status.message.text()
            state["metadata"]["news_context"] = news_text
            logger.info("weather_agent_fetched_news", chars=len(news_text))
        except Exception:
            logger.exception("weather_news_enrich_failed")
            state["metadata"]["news_context"] = ""

        return state

    async def _summarize(self, state: AgentState) -> AgentState:
        query = state["message"]
        meta = state.get("metadata", {})
        weather_data = meta.get("weather", {})
        is_mock = meta.get("is_mock", False)

        unit = weather_data.get("unit_symbol", "C")
        city = weather_data.get("city", meta.get("city", "Unknown"))
        country = weather_data.get("country", "")
        temperature = weather_data.get("temperature", "N/A")
        feels_like = weather_data.get("feels_like", "N/A")
        humidity = weather_data.get("humidity", "N/A")
        wind_speed = weather_data.get("wind_speed", "N/A")
        description = weather_data.get("description", "Unknown")

        if is_mock:
            summary = (
                f"I couldn’t fetch live weather data for {city.title()} right now.\n\n"
                f"Please check whether the weather API is configured correctly and whether "
                f"the MCP tool is returning valid data."
            )
        else:
            summary = (
                f"Current weather in {city.title()}"
                f"{', ' + country if country else ''}:\n"
                f"- Temperature: {temperature}°{unit}\n"
                f"- Feels like: {feels_like}°{unit}\n"
                f"- Humidity: {humidity}%\n"
                f"- Wind speed: {wind_speed} m/s\n"
                f"- Conditions: {description}"
            )

        news_ctx = meta.get("news_context", "")
        if news_ctx:
            summary += f"\n\nRelated weather news:\n{news_ctx}"

        state["result"] = summary
        state["result_data"] = {
            "query": query,
            "city": meta.get("city"),
            "weather": weather_data,
            "is_mock": is_mock,
        }
        return state