from common.a2a_types import AgentSkill

SKILLS = [
    AgentSkill(
        id="query_sql",
        name="Query SQL Database",
        description="Answer questions about music, artists, albums, sales and customers from the Chinook database using natural language.",
        input_modes=["text"],
        output_modes=["text", "data"],
        tags=["sql", "database", "chinook", "music"],
        examples=[
            "How many albums does AC/DC have?",
            "List the top 5 customers by total purchases",
            "What are the most popular genres?",
            "Show all tracks longer than 5 minutes",
        ],
    ),
]
