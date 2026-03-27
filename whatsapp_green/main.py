"""
Green API WhatsApp Gateway
──────────────────────────
Receives incoming WhatsApp messages from Green API webhook
and forwards them to the Entry Agent for processing, then
replies back via Green API.

Green API sends a POST to this endpoint for every incoming message.
Set this URL in your Green API instance settings as the webhook URL.
"""
from __future__ import annotations
import logging
import httpx
import re
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.config import get_settings

logger  = logging.getLogger(__name__)
settings = get_settings()

ENTRY_AGENT_URL = f"http://localhost:{settings.entry_agent_port}/query"
PORT            = getattr(settings, "green_api_gateway_port", 8031)

app = FastAPI(title="Green API WhatsApp Gateway")


def _normalise_number(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        digits = "91" + digits
    return f"{digits}@c.us"


async def _send_reply(chat_id: str, text: str) -> None:
    """Send a reply back via Green API REST endpoint."""
    instance_id = getattr(settings, "green_api_instance_id", "")
    token       = getattr(settings, "green_api_token", "")
    if not instance_id or not token:
        logger.error("Green API credentials not configured — cannot send reply")
        return
    url = (
        f"https://api.green-api.com/waInstance{instance_id}"
        f"/sendMessage/{token}"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json={"chatId": chat_id, "message": text})
        if resp.status_code == 200:
            logger.info("Green API: reply sent to %s", chat_id)
        else:
            logger.error("Green API send failed: %s %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Green API send exception: %s", exc)


async def _process_and_reply(chat_id: str, user_query: str) -> None:
    """Call Entry Agent and send result back to WhatsApp."""
    logger.info("Green API: query from %s → %r", chat_id, user_query)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(ENTRY_AGENT_URL, json={"query": user_query})
            resp.raise_for_status()
            data = resp.json()
        reply = data.get("result") or data.get("error") or "No response from agent."
    except Exception as exc:
        logger.error("Entry Agent error: %s", exc)
        reply = f"Error reaching agent: {exc}"

    await _send_reply(chat_id, str(reply))


@app.get("/webhook")
def green_api_webhook_verify():
    """Green API pings GET /webhook to verify the URL is reachable."""
    return JSONResponse({"status": "ok"})


@app.post("/webhook")
async def green_api_webhook(request: Request):
    """
    Green API calls this endpoint for every event.
    We only care about incoming text messages (typeWebhook = incomingMessageReceived).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "ignored", "reason": "invalid JSON"})

    webhook_type = body.get("typeWebhook", "")
    if webhook_type != "incomingMessageReceived":
        # Not a message we need to handle (status updates, etc.)
        return JSONResponse({"status": "ignored", "type": webhook_type})

    message_data = body.get("messageData", {})
    msg_type     = message_data.get("typeMessage", "")
    if msg_type != "textMessage":
        # Only handle text for now
        return JSONResponse({"status": "ignored", "reason": "non-text message"})

    text     = message_data.get("textMessageData", {}).get("textMessage", "").strip()
    chat_id  = body.get("senderData", {}).get("chatId", "")
    sender   = body.get("senderData", {}).get("sender", chat_id)

    if not text or not chat_id:
        return JSONResponse({"status": "ignored", "reason": "empty text or chat_id"})

    logger.info("Green API webhook: from=%s text=%r", sender, text)

    # Process asynchronously — send an immediate ack back
    import asyncio
    asyncio.create_task(_process_and_reply(chat_id, text))

    return JSONResponse({"status": "received"})


@app.get("/health")
def health():
    return {"status": "ok", "service": "green-api-gateway"}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    logger.info("Starting Green API gateway on port %d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
