from __future__ import annotations
import hashlib
import logging
import re
import httpx
import uvicorn
from agents.base import BaseAgent
from agents.llm_utils import ask_llm, ask_llm_json
from common.config import get_settings
from common.prompts.composio_prompts import DELIVERY_SYSTEM, SUBJECT_WRITER_SYSTEM

logger = logging.getLogger(__name__)
settings = get_settings()
PORT = settings.composio_agent_port
HOST = settings.composio_agent_host
MCP = settings.mcp_server_url

DEFAULT_APP = getattr(settings, "default_composio_app", "GMAIL")
DEFAULT_RECIPIENT = getattr(settings, "default_email_recipient", "")
CONTENT_KEYS = ["report_markdown", "news_summary", "weather_data_text", "sql_answer", "rag_answer"]


class ComposioAgent(BaseAgent):
    @property
    def agent_card(self) -> dict:
        return {
            "name": "Composio Agent",
            "description": "Sends content via Gmail, Slack, Telegram, or Discord.",
            "url": f"http://{HOST}:{PORT}",
            "version": "1.0.0",
            "protocolVersion": "0.3.0",
            "requires": [],
            "any_of_requires": CONTENT_KEYS,
            "prefers": ["report_markdown"], 
            "produces": ["message_sent_confirmation"],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "send_via_composio",
                    "name": "Send Message",
                    "tags": ["gmail", "slack", "telegram", "discord", "email"],
                }
            ],
        }

    @staticmethod
    def _extract_whatsapp_recipient(instruction: str) -> str | None:
        """
        Extract WhatsApp recipient directly from the instruction via regex.
        Returns the raw name or number exactly as written (case-preserved).
        Never touches an LLM — no hallucination possible.
        """
        # Patterns ordered by specificity
        patterns = [
            # "send it to Vidhi HestaBit on WhatsApp"
            r"send\s+(?:it\s+)?to\s+(.+?)\s+on\s+whatsapp",
            # "send it to Vidhi HestaBit via WhatsApp"
            r"send\s+(?:it\s+)?to\s+(.+?)\s+via\s+whatsapp",
            # "whatsapp Vidhi HestaBit"
            r"whatsapp\s+([^,\.]+?)(?:\s+and|\s*$)",
            # "message Vidhi HestaBit on WhatsApp"
            r"message\s+(.+?)\s+on\s+whatsapp",
            # "to 917599292135 on WhatsApp"
            r"to\s+(\+?[\d\s\-]+)\s+on\s+whatsapp",
        ]
        for pattern in patterns:
            m = re.search(pattern, instruction, re.IGNORECASE)
            if m:
                return m.group(1).strip().strip("'\"")
        return None

    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        delivery = await ask_llm_json(DELIVERY_SYSTEM, instruction, max_tokens=80)
        app = (
            delivery.get("app", "") or context.get("composio_app") or DEFAULT_APP
        ).upper()

        # ── Reliable WhatsApp recipient extraction (regex beats LLM here) ──
        whatsapp_recipient = self._extract_whatsapp_recipient(instruction)
        if whatsapp_recipient and app in ("WHATSAPP_GREEN", "GREEN", "WHATSAPP"):
            # Force WHATSAPP_GREEN for Green API and use the regex-extracted name
            app = "WHATSAPP_GREEN"
            recipient = whatsapp_recipient
            logger.info("ComposioAgent: regex-extracted WhatsApp recipient=%r", recipient)
        else:
            recipient = (
                delivery.get("recipient", "")
                or context.get("composio_recipient")
                or context.get("email_recipient")
                or DEFAULT_RECIPIENT
            )

        if not recipient:
            return {
                "message_sent_confirmation": (
                    "No recipient found. Include an address, channel, or chat ID in your query."
                )
            }

        content = next(
            (str(context[k]) for k in CONTENT_KEYS if context.get(k)), instruction
        )
        subject = await self._make_subject(context, instruction)
        sender_email = (
            context.get("user_email")
            or context.get("composio_recipient")
            or "default"
        )
        stable_seed = f"{app}:{sender_email}"
        user_id = "mas_" + hashlib.md5(stable_seed.encode()).hexdigest()[:16]
        logger.info(
            "ComposioAgent task=%s app=%s recipient=%s user_id=%s",
            task_id[:8], app, recipient, user_id,
        )

        # ── Green API (Baileys) — bypass Composio OAuth entirely ──────
        if app in ("WHATSAPP_GREEN", "GREEN"):
            send = await self._mcp_send(app, user_id, recipient, subject, content)
            if send.get("success"):
                msg = f"WhatsApp message sent to '{recipient}' via Green API."
            else:
                msg = f"WhatsApp (Green API) send failed: {send.get('error', 'unknown')}"
            logger.info("ComposioAgent (Green API): %s", msg)
            return {"message_sent_confirmation": msg}

        # ── Composio OAuth flow for Gmail/Slack/Telegram/Discord ──────
        connect = await self._mcp_connect(app, user_id)
        if not connect.get("connected"):
            oauth_url = connect.get("oauth_url", "")
            error = connect.get("error", "")
            if not oauth_url:
                return {
                    "message_sent_confirmation": f"{app} connection failed: {error or 'unknown'}"
                }
            return {
                "message_sent_confirmation": f"{app} not connected. Authorize at: {oauth_url}",
                "oauth_url": oauth_url,
                "oauth_required": True,
            }

        send = await self._mcp_send(app, user_id, recipient, subject, content)

        if send.get("success"):
            msg = f"Sent via {app} to '{recipient}'. Subject: '{subject}'."
        else:
            msg = f"Failed to send via {app}: {send.get('error', 'unknown')}"
        logger.info("ComposioAgent: %s", msg)
        return {"message_sent_confirmation": msg}

    async def _make_subject(self, context: dict, instruction: str) -> str:
        if context.get("report_title"):
            return context["report_title"]

        available = []
        if context.get("city_name"):
            available.append(f"city: {context['city_name']}")
        if context.get("news_topic"):
            available.append(f"topic: {context['news_topic']}")
        if context.get("sql_answer"):
            available.append("database query result")
        if context.get("rag_answer"):
            available.append("legal research result")
        if context.get("weather_data_text"):
            available.append("weather data")

        prompt = (
            f"User request: {instruction}\n"
            f"Content: {', '.join(available) or 'general result'}\n"
            "Write a short professional subject line (max 8 words). Return ONLY the subject."
        )
        try:
            return (
                await ask_llm(SUBJECT_WRITER_SYSTEM, prompt, max_tokens=30)
            ).strip().strip("\"'.")
        except Exception:
            return "Result from AI Agent"

    @staticmethod
    def _extract_mcp_error(body: dict, status_code: int) -> str:
        detail = body.get("detail")
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
        if isinstance(detail, str) and detail:
            return detail
        if body.get("message"):
            return str(body["message"])
        if body.get("error"):
            return str(body["error"])
        return f"MCP HTTP {status_code}"

    async def _mcp_connect(self, app: str, user_id: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{MCP}/tools/call",
                    json={
                        "tool": "composio_tool",
                        "arguments": {
                            "action": "connect",
                            "app": app,
                            "user_id": user_id,
                        },
                    },
                )
            body = response.json()
            if response.status_code != 200:
                return {
                    "connected": False,
                    "error": self._extract_mcp_error(body, response.status_code),
                }
            return body.get("result", {})
        except Exception as exc:
            logger.error("Composio connect failed: %s", exc)
            return {"connected": False, "error": str(exc)}

    async def _mcp_send(
        self, app: str, user_id: str, recipient: str, subject: str, body: str
    ) -> dict:
        args = {"app": app, "user_id": user_id, "to": recipient, "body": body}
        if app == "GMAIL":
            args["subject"] = subject
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{MCP}/tools/call",
                    json={"tool": "send_message", "arguments": args},
                )
            payload = response.json()
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": self._extract_mcp_error(payload, response.status_code),
                }
            return payload.get("result", {})
        except Exception as exc:
            logger.error("MCP send_message failed: %s", exc)
            return {"success": False, "error": str(exc)}


app = ComposioAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)