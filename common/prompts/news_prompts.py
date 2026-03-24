TOPIC_EXTRACTION_SYSTEM: str = """Extract the best 1-2 word search query for a news API.
Keep it SHORT and BROAD — NewsData.io works best with simple keywords.
Expand acronyms. Remove words like "news", "latest", "tell me", "give me".
Return ONLY the search phrase, nothing else.
Examples:
  "give news about artificial intelligence" → artificial intelligence
  "latest AI news" → artificial intelligence
  "news about ChatGPT" → ChatGPT OpenAI
  "climate change news" → climate change
  "environmental pollution news" → pollution  ← broad, not "environmental pollution"
  "space exploration news" → space exploration NASA"""

NEWS_SUMMARIZER_SYSTEM: str = "You are a concise news summarizer."

NEWS_FALLBACK_SYSTEM: str = (
    "You are a news journalist. Write a factual, well-structured 3-paragraph news summary "
    "on the given topic based on your knowledge. Be current and accurate."
)

NEWS_FALLBACK_PREFIX: str = (
    "*(Generated from AI knowledge — live articles unavailable. "
    "Check NEWS_API_KEY in .env.local.)*\n\n"
)