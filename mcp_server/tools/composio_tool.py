from __future__ import annotations
import asyncio
from functools import partial
from composio import ComposioToolSet
from common.config import get_settings
from common.errors import MCPError

TOOL_NAME = "composio_connect"
TOOL_DESCRIPTION = (
    "Check whether a user has connected an app (e.g. GMAIL, SLACK, TELEGRAM, DISCORD) "
    "via Composio OAuth. "
    "Returns connected=true when the account is ready. "
    "Returns connected=false plus an oauth_url the user must open to authorise."
)
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "app": {
            "type": "string",
            "description": (
                "Composio app identifier in UPPERCASE: "
                "GMAIL, SLACK, TELEGRAM, DISCORD, NOTION, GITHUB, "
                "WHATSAPP, TWITTER, LINKEDIN, GOOGLESHEETS, GOOGLEDRIVE."
            ),
        },
        "user_id": {
            "type": "string",
            "description": (
                "A stable identifier for this end-user, e.g. their email address "
                "or a session UUID. Composio uses it to store their connected accounts."
            ),
        },
        "redirect_url": {
            "type": "string",
            "description": "URL to redirect to after successful OAuth. Optional.",
            "default": "",
        },
    },
    "required": ["app", "user_id"],
}

# Friendly aliases so users can type 'gmail' instead of 'GMAIL'
APP_ALIASES: dict[str, str] = {
    "gmail": "GMAIL",
    "email": "GMAIL",
    "slack": "SLACK",
    "telegram": "TELEGRAM",
    "discord": "DISCORD",
    "notion": "NOTION",
    "github": "GITHUB",
    "whatsapp": "WHATSAPP",
    "twitter": "TWITTER",
    "x": "TWITTER",
    "linkedin": "LINKEDIN",
    "sheets": "GOOGLESHEETS",
    "google sheets": "GOOGLESHEETS",
    "drive": "GOOGLEDRIVE",
    "google drive": "GOOGLEDRIVE",
}

# Pure sync worker — called via run_in_executor, never directly from async code

def _check_or_initiate_sync(
    api_key: str,
    app_slug: str,
    user_id: str,
    redirect_url: str,
) -> dict:
    toolset = ComposioToolSet(api_key=api_key, entity_id=user_id)
    entity = toolset.get_entity(id=user_id)

    # Try to find an existing active connection
    try:
        connection = entity.get_connection(app=app_slug)
        if connection and getattr(connection, "status", "") == "ACTIVE":
            return {
                "connected": True,
                "app": app_slug,
                "user_id": user_id,
                "connection_id": getattr(connection, "id", ""),
                "message": f"{app_slug} is already connected and ready to use.",
            }
    except Exception:
        pass  
    
    # Start OAuth flow
    kwargs: dict = {"app_name": app_slug}
    if redirect_url:
        kwargs["redirect_url"] = redirect_url

    req = entity.initiate_connection(**kwargs)

    return {
        "connected": False,
        "app": app_slug,
        "user_id": user_id,
        "oauth_url": req.redirectUrl,
        "message": (
            f"Open this URL to connect your {app_slug} account:\n"
            f"{req.redirectUrl}\n\n"
            "After authorising, type 'connected' to continue."
        ),
    }


# Async entry point called by the MCP server

async def handle(app: str, user_id: str, redirect_url: str = "") -> dict:
    settings = get_settings()
    if not settings.composio_api_key:
        raise MCPError(
            "COMPOSIO_API_KEY is not set in .env. "
            "Get your free key at https://app.composio.dev",
            tool=TOOL_NAME,
        )

    app_slug = APP_ALIASES.get(app.lower(), app.upper())
    loop = asyncio.get_event_loop()

    try:
        return await loop.run_in_executor(
            None,
            partial(
                _check_or_initiate_sync,
                settings.composio_api_key,
                app_slug,
                user_id,
                redirect_url,
            ),
        )
    except MCPError:
        raise
    except Exception as e:
        raise MCPError(
            f"Composio error for {app_slug}: {e}",
            tool=TOOL_NAME,
        )
