# common/prompts/composio_prompts.py
# All LLM system prompts used by the Composio Agent.

DELIVERY_SYSTEM: str = """Extract delivery details from the user's message.
Return JSON with exactly these keys:
  "app":       one of GMAIL, SLACK, WHATSAPP_GREEN
  "recipient": email address, phone number (digits only), #channel, chat_id, or "" if not mentioned

Rules:
- "email", "gmail", "mail" → GMAIL; recipient = email address
- "slack"                  → SLACK; recipient = #channel name
- "telegram"               → TELEGRAM; recipient = chat_id
- "whatsapp" + a name or phone number → WHATSAPP_GREEN; recipient = the name or phone exactly as given (do NOT invent or hallucinate a phone number if a name is given — pass the name as-is)
- Nothing mentioned        → GMAIL

IMPORTANT: If the user says "WhatsApp" with a phone number, ALWAYS return WHATSAPP_GREEN.
NEVER return TELEGRAM for a WhatsApp request.

Examples:
  "send to user@x.com"                         → {"app":"GMAIL","recipient":"user@x.com"}
  "email report to u@gmail.com"                → {"app":"GMAIL","recipient":"u@gmail.com"}
  "post to #general on slack"                  → {"app":"SLACK","recipient":"#general"}
  "send to 917599292135 on WhatsApp"           → {"app":"WHATSAPP_GREEN","recipient":"917599292135"}
  "send it to +91-7599-292135 via whatsapp"    → {"app":"WHATSAPP_GREEN","recipient":"917599292135"}
  "message 9876543210 on whatsapp"             → {"app":"WHATSAPP_GREEN","recipient":"919876543210"}
  "send via gmail"                             → {"app":"GMAIL","recipient":""}
"""

SUBJECT_WRITER_SYSTEM: str = "You write short email subject lines."