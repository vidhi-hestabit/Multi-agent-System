from __future__ import annotations
import asyncio, os
from functools import partial
from pathlib import Path
from common.config import get_settings
from common.errors import MCPError
from mcp_server.app import mcp

TOOL_NAME = "composio_tool"
TOOL_DESCRIPTION = (
    "Universal Composio tool. action='connect' to check/initiate OAuth. "
    "Or pass an action like GMAIL_SEND_EMAIL."
)

_APP_SLUG = {
    "GMAIL":    "gmail",    "gmail":    "gmail",    "email":   "gmail",
    "SLACK":    "slack",    "slack":    "slack",
    "TELEGRAM": "telegram", "telegram": "telegram",
    "DISCORD":  "discord",  "discord":  "discord",
}


def _configure_cache() -> None:
    project_cache = Path(__file__).resolve().parents[2] / ".composio-cache"
    for raw in [os.environ.get("COMPOSIO_CACHE_DIR",""), str(project_cache), "/tmp/composio-cache"]:
        if not raw: continue
        p = Path(raw).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            (p / ".write-test").write_text("ok")
            (p / ".write-test").unlink()
            os.environ["COMPOSIO_CACHE_DIR"] = str(p)
            return
        except OSError:
            continue


def _patch_composio_http():
    try:
        import requests, requests.adapters as _ra

        _orig_init = requests.Session.__init__
        def _patched_init(self, *args, **kwargs):
            _orig_init(self, *args, **kwargs)
            self.trust_env = False
        requests.Session.__init__ = _patched_init

        _orig_send = _ra.HTTPAdapter.send
        def _adapter_send(self, request, **kwargs):
            if any(d in (request.url or "") for d in ("composio.dev", "backend.composio")):
                kwargs["proxies"] = {}
            return _orig_send(self, request, **kwargs)
        _ra.HTTPAdapter.send = _adapter_send

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("composio proxy patch failed: %s", exc)


_patch_composio_http()

def _get_toolset():
    _configure_cache()
    try:
        from composio import ComposioToolSet
        return ComposioToolSet
    except Exception as exc:
        raise MCPError(f"Composio SDK unavailable: {exc}", tool=TOOL_NAME) from exc


def _slug(app: str) -> str:
    if not app: raise MCPError("app is required for connect.", tool=TOOL_NAME)
    return _APP_SLUG.get(app.strip(), app.strip().lower())


def _redirect_url(obj) -> str | None:
    for attr in ("redirectUrl","redirect_url","redirectUri","redirect_uri","url"):
        val = getattr(obj, attr, None) or (isinstance(obj, dict) and obj.get(attr))
        if val: return str(val)
    return None


def _connect_sync(api_key: str, app: str, user_id: str) -> dict:
    slug    = _slug(app)
    toolset = _get_toolset()(api_key=api_key, entity_id=user_id)
    entity  = toolset.client.get_entity(id=user_id)

    try:
        conn = entity.get_connection(app=slug)
        if conn:
            return {"connected": True, "app": slug, "user_id": user_id,
                    "message": f"{slug} already connected."}
    except Exception:
        pass

    try:
        req = entity.initiate_connection(app_name=slug)
    except Exception as exc:
        raise MCPError(f"Failed to initiate {slug} OAuth: {exc}", tool=TOOL_NAME) from exc

    url = _redirect_url(req)
    if not url:
        raise MCPError(f"No OAuth URL for {slug}. Response: {req}", tool=TOOL_NAME)

    return {"connected": False, "app": slug, "user_id": user_id, "oauth_url": url,
            "message": f"Open this URL to connect {slug}:\n{url}\nThen retry."}


def _execute_sync(api_key: str, action: str, user_id: str, params: dict) -> dict:
    toolset = _get_toolset()(api_key=api_key, entity_id=user_id)
    try:
        resp = toolset.execute_action(action=action, params=params, entity_id=user_id)
    except Exception as exc:
        raise MCPError(f"Action {action} failed: {exc}", tool=TOOL_NAME) from exc
    if not isinstance(resp, dict):
        return {"success": True, "action": action, "result": str(resp)}
    if resp.get("success") or resp.get("successful") or resp.get("successfull") or resp.get("status")=="success":
        return {"success": True, "action": action, "result": resp}
    inner = resp.get("data") or resp.get("response") or resp
    if isinstance(inner, dict) and inner.get("success"):
        return {"success": True, "action": action, "result": inner}
    raise MCPError(f"Action {action} failed: {resp.get('error', resp)}", tool=TOOL_NAME)


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(action: str, user_id: str, app: str = "", params: dict | None = None) -> dict:
    api_key = get_settings().composio_api_key
    if not api_key or api_key == "your_composio_key_here":
        raise MCPError("COMPOSIO_API_KEY not set in .env.local", tool=TOOL_NAME)
    loop = asyncio.get_running_loop()
    try:
        if action.strip().lower() == "connect":
            return await loop.run_in_executor(None, partial(_connect_sync, api_key, app, user_id))
        return await loop.run_in_executor(None, partial(_execute_sync, api_key, action, user_id, params or {}))
    except MCPError: raise
    except Exception as exc:
        raise MCPError(str(exc), tool=TOOL_NAME) from exc