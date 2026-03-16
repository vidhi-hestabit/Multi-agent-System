from __future__ import annotations
import re
from groq import AsyncGroq
from common.config import get_settings
from common.logging import get_logger, setup_logging
from agents.base_agent.base_handler import BaseHandler, AgentState
from agents.base_agent.base_mcp_client import BaseMCPClient
from agents.base_agent.base_a2a_client import BaseA2AClient

setup_logging()
logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a News Research Agent. Your job is to:
1. Understand what news topic the user is asking about
2. Use the provided news data to give a clear, concise summary
3. Highlight the most important and relevant articles
4. Present findings in a structured, readable format

Always be factual and cite the sources of news articles.
If no real news data is available, clearly indicate that placeholder data is being shown.
"""

# Expand short/generic queries for better NewsData.io results
QUERY_EXPANSIONS = {
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "ev": "electric vehicles",
    "us": "united states",
}


class NewsAgentHandler(BaseHandler):

    def __init__(self):
        self.settings = get_settings()
        self.mcp = BaseMCPClient()
        self.llm = AsyncGroq(api_key=self.settings.groq_api_key)
        super().__init__()

    def _build_graph(self):
        self.add_node("fetch_news", self._fetch_news)
        self.add_node("enrich_with_weather", self._enrich_with_weather)
        self.add_node("summarize", self._summarize)

        self.set_entry("fetch_news")

        self.add_conditional_edges(
            "fetch_news",
            self._needs_weather,
            {"yes": "enrich_with_weather", "no": "summarize"},
        )
        self.add_edge("enrich_with_weather", "summarize")
        self.finish("summarize")

    def _needs_weather(self, state: AgentState) -> str:
        msg = state.get("message", "").lower()
        weather_words = {"weather", "temperature", "forecast", "rain", "sunny", "wind"}
        return "yes" if any(w in msg for w in weather_words) else "no"

    async def _fetch_news(self, state: AgentState) -> AgentState:
        query = state["message"]
        topic = self._extract_topic(query)
        # Expand single-word generic queries
        topic = QUERY_EXPANSIONS.get(topic.lower().strip(), topic)
        state.setdefault("metadata", {})["topic"] = topic

        try:
            news_data = await self.mcp.call_tool(
                "fetch_news",
                {"query": topic, "page_size": 5},
            )
        except Exception as exc:
            logger.error("news_fetch_failed", error=str(exc))
            news_data = {"result": [], "is_mock": True}

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_articles = []
        for a in news_data.get("result", []):
            url = a.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_articles.append(a)

        state["metadata"]["articles"] = unique_articles
        state["metadata"]["is_mock"] = news_data.get("is_mock", False)
        state["metadata"]["total"] = len(unique_articles)
        return state

    async def _enrich_with_weather(self, state: AgentState) -> AgentState:
        query = state["message"]
        weather_url = self.settings.weather_agent_url

        try:
            client = BaseA2AClient(weather_url, timeout=30)
            response = await client.send_task(text=query, session_id=state.get("session_id"), metadata=state.get("metadata", {}))
            weather_text = ""
            if response.status.message:
                weather_text = response.status.message.text()
            state["metadata"]["weather_context"] = weather_text
            logger.info("news_agent_fetched_weather", chars=len(weather_text))
        except Exception as exc:
            logger.warning("news_weather_enrich_failed", error=str(exc))
            state["metadata"]["weather_context"] = ""

        return state

    async def _summarize(self, state: AgentState) -> AgentState:
        query = state["message"]
        meta = state.get("metadata", {})
        articles = meta.get("articles", [])
        is_mock = meta.get("is_mock", False)

        articles_text = "\n\n".join(
            f"Title: {a['title']}\n"
            f"Source: {a.get('source', 'Unknown')}\n"
            f"Published: {a.get('published_at', 'N/A')}\n"
            f"Description: {a.get('description', 'N/A')}\n"
            f"URL: {a.get('url', '')}"
            for a in articles
        )

        if is_mock:
            articles_text = (
                "[Note: Using placeholder data. Set NEWS_API_KEY for real articles.]\n\n"
                + articles_text
            )

        weather_ctx = meta.get("weather_context", "")
        extra = f"\n\nRelated weather context:\n{weather_ctx}" if weather_ctx else ""

        user_message = (
            f"User query: {query}\n\n"
            f"News articles for topic '{meta.get('topic', query)}':\n\n"
            f"{articles_text}{extra}\n\n"
            "Please summarize these news articles for the user."
        )

        try:
            chat_response = await self.llm.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1024,
                temperature=0.3,
            )
            summary = chat_response.choices[0].message.content
        except Exception as exc:
            logger.error("news_llm_failed", error=str(exc))
            summary = articles_text or "No articles found."

        state["result"] = summary
        state["result_data"] = {
            "topic": meta.get("topic"),
            "articles": articles,
            "total": meta.get("total", len(articles)),
            "is_mock": is_mock,
        }
        return state

    def _extract_topic(self, query: str) -> str:
        query = re.sub(
            r"(?i)^(send|generate|create|write|make|prepare)\s+(a\s+|an\s+)?report\s+(about|on|for|regarding)?\s*",
            "", query.strip(),
        )
        query = re.sub(
            r"(?i)\s+(via|through|using|over|with)\s+(gmail|email|slack|telegram|discord)\s*$",
            "", query.strip(),
        )
        patterns = [
            r"(?:get\s+me|tell\s+me|show\s+me|give\s+me)\s+(?:the\s+)?(?:latest\s+|recent\s+|current\s+)?(?:news\s+(?:about|on)\s+)?(.+?)(?:\s+news|\s+articles?|$)",
            r"(?:get|fetch|find|show)\s+(?:the\s+)?(?:latest\s+|recent\s+)?(?:news\s+(?:about|on)\s+)?(.+?)(?:\s+news|\s+articles?|$)",
            r"(?:what(?:'s| is| are)?\s+)?(?:happening\s+with|the\s+latest\s+(?:on|about|with)|going\s+on\s+with)\s+(.+?)(?:\?|\s+news|\s+articles?|$)",
            r"(?:latest|recent|current)\s+(.+?)(?:\s+news|\s+articles?|$)",
            r"news\s+(?:about|on|for)\s+(.+?)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, query.lower())
            if match:
                return match.group(1).strip().rstrip("?").strip()
        return query[:80].strip()
