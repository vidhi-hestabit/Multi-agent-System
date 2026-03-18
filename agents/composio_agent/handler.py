from __future__ import annotations

import json
from langgraph.graph import END

from common.config import get_settings
from common.logging import get_logger
from agents.base_agent.base_handler import BaseHandler, AgentState
from agents.base_agent.base_mcp_client import BaseMCPClient

logger = get_logger(__name__)

SUPPORTED_APPS: dict[str, str] = {
    "gmail": "GMAIL",
    "email": "GMAIL",
    "slack": "SLACK",
    "telegram": "TELEGRAM",
    "discord": "DISCORD",
}

SUPPORTED_APPS_DISPLAY = "Gmail, Slack, Telegram, Discord"

SEND_KEYWORDS = {
    "send", "email", "mail", "slack", "telegram",
    "discord", "deliver", "forward", "share", "notify", "message",
}


def _extract_app(text: str) -> str | None:
    lower = (text or "").lower()
    for key, slug in SUPPORTED_APPS.items():
        if key in lower:
            return slug
    return None


def _normalize_tool_result(result) -> dict:
    """
    Normalize different MCP tool response shapes into a plain dict.

    Handles:
    - dict already
    - JSON string
    - {"result": {...}}
    - {"content": [{"type":"text","text":"{...json...}"}]}
    - {"content": [{"text":"..."}]}
    """
    if result is None:
        return {}

    if isinstance(result, dict):
        if "oauth_url" in result or "connected" in result or "success" in result:
            return result

        if isinstance(result.get("result"), dict):
            inner = result["result"]
            if "oauth_url" in inner or "connected" in inner or "success" in inner:
                return inner

        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", "")
                if text:
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass

        structured = result.get("structured_content")
        if isinstance(structured, dict):
            return structured

        return result

    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {"raw": result}

    return {"raw": result}


class ComposioAgentHandler(BaseHandler):
    def __init__(self):
        self.settings = get_settings()
        self.mcp = BaseMCPClient()
        super().__init__()

    def _build_graph(self):
        self.add_node("route", self._route)
        self.add_node("ask_app", self._ask_app)
        self.add_node("connect_app", self._connect_app)
        self.add_node("ask_recipient", self._ask_recipient)
        self.add_node("send_message", self._send_message)
        self.add_node("complete", self._complete_node)

        self.set_entry("route")

        self.add_conditional_edges(
            "route",
            self._router_condition,
            {
                "ask_app": "ask_app",
                "connect_app": "connect_app",
                "ask_recipient": "ask_recipient",
                "send": "send_message",
                "complete": "complete",
            },
        )

        self.add_edge("ask_app", END)
        self.add_edge("connect_app", END)
        self.add_edge("ask_recipient", END)
        self.add_edge("send_message", "complete")
        self.finish("complete")

    def _router_condition(self, state: AgentState) -> str:
        meta = state.get("metadata", {})
        if not meta.get("app_slug"):
            return "ask_app"
        if not meta.get("app_connected"):
            return "connect_app"
        if not meta.get("recipient"):
            return "ask_recipient"
        if not meta.get("sent"):
            return "send"
        return "complete"

    async def _route(self, state: AgentState) -> AgentState:
        for key, value in list(state.get("metadata", {}).items()):
            if key.startswith("__state_"):
                real_key = key[len("__state_"):]
                state["metadata"][real_key] = value
                del state["metadata"][key]

        history = state.get("history", [])
        if history:
            last_user = next(
                (h["text"] for h in reversed(history) if h["role"] == "user"),
                "",
            )
            state["metadata"]["latest_user_message"] = last_user

        content = state.get("message", "")
        if "report_markdown" in state.get("metadata", {}):
            content = state["metadata"]["report_markdown"]
        state["metadata"]["content_to_send"] = content

        return state

    async def _ask_app(self, state: AgentState) -> AgentState:
        meta = state.get("metadata", {})
        latest = meta.get("latest_user_message", state.get("message", ""))
        app_slug = _extract_app(latest)

        if app_slug:
            meta["app_slug"] = app_slug.upper()
            return await self._connect_app(state)

        state["needs_input"] = True
        state["input_prompt"] = (
            f"Which app should I use to send the message?"
            f"Supported: {SUPPORTED_APPS_DISPLAY}"
            "Type the app name to continue."
        )
        return state

    async def _connect_app(self, state: AgentState) -> AgentState:
        meta = state.get("metadata", {})
        latest_user_message = meta.get("latest_user_message", "")

        app_slug = meta.get("app_slug") or _extract_app(latest_user_message)
        if not app_slug:
            state["needs_input"] = True
            state["input_prompt"] = (
                f"I did not recognise that app. Please choose one of: {SUPPORTED_APPS_DISPLAY}"
            )
            return state

        meta["app_slug"] = app_slug.upper()
        app_slug = meta["app_slug"]

        user_id = meta.setdefault(
            "composio_user_id",
            f"agent_{(state.get('session_id') or state.get('task_id', 'default'))[:12]}"
        )

        latest = meta.get("latest_user_message", "").strip().lower()
        if meta.get("awaiting_oauth") and latest in {
            "connected", "done", "ok", "yes", "ready", "complete"
        }:
            meta["awaiting_oauth"] = False

        try:
            raw_result = await self.mcp.call_tool(
                "composio_tool",
                {
                    "action": "connect",
                    "app": app_slug,
                    "user_id": user_id,
                },
            )
            logger.info("composio_connect_raw_result", result=raw_result)

            result = _normalize_tool_result(raw_result)
            logger.info("composio_connect_normalized_result", result=result)

        except Exception as exc:
            state["needs_input"] = True
            state["input_prompt"] = (
                f"Could not reach Composio: {exc}"
                "Please check your COMPOSIO_API_KEY and try again."
            )
            return state

        if result.get("connected"):
            meta["app_connected"] = True
            label = {
                "GMAIL": "recipient email address",
                "SLACK": "#channel-name or a member ID",
                "TELEGRAM": "your numeric Telegram chat ID",
                "DISCORD": "Discord channel ID",
            }.get(app_slug, "recipient")

            state["needs_input"] = True
            state["input_prompt"] = (
                f"{app_slug} is connected."
                f"Who should I send the message to?({label})"
            )
            return state

        oauth_url = result.get("oauth_url", "")
        if not oauth_url:
            state["needs_input"] = True
            state["input_prompt"] = (
                f"Connection was initiated for {app_slug}, but no OAuth URL was returned."
                f"Tool response: {result}"
            )
            return state

        meta["awaiting_oauth"] = True
        state["needs_input"] = True
        state["input_prompt"] = (
            f"To connect your {app_slug} account, open this link:"
            f"{oauth_url}  "
            "After you have authorised, type 'connected' to continue."
        )
        return state

    async def _ask_recipient(self, state: AgentState) -> AgentState:
        meta = state.get("metadata", {})
        latest = meta.get("latest_user_message", state.get("message", "")).strip()

        if latest:
            meta["recipient"] = latest
            return await self._send_message(state)

        state["needs_input"] = True
        state["input_prompt"] = "Please enter the recipient address."
        return state

    async def _send_message(self, state: AgentState) -> AgentState:
        meta = state.get("metadata", {})
        recipient = meta.get("recipient") or meta.get("latest_user_message", "").strip()

        if not recipient:
            state["needs_input"] = True
            state["input_prompt"] = "Please enter the recipient address."
            return state

        meta["recipient"] = recipient

        app_slug = meta["app_slug"].upper()
        user_id = meta["composio_user_id"]
        content = meta.get("content_to_send", "")
        title = meta.get("report_title", "Message")

        payload = {
            "app": app_slug,
            "user_id": user_id,
            "to": recipient,
        }
        if app_slug == "GMAIL":
            payload.update({"subject": title, "body": content})
        else:
            payload.update({"body": content})

        try:
            raw_result = await self.mcp.call_tool("send_message", payload)
            logger.info("send_message_raw_result", result=raw_result)

            result = _normalize_tool_result(raw_result)
            logger.info("send_message_normalized_result", result=result)

            meta["sent"] = True
        except Exception as exc:
            logger.error("send_message_failed", error=str(exc))
            meta["sent"] = False
            state["error"] = f"Failed to send via {app_slug}: {exc}"
            return state

        state["result"] = f"Message sent to {recipient} via {app_slug}."
        state["result_data"] = {
            "sent_via": app_slug,
            "sent_to": recipient,
            "tool_result": result,
        }
        return state

    async def _complete_node(self, state: AgentState) -> AgentState:
        if not state.get("result"):
            state["result"] = "Done."
        return state