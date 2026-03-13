from __future__ import annotations
import asyncio
from functools import partial
from composio import ComposioToolSet
from common.config import get_settings
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

def _send_sync(api_key: str,app_slug: str,user_id: str,to: str,body: str,subject: str) -> dict:
    action_name = APP_ACTION.get(app_slug)
    if not action_name:
        raise MCPError(
            f"Sending via {app_slug} is not supported yet. "
            f"Supported: {list[str](APP_ACTION.keys())}",
            tool=TOOL_NAME,
        )

    toolset = ComposioToolSet(api_key=api_key, entity_id=user_id)

    if app_slug == "GMAIL":
        params = {
            "recipient_email": to,
            "subject": subject or "Message from your AI Agent",
            "body": body
        }
    elif app_slug == "SLACK":
        params = {"channel": to, "text": body}
    elif app_slug == "TELEGRAM":
        params = {"chat_id": to, "text": body}
    elif app_slug == "DISCORD":
        params = {"channel_id": to, "content": body}
    else:
        params = {"to": to, "body": body}

    response = toolset.execute_action(
        action=action_name,
        params=params,
        entity_id=user_id
    )

    if response.get("successfull") or response.get("success"):
        return {
            "success": True,
            "app": app_slug,
            "to": to,
            "message": f"Message sent via {app_slug} to {to}.",
        }

    error_detail = response.get("error") or str(response)
    raise MCPError(f"Composio action {action_name} failed: {error_detail}", tool=TOOL_NAME)


async def handle(app: str,user_id: str,to: str,body: str,subject: str = "") -> dict:
    settings = get_settings()
    if not settings.composio_api_key:
        raise MCPError("COMPOSIO_API_KEY is not set in .env.", tool=TOOL_NAME)

    app_slug = app.upper()
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None,
            partial(_send_sync, settings.composio_api_key, app_slug, user_id, to, body, subject),
        )
    except MCPError:
        raise
    except Exception as e:
        raise MCPError(f"Failed to send via {app_slug}: {e}", tool=TOOL_NAME)