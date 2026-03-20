from __future__ import annotations
import asyncio
from functools import partial
from composio import Composio
from common.config import get_settings
from common.errors import MCPError
from mcp_server.app import mcp

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
            "description": "App name for connect flow, such as GMAIL, SLACK, TELEGRAM, DISCORD.",
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

# Maps friendly names → Composio toolkit slugs
APP_ALIASES: dict[str, str] = {
    "gmail": "gmail",
    "email": "gmail",
    "slack": "slack",
    "telegram": "telegram",
    "discord": "discord",
    "notion": "notion",
    "github": "github",
    "whatsapp": "whatsapp",
    "sheets": "googlesheets",
    "google sheets": "googlesheets",
    "drive": "googledrive",
    "google drive": "googledrive",
}


def _normalize_app(app: str) -> str:
    if not app:
        raise MCPError("App is required for connect action.", tool=TOOL_NAME)
    return APP_ALIASES.get(app.strip().lower(), app.strip().lower())


def _get_auth_config_id(composio: Composio, toolkit_slug: str) -> str:
    """Auto-resolve auth_config_id for a toolkit from the Composio dashboard."""
    try:
        configs = composio.auth_configs.list(toolkit_slug=toolkit_slug)
        items = getattr(configs, "items", None) or (configs if isinstance(configs, list) else [])
        for cfg in items:
            cfg_id = getattr(cfg, "id", None) or (cfg.get("id") if isinstance(cfg, dict) else None)
            if cfg_id:
                return cfg_id
    except Exception as exc:
        raise MCPError(
            f"Could not fetch auth configs for {toolkit_slug}: {exc}",
            tool=TOOL_NAME,
        ) from exc

    raise MCPError(
        f"No auth config found for '{toolkit_slug}'. "
        f"Please set one up at https://app.composio.dev/auth-configs",
        tool=TOOL_NAME,
    )


def _extract_redirect_url(obj: object) -> str | None:
    return (
        getattr(obj, "redirect_url", None)
        or getattr(obj, "redirectUrl", None)
        or getattr(obj, "url", None)
        or (obj.get("redirect_url") if isinstance(obj, dict) else None)
        or (obj.get("redirectUrl") if isinstance(obj, dict) else None)
        or (obj.get("url") if isinstance(obj, dict) else None)
    )


def _connect_sync(api_key: str, app: str, user_id: str) -> dict:
    toolkit_slug = _normalize_app(app)
    composio = Composio(api_key=api_key)

    # Check if already connected
    try:
        accounts = composio.connected_accounts.list(
            user_ids=[user_id],
            toolkit_slugs=[toolkit_slug],
            statuses=["ACTIVE"],
        )
        items = getattr(accounts, "items", None) or (accounts if isinstance(accounts, list) else [])
        if items:
            return {
                "connected": True,
                "app": toolkit_slug,
                "user_id": user_id,
                "message": f"{toolkit_slug} is already connected.",
            }
    except Exception:
        pass

    # Auto-resolve auth_config_id from dashboard
    auth_config_id = _get_auth_config_id(composio, toolkit_slug)

    try:
        req = composio.connected_accounts.initiate(
            user_id=user_id,
            auth_config_id=auth_config_id,
        )
    except Exception as exc:
        raise MCPError(
            f"Failed to initiate connection for {toolkit_slug}: {exc}",
            tool=TOOL_NAME,
        ) from exc

    redirect_url = _extract_redirect_url(req)
    if not redirect_url:
        raise MCPError(
            f"Could not get OAuth URL for {toolkit_slug}.",
            tool=TOOL_NAME,
        )

    return {
        "connected": False,
        "app": toolkit_slug,
        "user_id": user_id,
        "oauth_url": redirect_url,
        "message": (
            f"Open this URL to connect {toolkit_slug}:\n{redirect_url}\n\n"
            "After authorising, type 'connected' to continue."
        ),
    }


def _execute_sync(api_key: str, action: str, user_id: str, params: dict) -> dict:
    composio = Composio(api_key=api_key)

    try:
        response = composio.tools.execute(
            slug=action,
            arguments=params,
            user_id=user_id,
        )
    except Exception as exc:
        raise MCPError(
            f"Execution failed for action {action}: {exc}",
            tool=TOOL_NAME,
        ) from exc

    return {
        "success": True,
        "action": action,
        "result": response,
    }


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(
    action: str,
    user_id: str,
    app: str = "",
    params: dict | None = None,
) -> dict:
    settings = get_settings()

    if not settings.composio_api_key:
        raise MCPError("COMPOSIO_API_KEY is not set in environment.", tool=TOOL_NAME)

    loop = asyncio.get_running_loop()

    try:
        if action.strip().lower() == "connect":
            return await loop.run_in_executor(
                None,
                partial(_connect_sync, settings.composio_api_key, app, user_id),
            )

        return await loop.run_in_executor(
            None,
            partial(_execute_sync, settings.composio_api_key, action, user_id, params or {}),
        )
    except MCPError:
        raise
    except Exception as exc:
        raise MCPError(str(exc), tool=TOOL_NAME) from exc