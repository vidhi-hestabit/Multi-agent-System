# common/prompts/composio_prompts.py
# All LLM system prompts used by the Composio Agent.

DELIVERY_SYSTEM: str = """Extract delivery details from the user's message.
Return JSON with exactly these keys:
  "app":       one of GMAIL, SLACK, TELEGRAM, DISCORD
  "recipient": email, #channel, chat_id, or "" if not mentioned

Rules:
- "email", "gmail", "mail" → GMAIL
- "slack"                  → SLACK
- "telegram"               → TELEGRAM
- "discord"                → DISCORD
- Nothing mentioned        → GMAIL

Examples:
  "send to user@x.com"          → {"app":"GMAIL","recipient":"user@x.com"}
  "email report to u@gmail.com" → {"app":"GMAIL","recipient":"u@gmail.com"}
  "post to #general on slack"   → {"app":"SLACK","recipient":"#general"}
  "send via gmail"              → {"app":"GMAIL","recipient":""}"
"""

SUBJECT_WRITER_SYSTEM: str = "You write short email subject lines."