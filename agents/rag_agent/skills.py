from common.a2a_types import AgentSkill

SKILLS = [
    AgentSkill(
        id="query_rag",
        name="Query Indian Law",
        description="Answer questions about Indian law using a semantic search over the Indian Law dataset.",
        input_modes=["text"],
        output_modes=["text", "data"],
        tags=["law", "india", "legal", "rag"],
        examples=[
            "What is the punishment for theft under IPC?",
            "Explain the right to free speech in India",
            "What does the Indian constitution say about equality?",
            "Laws related to cybercrime in India",
        ],
    ),
]
