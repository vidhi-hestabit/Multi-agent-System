from __future__ import annotations
import httpx
from datetime import datetime
from common.config import get_settings
from common.errors import MCPError
from common.models import WeatherData
from mcp_server.app import mcp

TOOL_NAME = "fetch_weather"
TOOL_DESCRIPTION = "Fetch current weather conditions for a city."
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {
            "type": "string",
            "description": "City name (e.g. 'London', 'Tokyo', 'New York')",
        },
        "units": {
            "type": "string",
            "description": "Temperature units: 'metric' (Celsius), 'imperial' (Fahrenheit), or 'standard' (Kelvin).",
            "enum": ["metric", "imperial", "standard"],
            "default": "metric",
        },
    },
    "required": ["city"],
}


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(city: str, units: str = "metric") -> WeatherData:
    settings = get_settings()
    api_key = settings.openweather_api_key

    if not api_key:
        raise MCPError("OPENWEATHER_API_KEY is not configured in .env", tool=TOOL_NAME)

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": api_key, "units": units}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(url, params=params)
            if response.status_code == 404:
                raise MCPError(f"City '{city}' not found", tool=TOOL_NAME)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP error while fetching weather: {str(e)}", tool=TOOL_NAME)

    return WeatherData(
        city=data["name"],
        country=data["sys"]["country"],
        temperature=data["main"]["temp"],
        feels_like=data["main"]["feels_like"],
        humidity=data["main"]["humidity"],
        wind_speed=data["wind"]["speed"],
        description=data["weather"][0]["description"],
        icon=data["weather"][0]["icon"],
        timestamp=datetime.utcfromtimestamp(data["dt"]),
    )