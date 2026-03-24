from __future__ import annotations
import logging
import httpx
import uvicorn
from agents.base import BaseAgent
from agents.llm_utils import ask_llm
from common.config import get_settings
from common.prompts.weather_prompts import CITY_EXTRACTION_SYSTEM

logger = logging.getLogger(__name__)
settings = get_settings()
PORT = settings.weather_agent_port
HOST = settings.weather_agent_host
MCP = settings.mcp_server_url


class WeatherAgent(BaseAgent):
    @property
    def agent_card(self) -> dict:
        return {
            "name":            "Weather Agent",
            "description":     "Fetches current weather for any city via OpenWeatherMap.",
            "url":             f"http://{HOST}:{PORT}",
            "version":         "1.0.0",
            "protocolVersion": "0.3.0",
            "requires":        [],
            "produces":        ["weather_data", "weather_data_text", "city_name"],
            "capabilities":    {"streaming": False},
            "skills": [
                {
                    "id":          "fetch_weather",
                    "name":        "Fetch Weather",
                    "description": "Get temperature, humidity, conditions for a city.",
                    "tags":        ["weather"],
                }
            ],
        }

    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        city = await ask_llm(CITY_EXTRACTION_SYSTEM, instruction, max_tokens=20)
        city = city.strip().strip("\"'.").title() or "Delhi"
        logger.info("WeatherAgent: city=%r (from LLM)", city)

        # Verify MCP is reachable
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{MCP}/health")
            if r.status_code != 200:
                raise RuntimeError(f"MCP /health returned {r.status_code}")
        except Exception as exc:
            raise RuntimeError(f"MCP not reachable at {MCP}: {exc}")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{MCP}/tools/call",
                json={"tool": "fetch_weather", "arguments": {"city": city, "units": "metric"}},
            )

        if resp.status_code == 422:
            raise RuntimeError(f"fetch_weather error: {resp.json().get('detail')}")
        resp.raise_for_status()

        data = resp.json().get("result", {})
        if hasattr(data, "model_dump"):
            data = data.model_dump()

        temp    = data.get("temperature", "N/A")
        feels   = data.get("feels_like",  "N/A")
        hum     = data.get("humidity",    "N/A")
        wind    = data.get("wind_speed",  "N/A")
        desc    = data.get("description", "unknown")
        city_r  = data.get("city", city)
        country = data.get("country", "")
        country_str = f", {country}" if country else ""
        text = (
            f"The current weather in {city_r}{country_str} is {desc} "
            f"with the temperature of {temp}°C (feels {feels}°C). "
            f"humidity is at {hum}% and wind is {wind} m/s"
        )
        logger.info("WeatherAgent: %s", text)
        return {"weather_data": data, "weather_data_text": text, "city_name": city_r}


app = WeatherAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)