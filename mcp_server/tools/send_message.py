from __future__ import annotations
from common.errors import MCPError
from mcp_server.tools import composio_tool

TOOL_NAME = "send_message"
TOOL_DESCRIPTION = (
    "Send a message or email via a Composio-connected app. "
    "Supports GMAIL, SLACK, TELEGRAM, DISCORD. "
    "The user must have authorised the app first via composio_connect."
)
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "app": {
            "type": "string",
            "description": "App to send through: GMAIL, SLACK, TELEGRAM, or DISCORD.",
        },
        "user_id": {
            "type": "string",
            "description": "Same user_id used when the app was connected via composio_connect.",
        },
        "to": {
            "type": "string",
            "description": (
                "Recipient/destination."
                "GMAIL: recipient email address."
                "SLACK: channel name like #general or a member ID."
                "TELEGRAM: numeric chat_id."
                "DISCORD: channel_id."
            ),
        },
        "subject": {
            "type": "string",
            "description": "Subject line. Required for GMAIL; ignored by other apps.",
            "default": "",
        },
        "body": {
            "type": "string",
            "description": "The message body or email content.",
        },
    },
    "required": ["app", "user_id", "to", "body"],
}

# Composio action name per app
APP_ACTION: dict[str, str] = {
    "GMAIL": "GMAIL_SEND_EMAIL",
    "SLACK": "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL",
    "TELEGRAM": "TELEGRAM_SEND_MESSAGE",
    "DISCORD": "DISCORD_SEND_MESSAGE",
}

async def handle( app: str, user_id: str, to: str, body: str, subject: str = "") -> dict:
    app_slug = app.upper()
    action = APP_ACTION.get(app_slug)
    if not action:
        raise MCPError(
            f"{app_slug} is not supported. Supported apps: {list(APP_ACTION.keys())}",
            tool=TOOL_NAME,
        )

    if app_slug == "GMAIL":
        params = {
            "recipient_email": to,
            "subject": subject or "Message from AI Agent",
            "body": body,
        }
    elif app_slug == "SLACK":
        params = { "channel": to, "text": body }
    elif app_slug == "TELEGRAM":
        params = { "chat_id": to, "text": body }

    elif app_slug == "DISCORD":
        params = { "channel_id": to, "content": body}

    else:
        raise MCPError(f"Unsupported app {app_slug}", tool=TOOL_NAME)

    result = await composio_tool.handle( action=action, user_id=user_id, params=params )

    if result.get("success"):
        return {
            "success": True,
            "app": app_slug,
            "to": to,
            "message": f"Message sent via {app_slug} to {to}.",
        }

    raise MCPError(f"Failed sending message via {app_slug}", tool=TOOL_NAME )