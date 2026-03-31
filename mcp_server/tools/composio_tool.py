from __future__ import annotations
import asyncio, os, typing as t
import logging
from functools import partial
from pathlib import Path
import traceback
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
    "WHATSAPP": "whatsapp", "whatsapp": "whatsapp",
}

# Map app slug -> auth_config_id (set via env vars for each app)
# These are the auth config IDs from the Composio dashboard
def _get_auth_config_id(slug: str) -> str:
    settings = get_settings()
    mapping = {
        "gmail":    getattr(settings, "composio_gmail_auth_config_id", ""),
        "slack":    getattr(settings, "composio_slack_auth_config_id", ""),
        "telegram": getattr(settings, "composio_telegram_auth_config_id", ""),
        "discord":  getattr(settings, "composio_discord_auth_config_id", ""),
        "whatsapp": getattr(settings, "composio_whatsapp_auth_config_id", ""),
    }
    return mapping.get(slug, "")


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

# --- Monkey-patch Composio SDK for 'type' KeyError fix ---
try:
    from composio.core.models._files import FileHelper, FileDownloadable
    
    def _patched_substitute_file_downloads_recursively(
        self,
        tool, # Tool
        schema: t.Dict,
        request: t.Dict,
    ) -> t.Dict:
        if "properties" not in schema:
            return request

        params = schema["properties"]
        for _param in request:
            if _param not in params:
                continue

            if self._is_file_downloadable(schema=params[_param]):
                request[_param] = str(
                    FileDownloadable(**request[_param]).download(
                        self._outdir / tool.toolkit.slug / tool.slug
                    )
                )
                continue

            if "anyOf" in params[_param]:
                obj = self._find_file_downloadable_from_any_of(params[_param]["anyOf"])
                if obj is None:
                    continue
                params[_param] = obj

            # FIX: Use .get("type") instead of ["type"] to handle schemas with $ref
            if isinstance(request[_param], dict) and params[_param].get("type") == "object":
                request[_param] = self._substitute_file_downloads_recursively(
                    schema=params[_param],
                    request=request[_param],
                    tool=tool,
                )
                continue

        return request

    FileHelper._substitute_file_downloads_recursively = _patched_substitute_file_downloads_recursively
    logging.getLogger(__name__).info("Composio SDK monkey-patch (KeyError: 'type' fix) applied.")
except Exception as patch_exc:
    logging.getLogger(__name__).warning("Failed to apply Composio monkey-patch: %s", patch_exc)


def _get_client(api_key: str):
    _configure_cache()
    try:
        from composio import Composio
        return Composio(api_key=api_key)
    except Exception as exc:
        raise MCPError(f"Composio SDK unavailable: {exc}", tool=TOOL_NAME) from exc


def _slug(app: str) -> str:
    if not app: raise MCPError("app is required for connect.", tool=TOOL_NAME)
    return _APP_SLUG.get(app.strip(), app.strip().lower())


def _redirect_url(obj) -> str | None:
    for attr in ("redirectUrl","redirect_url","redirectUri","redirect_uri","url",
                 "connectionStatus", "connection_status"):
        val = getattr(obj, attr, None) or (isinstance(obj, dict) and obj.get(attr))
        if val and str(val).startswith("http"): return str(val)
    # Try nested
    for attr in ("data", "response"):
        sub = getattr(obj, attr, None) or (isinstance(obj, dict) and obj.get(attr))
        if isinstance(sub, dict):
            for k in ("redirectUrl","redirect_url","url","oauth_url"):
                if sub.get(k) and str(sub[k]).startswith("http"):
                    return str(sub[k])
    return None


def _connect_sync(api_key: str, app: str, user_id: str) -> dict:
    slug   = _slug(app)
    client = _get_client(api_key)

    # Check if already connected
    try:
        result = client.connected_accounts.list(
            user_ids=[user_id],
            # toolkit_slugs=[slug],
            statuses=["ACTIVE"],
        )
        items = getattr(result, "items", None) or getattr(result, "data", None) or []
        matched = [i for i in items 
                   if slug in (
                       getattr(i, "toolkit_slug", "") or 
                       getattr(getattr(i, "toolkit", None), "slug", "") or ""
                   ).lower()]
        if matched:
            return {"connected": True, 
                    "app": slug, 
                    "user_id": user_id,
                    "message": f"{slug} already connected."}
        #items = getattr(result, "items", None)  or []
        # items = [i for i in items if getattr(i, "toolkit", {}) and 
        #          getattr(i.toolkit, "slug", "") == slug]
        # if items:
        #     return {"connected": True, "app": slug, "user_id": user_id,
        #             "message": f"{slug} already connected."}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("connected_accounts.list failed: %s",e)

    # Get auth_config_id for this app
    auth_config_id = _get_auth_config_id(slug)

    # Initiate connection
    try:
        if auth_config_id:
            req = client.connected_accounts.initiate(
                user_id=user_id,
                auth_config_id=auth_config_id,
                allow_multiple=True,
            )
        else:
            req = client.toolkits.authorize(
                user_id=user_id,
                toolkit=slug,
            )
    except Exception as exc:
        err_str = str(exc)
        if "Multiple connected accounts" in err_str or "MultipleConnected" in err_str:
            return {"connected": True, 
                    "app": slug, 
                    "user_id": user_id,
                    "message": f"{slug} already connected."}
        raise MCPError(f"Failed to initiate {slug} OAuth: {exc}", tool=TOOL_NAME) from exc

    url = _redirect_url(req)
    if not url:
        # Some integrations (API key based) connect immediately
        status = getattr(req, "status", "") or getattr(req, "connectionStatus", "")
        if str(status).upper() in ("ACTIVE", "CONNECTED"):
            return {"connected": True, "app": slug, "user_id": user_id,
                    "message": f"{slug} connected."}
        raise MCPError(f"No OAuth URL for {slug}. Response: {req}", tool=TOOL_NAME)

    return {"connected": False, "app": slug, "user_id": user_id, "oauth_url": url,
            "message": f"Open this URL to connect {slug}:\n{url}\nThen retry."}


def _execute_sync(api_key: str, action: str, user_id: str, params: dict) -> dict:
    client = _get_client(api_key)
    try:
        resp = client.tools.execute(
            slug=action,
            arguments=params,
            user_id=user_id,
            dangerously_skip_version_check=True,
        )
    except Exception as exc:
        err_str = str(exc)
        logger = logging.getLogger(__name__)
        logger.error("Composio execution failed: %s", err_str, exc_info=True)
        # If connection is missing, try to initiate and return URL
        if any(msg in err_str.lower() for msg in ["no active accounts", "no connected account", "no connection", "no account", "authenticat", "failed"]):
            logger.info("Matched connection error keywords. Initiating connect...")
            try:
                # Extract app name from action (e.g. SLACK_SEND_MESSAGE -> slack)
                app_name = action.split("_")[0].lower()
                conn = _connect_sync(api_key, app_name, user_id)
                if not conn.get("connected") and conn.get("oauth_url"):
                    return {"success": False, "connected": False, "oauth_url": conn["oauth_url"], 
                            "message": f"Please connect {app_name} first:\n{conn['oauth_url']}"}
            except Exception as e:
                logger.error("Auto-connect failed: %s", e)
        raise MCPError(f"Action {action} failed: {exc}", tool=TOOL_NAME) from exc

    # ToolExecutionResponse object
    if not isinstance(resp, dict):
        data = getattr(resp, "data", None) or getattr(resp, "response_data", None)
        success = getattr(resp, "successful", None) or getattr(resp, "success", None)
        if success:
            return {"success": True, "action": action, "result": data or str(resp)}
        err = getattr(resp, "error", str(resp))
        raise MCPError(f"Action {action} failed: {err}", tool=TOOL_NAME)

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