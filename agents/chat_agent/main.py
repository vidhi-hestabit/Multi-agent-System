from __future__ import annotations
import logging
import uvicorn
from groq import AsyncGroq
from agents.base import BaseAgent
from common.config import get_settings
from common.prompts.chat_prompts import CHAT_SYSTEM

logger = logging.getLogger(__name__)
settings = get_settings()
PORT = settings.chat_agent_port
HOST = settings.chat_agent_host


class ChatAgent(BaseAgent):
    @property
    def agent_card(self) -> dict:
        return {
            "name": "Chat Agent",
            "description": "Handles conversational queries, greetings, jokes, and general chat.",
            "url": f"http://{HOST}:{PORT}",
            "version": "1.0.0",
            "protocolVersion": "0.3.0",
            "requires": [],
            "any_of_requires": [],
            "produces": ["chat"],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "chat",
                    "name": "Conversational Chat",
                    "description": "Reply to greetings, jokes, general questions, and small talk.",
                    "tags": ["chat", "greeting", "conversation"],
                }
            ],
        }

    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        llm = AsyncGroq(api_key=settings.groq_api_key)
        messages = [{"role": "system", "content": CHAT_SYSTEM}]
        
        # Add history if available
        history = context.get("history")
        if history:
            messages.append({"role": "system", "content": f"Previous conversation history:\n{history}"})
            
        messages.append({"role": "user", "content": instruction})

        response = await llm.chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            max_tokens=150,
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        logger.info("ChatAgent: %r → %d chars", instruction[:50], len(reply))
        return {"chat": reply}


app = ChatAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)