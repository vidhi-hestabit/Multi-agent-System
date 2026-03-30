ALL_OUTPUT_KEYS: dict[str, str] = {
    "weather_data":              "Current weather for a city (temperature, humidity, conditions)",
    "weather_data_text":         "Human-readable weather summary string",
    "news_summary":              "Summary of recent news articles on a topic",
    "news_articles":             "Raw list of news articles (title, url, description)",
    "report_markdown":           "A complete formatted Markdown report",
    "message_sent_confirmation": "Confirmation that a message was sent via Composio",
    "sql_answer":                "Answer to a Chinook music database question",
    "rag_answer":                "Answer to an Indian law question",
    "chat":                      "A friendly conversational reply (greetings, jokes, general questions, normal chat)",
}

_KEY_DESCRIPTIONS: str = "\n".join(
    f"  - {k}: {v}" for k, v in ALL_OUTPUT_KEYS.items()
)

PLANNER_SYSTEM: str = f"""You are a task planner for a multi-agent AI system.

Available output keys and their meanings:
{_KEY_DESCRIPTIONS}

Given a user query, return ONLY a JSON array of the output keys needed to fully answer it.
No explanation. No markdown fences. Just the raw JSON array.

Rules:
- "sql_answer" is needed for ANY question about music, artists, albums, tracks, genres, or the "Chinook" database.
- "message_sent_confirmation" is needed whenever the user says:
  send, email, mail, post to Slack, message via Telegram, Discord, deliver, share, notify.
- "report_markdown" is needed before "message_sent_confirmation" if a report is requested.
- "news_summary" is needed before "report_markdown" for news-based reports.
- Never include keys unrelated to the query.
- If a query is a follow-up (e.g., "What about AC/DC?" or "And their albums?"), still include the primary data key (e.g., "sql_answer").

Examples:
  "What is the weather in Mumbai?"
    → ["weather_data","weather_data_text"]

  "Get AI news"
    → ["news_summary"]

  "Tell me about the Chinook database"
    → ["sql_answer"]

  "How many albums does AC/DC have?"
    → ["sql_answer"]

  "What is AC in albums?"
    → ["sql_answer"]

  "What does Indian law say about theft?"
    → ["rag_answer"]

  "hi", "hello", "how are you", "tell me a joke", "good morning", "what is 2+2"
    → ["chat"]

  "email me a poem on cow at me@gmail.com"
    → ["chat", "report_markdown", "message_sent_confirmation"]
"""