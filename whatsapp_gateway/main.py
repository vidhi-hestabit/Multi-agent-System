from __future__ import annotations

import asyncio
import logging
import re

import httpx
import uvicorn
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse

from common.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PORT = settings.whatsapp_gateway_port
HOST = settings.whatsapp_gateway_host
ENTRY_AGENT_URL = settings.entry_agent_url
MCP_SERVER_URL = settings.mcp_server_url
VERIFY_TOKEN = settings.whatsapp_verify_token
PHONE_NUMBER_ID = settings.whatsapp_phone_number_id

COMPOSIO_ENTITY_ID = settings.whatsapp_composio_entity_id

# WhatsApp message max length
WA_MAX_LEN = 4096

#  Helpers

def strip_markdown(text: str) -> str:
    """Strip common Markdown formatting for clean WhatsApp display."""
    text = re.sub(r"#{1,6}\s*", "", text)                          # headings
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)                 # bold → WA bold
    text = re.sub(r"__(.+?)__", r"_\1_", text)                     # underline → italic
    text = re.sub(r"`{3}[\s\S]*?`{3}", "", text)                   # code blocks
    text = re.sub(r"`(.+?)`", r"\1", text)                         # inline code
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)                # links
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)     # bullets
    text = re.sub(r"\n{3,}", "\n\n", text)                         # collapse blanks
    return text.strip()

def truncate(text: str, limit: int = WA_MAX_LEN) -> str:
    """Truncate text to WhatsApp's character limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "\n\n… _[response trimmed]_"

async def send_whatsapp_reply(to_number: str, text: str) -> bool:
    """
    Send a WhatsApp reply via Composio's WHATSAPP_SEND_MESSAGE action
    through the MCP server's composio_tool.
    """
    try:
        user_id = COMPOSIO_ENTITY_ID or f"mas_whatsapp_{PHONE_NUMBER_ID[:16]}"
        async with httpx.AsyncClient(timeout=30) as client:
            # Use the existing composio_tool via MCP server
            r = await client.post(
                f"{MCP_SERVER_URL}/tools/call",
                json={
                    "tool": "send_message",
                    "arguments": {
                        "app": "WHATSAPP",
                        "user_id": user_id,
                        "to": to_number,
                        "body": text,
                    },
                },
            )
            result = r.json()
            if r.status_code == 200 and result.get("result", {}).get("success"):
                logger.info("WhatsApp reply sent to %s", to_number)
                return True
            else:
                logger.error("WhatsApp send failed: %s", result)
                return False
    except Exception as exc:
        logger.exception("Failed to send WhatsApp reply: %s", exc)
        return False

async def process_and_reply(sender_number: str, message_text: str) -> None:
    """Forward the query to Entry Agent and send the response back via WhatsApp."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{ENTRY_AGENT_URL}/query",
                json={"query": message_text},
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()

        result = data.get("result") or data.get("error") or "No response from agents."
        status = data.get("status", "unknown")
        agents = data.get("agents_called", [])

        # Format reply
        reply = strip_markdown(result)

        if agents:
            agent_names = ", ".join(agents)
            reply += f"\n\n_Agents: {agent_names} | Status: {status}_"

        reply = truncate(reply)

    except httpx.TimeoutException:
        reply = (
            "⏳ Your query is taking longer than expected. "
            "Please try again in a moment."
        )
    except Exception as exc:
        logger.exception("Error calling Entry Agent: %s", exc)
        reply = (
            "❌ Sorry, I couldn't process your query right now. "
            "Please make sure the Nexus system is running."
        )

    await send_whatsapp_reply(sender_number, reply)

#  Extract message from Meta webhook payload 
def extract_message(body: dict) -> tuple[str, str] | None:
    """
    Extract (sender_phone, message_text) from Meta's webhook payload.
    Returns None if the payload doesn't contain a text message.
    """
    try:
        entry = body.get("entry", [])
        if not entry:
            return None

        changes = entry[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        if msg.get("type") != "text":
            return None

        sender = msg.get("from", "")
        text = msg.get("text", {}).get("body", "")

        if sender and text:
            return (sender, text)
    except (IndexError, KeyError, TypeError):
        pass

    return None

# FastAPI App 
def create_app() -> FastAPI:
    app = FastAPI(
        title="Nexus WhatsApp Gateway",
        description="Bridges WhatsApp (via Meta Cloud API + Composio) to the Nexus Multi-Agent System.",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        )
        if not PHONE_NUMBER_ID:
            logger.warning(
                "WHATSAPP_PHONE_NUMBER_ID not set! "
                "Configure it in .env.local for WhatsApp replies to work."
            )
        logger.info(
            "WhatsApp Gateway ready — port=%s verify_token=%s phone_id=%s",
            PORT,
            VERIFY_TOKEN[:4] + "***" if VERIFY_TOKEN else "(not set)",
            PHONE_NUMBER_ID or "(not set)",
        )

    #  Meta Webhook Verification (GET)
    @app.get("/whatsapp/webhook")
    async def verify_webhook(
        request: Request,
    ):
        """
        Meta sends a GET request with hub.mode, hub.verify_token, and
        hub.challenge to verify the webhook endpoint during setup.
        """
        params = request.query_params
        mode = params.get("hub.mode", "")
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully")
            return PlainTextResponse(content=challenge, status_code=200)

        logger.warning("Webhook verification failed: mode=%s token=%s", mode, token)
        return PlainTextResponse(content="Forbidden", status_code=403)

    #  Incoming WhatsApp Messages (POST) 
    @app.post("/whatsapp/webhook")
    async def receive_message(request: Request):
        """
        Meta sends incoming WhatsApp messages as JSON POST.
        We extract the message, immediately return 200 to Meta,
        and process the query in the background.
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"status": "error"}, status_code=400)

        result = extract_message(body)

        if result:
            sender, text = result
            logger.info("WhatsApp from %s: %s", sender, text[:80])
            # Process in background — don't block the webhook
            asyncio.create_task(process_and_reply(sender, text))

        # Always return 200 to Meta (required, or they'll retry)
        return JSONResponse({"status": "ok"}, status_code=200)

    #  Health 
    @app.get("/whatsapp/health")
    async def health():
        return {
            "status": "ok",
            "service": "whatsapp-gateway",
            "phone_number_id_set": bool(PHONE_NUMBER_ID),
            "entry_agent_url": ENTRY_AGENT_URL,
            "mcp_server_url": MCP_SERVER_URL,
        }

    return app

#  Entry point 
app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
