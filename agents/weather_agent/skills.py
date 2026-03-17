from common.a2a_types import AgentSkill

SKILLS = [
    AgentSkill(
        id="fetch_weather",
        name="Fetch Weather",
        description="Get current weather conditions and forecast for any city.",
        input_modes=["text"],
        output_modes=["text", "data"],
        tags=["weather", "forecast", "temperature"],
        examples=[
            "What is the weather in London?",
            "Weather forecast for Tokyo",
            "Is it raining in New York?",
            "Temperature in Paris today",
        ],
    ),
]
