from __future__ import annotations
import logging
import httpx
import uvicorn
from groq import AsyncGroq
from agents.base import BaseAgent
from agents.llm_utils import ask_llm
from common.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
PORT = settings.news_agent_port
HOST = settings.news_agent_host
MCP = settings.mcp_server_url
GROQ_API_KEY = settings.groq_api_key
GROQ_MODEL = settings.groq_model

_TOPIC_SYSTEM = """Extract the best 2-4 word search query for a news API.
Expand acronyms. Remove words like "news", "latest", "tell me", "give me".
Return ONLY the search phrase, nothing else.
Examples:
  "give news about artificial intelligence" → artificial intelligence
  "latest AI news" → artificial intelligence
  "news about ChatGPT" → ChatGPT OpenAI
  "climate change news" → climate change
  "space exploration news" → space exploration NASA"""

_FALLBACK_SYSTEM = (
    "You are a news journalist. Write a factual, well-structured 3-paragraph news summary "
    "on the given topic based on your knowledge. Be current and accurate."
)


class NewsAgent(BaseAgent):

    @property
    def agent_card(self) -> dict:
        return {
            "name": "News Agent",
            "description": "Fetches and summarizes news. Uses MCP/NewsData.io if available, else LLM knowledge.",
            "url": f"http://{HOST}:{PORT}",
            "version": "1.0.0",
            "protocolVersion": "0.3.0",
            "requires": [],
            "produces": ["news_summary", "news_articles", "news_topic"],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "fetch_news",
                    "name": "Fetch News",
                    "description": "Get and summarize recent news articles.",
                    "tags": ["news"],
                }
            ],
        }

    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        topic = context.get("city_name") or (
            await ask_llm(_TOPIC_SYSTEM, instruction, max_tokens=30)
        ).strip().strip("\"'.")

        logger.info("NewsAgent task=%s topic=%r", task_id[:8], topic)

        # Try live fetch from MCP
        articles = await self._try_fetch(topic, instruction)

        if articles:
            logger.info("NewsAgent: %d articles fetched for %r", len(articles), topic)
            summary = await self._summarize_from_articles(
                topic=topic,
                articles=articles,
                weather_ctx=context.get("weather_data_text", ""),
            )
        else:
            logger.warning(
                "NewsAgent: MCP returned no articles for %r (task=%s) — using LLM fallback. "
                "Check NEWS_API_KEY in .env.local and restart MCP server.",
                topic,
                task_id[:8],
            )
            summary = await ask_llm(
                _FALLBACK_SYSTEM,
                f"Write a news summary about: {topic}",
                max_tokens=600,
                temperature=0.4,
            )
            summary = (
                "*(Generated from AI knowledge — live articles unavailable. "
                "Check NEWS_API_KEY in .env.local.)*\n\n" + summary
            )

        return {"news_summary": summary,"news_articles": articles,"news_topic": topic}

    async def _try_fetch(self, topic: str, instruction: str) -> list[dict]:
        for query in dict.fromkeys([topic, instruction[:80]]):
            if not query.strip():
                continue
            articles = await self._fetch_one(query)
            if articles:
                return articles
        return []

    async def _fetch_one(self, query: str) -> list[dict]:
        logger.info("NewsAgent: fetch_news query=%r", query)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{MCP}/tools/call",
                    json={ "tool": "fetch_news", "arguments": {"query": query,"language": "en","page_size": 5}})
            body = resp.json()
            if resp.status_code != 200 or body.get("error"):
                err = body.get("error") or body.get("detail", {})
                logger.warning("NewsAgent: MCP error for %r: %s", query, err)
                return []

            raw = body.get("result", [])
            articles: list[dict] = []

            for a in raw if isinstance(raw, list) else []:
                if hasattr(a, "model_dump"):
                    a = a.model_dump()

                if isinstance(a, dict) and a.get("title"):
                    articles.append(
                        {
                            "title": a.get("title", ""),
                            "source": a.get("source", ""),
                            "description": a.get("description", "") or "",
                            "url": a.get("url", ""),
                        }
                    )
            return articles
        except Exception as exc:
            logger.warning("NewsAgent: _fetch_one exception for %r: %s", query, exc)
            return []

    async def _summarize_from_articles( self, topic: str, articles: list[dict], weather_ctx: str = "") -> str:
        llm = AsyncGroq(api_key=GROQ_API_KEY)
        block = "\n\n".join(
            f"Title: {a['title']}\nSource: {a['source']}\n{a['description']}"
            for a in articles
        )
        extra = f"Weather context: {weather_ctx}\n\n" if weather_ctx else ""
        prompt = ( f"Topic: {topic}\n" f"{extra}" f"Articles:\n{block}\n\n" "Write a clear 3-paragraph summary.")
        try:
            r = await llm.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are a concise news summarizer."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=0.3,
            )
            return r.choices[0].message.content
        except Exception as exc:
            logger.error("NewsAgent LLM failed: %s", exc)
            return "\n\n".join(
                f"**{a['title']}**\n{a['description']}" for a in articles
            )

    def build_app(self):
        app = super().build_app()

        @app.get("/debug")
        async def debug():
            key = str(getattr(settings, "news_api_key", "") or "")
            result = {
                "mcp_url": MCP,
                "news_api_key_set": bool(key and key != "your_newsdata_io_key_here"),
                "news_api_key_preview": (key[:8] + "…") if key else "NOT SET",
            }

            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.post(
                        f"{MCP}/tools/call",
                        json={ "tool": "fetch_news", "arguments": {"query": "technology", "page_size": 2}})
                body = r.json()
                raw = body.get("result", [])
                result["fetch_news_test"] = {
                    "http_status": r.status_code,
                    "article_count": len(raw) if isinstance(raw, list) else 0,
                    "first_title": raw[0].get("title", "") if isinstance(raw, list) and raw else "",
                    "mcp_error": str(body.get("error", "") or body.get("detail", "")),
                    "raw_response_preview": str(body)[:400],
                }
            except Exception as e:
                result["fetch_news_test"] = {"error": str(e)}
            return result
        return app

app = NewsAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)