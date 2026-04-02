from __future__ import annotations
from datetime import datetime
import httpx
from common.config import get_settings
from common.errors import MCPError
from common.models import NewsArticle
from mcp_server.app import mcp

TOOL_NAME = "fetch_news"
TOOL_DESCRIPTION = "Fetch the latest news articles for a given topic or query."
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query for news articles (e.g. 'artificial intelligence', 'climate change')",
        },
        "language": {
            "type": "string",
            "description": "Language code (e.g. 'en', 'fr'). Defaults to 'en'.",
            "default": "en",
        },
        "page_size": {
            "type": "integer",
            "description": "Number of articles to return (1-10). Defaults to 5.",
            "default": 5,
            "minimum": 1,
            "maximum": 10,
        },
    },
    "required": ["query"],
}


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(query: str, language: str = "en", page_size: int = 5) -> list[NewsArticle]:
    settings = get_settings()
    api_key = settings.news_api_key

    if not api_key or api_key == "your_newsapi_key_here":
        raise MCPError("NEWS_API_KEY is not configured in .env", tool=TOOL_NAME)

    url = "https://newsdata.io/api/1/news"
    # Sanitize query to prevent 422 Unprocessable Entity
    sanitized_query = query.split("\n")[0].strip()
    if len(sanitized_query) > 40:
        sanitized_query = sanitized_query[:40].strip()

    params = {
        "q": sanitized_query,
        "language": language,
        "size": page_size,
        "apikey": api_key,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, params=params)
            if response.status_code == 404:
                raise MCPError(f"Query '{query}' returned no results", tool=TOOL_NAME)
            response.raise_for_status()
            data = response.json()
        except httpx.ReadTimeout:
            raise MCPError("The NewsData API took too long to respond. Please try again later.", tool=TOOL_NAME)
        except httpx.ConnectError:
            raise MCPError("Could not connect to NewsData.io. Please check your internet connection.", tool=TOOL_NAME)
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP error while fetching news: {e.__class__.__name__} {str(e)}", tool=TOOL_NAME)

    if data.get("status") != "success":
        raise MCPError(
            f"NewsData.io error: {data.get('message', {}).get('message', 'Unknown error')}",
            tool=TOOL_NAME,
        )

    articles = []
    for article in data.get("results", [])[:page_size]:
        articles.append(
            NewsArticle(
                title=article.get("title", ""),
                description=article.get("description"),
                url=article.get("link", ""),
                source=article.get("source_id", ""),
                published_at=datetime.fromisoformat(
                    article.get("pubDate", "").replace(" ", "T")
                ) if article.get("pubDate") else None,
                content=(article.get("content") or "")[:500],
            )
        )

    return articles