from __future__ import annotations

from common.errors import MCPError
from mcp_server.app import mcp
from mcp_server.tools.composio_tool import handle as composio_handle

TOOL_NAME = "send_message"
TOOL_DESCRIPTION = (
    "Send a message or email through a Composio-connected app. "
    "Supported apps: GMAIL, SLACK, TELEGRAM, DISCORD."
)
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "app": {
            "type": "string",
            "description": "App to send through: GMAIL, SLACK, TELEGRAM, DISCORD.",
        },
        "user_id": {
            "type": "string",
            "description": "Same user_id used during the Composio connect flow.",
        },
        "to": {
            "type": "string",
            "description": (
                "Destination identifier. "
                "GMAIL: recipient email. "
                "SLACK: channel like #general or channel/user id. "
                "TELEGRAM: chat_id. "
                "DISCORD: channel_id."
            ),
        },
        "body": {
            "type": "string",
            "description": "Message body/content.",
        },
        "subject": {
            "type": "string",
            "description": "Email subject for GMAIL only.",
            "default": "",
        },
    },
    "required": ["app", "user_id", "to", "body"],
}

APP_ACTION: dict[str, str] = {
    "GMAIL": "GMAIL_SEND_EMAIL",
    "SLACK": "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL",
    "TELEGRAM": "TELEGRAM_SEND_MESSAGE",
    "DISCORD": "DISCORD_SEND_MESSAGE",
}


def _normalize_app(app: str) -> str:
    if not app:
        raise MCPError("App is required.", tool=TOOL_NAME)
    return app.strip().upper()


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(
    app: str,
    user_id: str,
    to: str,
    body: str,
    subject: str = "",
) -> dict:
    app_slug = _normalize_app(app)
    action = APP_ACTION.get(app_slug)

    if not action:
        raise MCPError(
            f"{app_slug} is not supported. Supported apps: {list(APP_ACTION.keys())}",
            tool=TOOL_NAME,
        )
    if not to.strip():
        raise MCPError("Recipient/destination 'to' is required.", tool=TOOL_NAME)
    if not body.strip():
        raise MCPError("Message body is required.", tool=TOOL_NAME)

    if app_slug == "GMAIL":
        params = {"recipient_email": to, "subject": subject or "Message from AI Agent", "body": body}
    elif app_slug == "SLACK":
        params = {"channel": to, "text": body}
    elif app_slug == "TELEGRAM":
        params = {"chat_id": to, "text": body}
    else:  # DISCORD
        params = {"channel_id": to, "content": body}

    result = await composio_handle(action=action, user_id=user_id, params=params)

    if result.get("success"):
        return {
            "success": True,
            "app": app_slug,
            "to": to,
            "message": f"Message sent via {app_slug} to {to}.",
            "result": result.get("result"),
        }

    raise MCPError(f"Failed sending message via {app_slug}.", tool=TOOL_NAME)