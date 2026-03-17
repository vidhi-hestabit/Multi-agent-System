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

SYSTEM_PROMPT = """You are a Weather Agent. Your job is to:
1. Interpret the user's weather query (city, conditions they want to know)
2. Present weather data in a clear, friendly way
3. Include temperature, humidity, wind speed, and general conditions
4. Use natural language, avoid raw data dumps

Mention if data is placeholder when applicable.
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

    #  Helpers 
    def _normalize_city(self, city: str) -> str:
        return city.lower().strip()

    def _needs_news(self, state: AgentState) -> str:
        msg = state.get("message", "").lower()
        keywords = {"news", "latest", "events", "happening", "headlines"}
        return "yes" if any(k in msg for k in keywords) else "no"

    def _extract_city(self, query: str) -> str:
        patterns = [
            r"weather (?:in|for|at)\s+([A-Za-z\s]+)",
            r"(?:temperature|forecast|conditions?) (?:in|for|at)\s+([A-Za-z\s]+)",
            r"(?:is it|what(?:'s| is) it like) (?:in|at)\s+([A-Za-z\s]+)",
            r"([A-Za-z\s]+?) weather",
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                city = match.group(1).strip().rstrip("?.,")
                if city:
                    return city

        words = [w for w in query.split() if w and w[0].isupper()]
        return " ".join(words) if words else "London"

    #  Nodes 
    async def _fetch_weather(self, state: AgentState) -> AgentState:
        query = state["message"]
        city_raw = self._extract_city(query)
        city = self._normalize_city(city_raw)

        state.setdefault("metadata", {})["city"] = city
        try:
            weather_data = await asyncio.wait_for( self.mcp.call_tool("fetch_weather", {"city": city, "units": "metric"}),
                timeout=10)
        except Exception:
            logger.exception("weather_fetch_failed")

            weather_data = {
                "city": city,
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
        weather_summary = (
            f"City: {weather_data.get('city')}, {weather_data.get('country')}\n"
            f"Temperature: {weather_data.get('temperature')}°{unit}\n"
            f"Feels like: {weather_data.get('feels_like')}°{unit}\n"
            f"Humidity: {weather_data.get('humidity')}%\n"
            f"Wind speed: {weather_data.get('wind_speed')} m/s\n"
            f"Conditions: {weather_data.get('description')}"
        )
        if is_mock:
            weather_summary = ("[Note: Placeholder data. Configure API key for real data]\n\n" + weather_summary)
        news_ctx = meta.get("news_context", "")
        extra = f"\n\nRelated news:\n{news_ctx}" if news_ctx else ""

        user_message = (
            f"User query: {query}\n\n"
            f"Weather data:\n{weather_summary}{extra}\n\n"
            "Present this in a friendly, natural way."
        )

        try:
            chat_response = await self.llm.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ], max_tokens=512, temperature=0.3
            )
            summary = chat_response.choices[0].message.content

        except Exception:
            logger.exception("weather_llm_failed")
            summary = f"Here's the latest weather update:\n\n{weather_summary}"

        state["result"] = summary
        state["result_data"] = {
            "city": meta.get("city"),
            "weather": weather_data,
            "is_mock": is_mock,
        }
        return state