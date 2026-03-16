from common.a2a_types import AgentSkill

SKILLS = [
    AgentSkill(
        id="fetch_news",
        name="Fetch News",
        description="Retrieve and summarize the latest news articles on a given topic.",
        input_modes=["text"],
        output_modes=["text", "data"],
        tags=["news", "information", "summarization"],
        examples=[
            "Get me the latest AI news",
            "What is happening with climate change?",
            "News about SpaceX launches",
        ],
    ),
]