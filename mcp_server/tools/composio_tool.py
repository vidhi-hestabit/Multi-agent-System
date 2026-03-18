from __future__ import annotations

import asyncio
from functools import partial
from composio import ComposioToolSet

from common.config import get_settings
from common.errors import MCPError

TOOL_NAME = "composio_tool"
TOOL_DESCRIPTION = (
    "Universal Composio tool. "
    "Use action='connect' to initiate/check OAuth for an app, "
    "or pass a Composio action name like GMAIL_SEND_EMAIL to execute it."
)

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": (
                "Either 'connect' to start/check OAuth, "
                "or a Composio action name like GMAIL_SEND_EMAIL."
            ),
        },
        "app": {
            "type": "string",
            "description": (
                "App name for connect flow, such as GMAIL, SLACK, TELEGRAM, DISCORD."
            ),
            "default": "",
        },
        "user_id": {
            "type": "string",
            "description": "Stable user identifier used by Composio.",
        },
        "params": {
            "type": "object",
            "description": "Parameters for execute actions.",
            "default": {},
        },
    },
    "required": ["action", "user_id"],
}

APP_ALIASES: dict[str, str] = {
    "gmail": "GMAIL",
    "email": "GMAIL",
    "slack": "SLACK",
    "telegram": "TELEGRAM",
    "discord": "DISCORD",
    "notion": "NOTION",
    "github": "GITHUB",
    "whatsapp": "WHATSAPP",
    "sheets": "GOOGLESHEETS",
    "google sheets": "GOOGLESHEETS",
    "drive": "GOOGLEDRIVE",
    "google drive": "GOOGLEDRIVE",
}


def _normalize_app(app: str) -> str:
    if not app:
        raise MCPError("App is required for connect action.", tool=TOOL_NAME)
    return APP_ALIASES.get(app.strip().lower(), app.strip().upper())


def _extract_oauth_url(req: object) -> str | None:
    # Composio SDK response shape can vary
    return (
        getattr(req, "redirectUrl", None)
        or getattr(req, "redirect_url", None)
        or getattr(req, "url", None)
        or (req.get("redirectUrl") if isinstance(req, dict) else None)
        or (req.get("redirect_url") if isinstance(req, dict) else None)
        or (req.get("url") if isinstance(req, dict) else None)
    )


def _connect_sync(api_key: str, app: str, user_id: str) -> dict:
    app_slug = _normalize_app(app)

    toolset = ComposioToolSet(api_key=api_key, entity_id=user_id)
    entity = toolset.get_entity(id=user_id)

    try:
        conn = entity.get_connection(app=app_slug)
        if conn and getattr(conn, "status", "") == "ACTIVE":
            return {
                "connected": True,
                "app": app_slug,
                "user_id": user_id,
                "message": f"{app_slug} is already connected.",
            }
    except Exception:
        # If connection lookup fails, still try initiating connection
        pass

    try:
        req = entity.initiate_connection(app_name=app_slug)
    except Exception as exc:
        raise MCPError(
            f"Failed to initiate connection for {app_slug}: {exc}",
            tool=TOOL_NAME,
        ) from exc

    oauth_url = _extract_oauth_url(req)
    if not oauth_url:
        raise MCPError(
            f"Could not get OAuth URL for {app_slug}. "
            f"Composio initiate_connection returned no redirect URL.",
            tool=TOOL_NAME,
        )

    return {
        "connected": False,
        "app": app_slug,
        "user_id": user_id,
        "oauth_url": oauth_url,
        "message": (
            f"Open this URL to connect {app_slug}:\n{oauth_url}\n\n"
            "After authorising, type 'connected' to continue."
        ),
    }


def _execute_sync(api_key: str, action: str, user_id: str, params: dict) -> dict:
    toolset = ComposioToolSet(api_key=api_key, entity_id=user_id)

    try:
        response = toolset.execute_action(
            action=action,
            params=params,
            entity_id=user_id,
        )
    except Exception as exc:
        raise MCPError(
            f"Execution failed for action {action}: {exc}",
            tool=TOOL_NAME,
        ) from exc

    if not isinstance(response, dict):
        return {
            "success": True,
            "action": action,
            "result": response,
        }

    if response.get("success") or response.get("successful") or response.get("successfull"):
        return {
            "success": True,
            "action": action,
            "result": response,
        }

    raise MCPError(
        f"Action {action} failed: {response.get('error', response)}",
        tool=TOOL_NAME,
    )


async def handle(
    action: str,
    user_id: str,
    app: str = "",
    params: dict | None = None,
) -> dict:
    settings = get_settings()

    if not settings.composio_api_key:
        raise MCPError(
            "COMPOSIO_API_KEY is not set in environment.",
            tool=TOOL_NAME,
        )

    loop = asyncio.get_running_loop()

    try:
        if action.strip().lower() == "connect":
            return await loop.run_in_executor(
                None,
                partial(_connect_sync, settings.composio_api_key, app, user_id),
            )

        return await loop.run_in_executor(
            None,
            partial(
                _execute_sync,
                settings.composio_api_key,
                action,
                user_id,
                params or {},
            ),
        )
    except MCPError:
        raise
    except Exception as exc:
        raise MCPError(str(exc), tool=TOOL_NAME) from exc