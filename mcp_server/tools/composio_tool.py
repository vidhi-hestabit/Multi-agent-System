from __future__ import annotations
import asyncio
from functools import partial
from composio import ComposioToolSet
from common.config import get_settings
from common.errors import MCPError

TOOL_NAME = "composio_tool"
TOOL_DESCRIPTION = (
    "Universal Composio tool. Does two things based on 'action' parameter:\n"
    "  connect  — Check if user has connected an app. Returns oauth_url if not.\n"
    "  execute  — Execute any action on a connected app (send email, post to Slack, etc.)"
)
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "Either 'connect' to check/initiate OAuth, or the Composio action name to execute (e.g. GMAIL_SEND_EMAIL, SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL, TELEGRAM_SEND_MESSAGE).",
        },
        "app": {
            "type": "string",
            "description": "App name: GMAIL, SLACK, TELEGRAM, DISCORD, NOTION, GITHUB, etc. Required for 'connect'.",
            "default": "",
        },
        "user_id": {
            "type": "string",
            "description": "Stable identifier for the user (e.g. email or session ID). Used by Composio to store their connected accounts.",
        },
        "params": {
            "type": "object",
            "description": "Parameters to pass when action is an execute call. E.g. for GMAIL_SEND_EMAIL: {recipient_email, subject, body}.",
            "default": {},
        },
    },
    "required": ["action", "user_id"],
}

APP_ALIASES: dict[str, str] = {
    "gmail": "GMAIL", "email": "GMAIL",
    "slack": "SLACK",
    "telegram": "TELEGRAM",
    "discord": "DISCORD",
    "notion": "NOTION",
    "github": "GITHUB",
    "whatsapp": "WHATSAPP",
    "sheets": "GOOGLESHEETS", "google sheets": "GOOGLESHEETS",
    "drive": "GOOGLEDRIVE", "google drive": "GOOGLEDRIVE",
}


def _connect_sync(api_key: str, app_slug: str, user_id: str) -> dict:
    toolset = ComposioToolSet(api_key=api_key, entity_id=user_id)
    entity  = toolset.get_entity(id=user_id)
    try:
        conn = entity.get_connection(app=app_slug)
        if conn and getattr(conn, "status", "") == "ACTIVE":
            return {"connected": True, "app": app_slug, "user_id": user_id}
    except Exception:
        pass
    req = entity.initiate_connection(app_name=app_slug)
    return {
        "connected": False,
        "app": app_slug,
        "user_id": user_id,
        "oauth_url": req.redirectUrl,
        "message": f"Open this URL to connect {app_slug}:\n{req.redirectUrl}\n\nThen type 'connected' to continue.",
    }


def _execute_sync(api_key: str, action: str, user_id: str, params: dict) -> dict:
    toolset = ComposioToolSet(api_key=api_key, entity_id=user_id)
    response = toolset.execute_action(
        action=action,
        params=params,
        entity_id=user_id,
    )
    if response.get("successfull") or response.get("success"):
        return {"success": True, "action": action, "result": response}
    raise MCPError(f"Action {action} failed: {response.get('error', response)}", tool=TOOL_NAME)


async def handle(action: str, user_id: str, app: str = "", params: dict | None = None) -> dict:
    settings = get_settings()
    if not settings.composio_api_key:
        raise MCPError("COMPOSIO_API_KEY not set in .env. Get it at https://app.composio.dev", tool=TOOL_NAME)

    loop = asyncio.get_event_loop()

    try:
        if action == "connect":
            app_slug = APP_ALIASES.get(app.lower(), app.upper())
            return await loop.run_in_executor(
                None, partial(_connect_sync, settings.composio_api_key, app_slug, user_id)
            )
        else:
            # action is a Composio action name like GMAIL_SEND_EMAIL
            return await loop.run_in_executor(
                None, partial(_execute_sync, settings.composio_api_key, action, user_id, params or {})
            )
    except MCPError:
        raise
    except Exception as e:
        raise MCPError(str(e), tool=TOOL_NAME)