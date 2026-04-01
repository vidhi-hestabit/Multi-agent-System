"""
Evolution API WhatsApp Gateway
────────────────────────────────
Self-hosted Baileys (like OpenClaw). Admin runs one Docker container.
Users just visit /connect/{user_id} → QR appears → scan → done.
No external accounts needed for users.

Evolution API Docker:
  docker run -d --name evolution-api -p 8080:8080 \\
    -e AUTHENTICATION_API_KEY=nexus_secret_key \\
    atendai/evolution-api:latest

Endpoints:
  GET  /connect/{user_id}   → QR onboarding page (instant QR, no form)
  GET  /qr/{user_id}        → Live QR code JSON for that user
  GET  /status/{user_id}    → Connection state
  POST /webhook             → Evolution API event webhook (all users)
  GET  /health              → Health check
"""
from __future__ import annotations
import asyncio
import logging
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from common.config import get_settings
from common.whatsapp_store import get_instance, upsert_instance, mark_connected

logger   = logging.getLogger(__name__)
settings = get_settings()

ENTRY_AGENT_URL = f"http://localhost:{settings.entry_agent_port}/query"
PORT            = getattr(settings, "green_api_gateway_port", 8031)
EVO_URL         = settings.evolution_api_url.rstrip("/")
EVO_KEY         = settings.evolution_api_key

app = FastAPI(title="Evolution API WhatsApp Gateway")


# ─────────────────────────────────────────────────────────────────────
# Evolution API helpers
# ─────────────────────────────────────────────────────────────────────

def _evo_headers() -> dict:
    return {"apikey": EVO_KEY, "Content-Type": "application/json"}


async def _ensure_instance(user_id: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{EVO_URL}/instance/fetchInstances",
                headers=_evo_headers(),
            )
            data = r.json() if r.status_code == 200 else {}
            
            # Handle both {"count":0} and list responses
            if isinstance(data, list):
                instances = data
            elif isinstance(data, dict):
                instances = data.get("instances", [])  # some versions nest it
            else:
                instances = []

            existing = [i for i in instances
                        if i.get("instance", {}).get("instanceName") == user_id
                        or i.get("name") == user_id]
            if existing:
                return True

            # Create new instance
            r2 = await client.post(
                f"{EVO_URL}/instance/create",
                headers=_evo_headers(),
                json={
                    "instanceName": user_id,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS",
                },
            )
            logger.info("Evolution API create response: %s %s", r2.status_code, r2.text)
            return r2.status_code in (200, 201)
    except Exception as exc:
        logger.error("_ensure_instance error: %s", exc)
        return False


async def _get_qr(user_id: str) -> dict:
    """Fetch QR or connection state from Evolution API."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{EVO_URL}/instance/connect/{user_id}",
                headers=_evo_headers(),
            )
        body = r.json()
    except Exception as exc:
        return {"error": str(exc)}

    # Evolution API returns {"code": "...", "base64": "data:image/png;base64,..."}
    # or {"instance": {"state": "open"}} when already connected
    if body.get("base64"):
        # Strip the data URL prefix if present
        b64 = body["base64"]
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        return {"status": "qr", "qr": b64}
    state = (body.get("instance") or {}).get("state", "")
    if state == "open":
        return {"status": "connected"}
    return {"status": "pending", "raw": body}


async def _get_state(user_id: str) -> str:
    """Return Evolution API connection state string."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{EVO_URL}/instance/connectionState/{user_id}",
                headers=_evo_headers(),
            )
        body  = r.json()
        return (body.get("instance") or {}).get("state", "unknown")
    except Exception:
        return "unknown"


# ─────────────────────────────────────────────────────────────────────
# QR Onboarding endpoints
# ─────────────────────────────────────────────────────────────────────

@app.get("/connect/{user_id}", response_class=HTMLResponse)
async def connect_page(user_id: str):
    """
    Per-user QR onboarding page. No form, no credentials.
    Creates the Evolution API instance automatically on first visit.
    """
    await _ensure_instance(user_id)
    return HTMLResponse(_qr_page(user_id))


@app.get("/qr/{user_id}")
async def get_qr(user_id: str):
    """Return live QR or connected status for a user."""
    await _ensure_instance(user_id)
    return JSONResponse(await _get_qr(user_id))


@app.get("/status/{user_id}")
async def connection_status(user_id: str):
    state     = await _get_state(user_id)
    connected = state == "open"
    if connected:
        await mark_connected(user_id)
    return JSONResponse({"connected": connected, "state": state})


# ─────────────────────────────────────────────────────────────────────
# Incoming messages → Entry Agent
# ─────────────────────────────────────────────────────────────────────

async def _send_reply(user_id: str, number: str, text: str) -> None:
    """Send reply via Evolution API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{EVO_URL}/message/sendText/{user_id}",
                headers=_evo_headers(),
                json={"number": number, "text": text},
            )
        logger.info("Evolution API: replied to %s (user=%s)", number, user_id)
    except Exception as exc:
        logger.error("Evolution API send exception: %s", exc)


async def _process_and_reply(user_id: str, number: str, text: str) -> None:
    logger.info("Evolution API: from=%s user=%s query=%r", number, user_id, text)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(ENTRY_AGENT_URL, json={"query": text})
            resp.raise_for_status()
            data = resp.json()
        reply = data.get("result") or data.get("error") or "No response."
    except Exception as exc:
        reply = f"Error: {exc}"
    await _send_reply(user_id, number, str(reply))


@app.post("/webhook")
async def webhook(request: Request):
    """
    Evolution API sends all events here.
    Set this URL in Evolution API: WEBHOOK_GLOBAL_URL or per-instance webhook.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "ignored"})

    event = body.get("event", "")
    logger.debug("Evolution API webhook event: %s", event)

    # Handle QR connected event → mark in DB
    if event == "connection.update":
        state       = (body.get("data") or {}).get("state", "")
        instance_id = body.get("instance", "")
        if state == "open" and instance_id:
            await mark_connected(instance_id)
            logger.info("Evolution API: %s connected", instance_id)
        return JSONResponse({"status": "ok"})

    # Incoming message
    if event not in ("messages.upsert", "messages.set"):
        return JSONResponse({"status": "ignored", "event": event})

    data     = body.get("data") or {}
    msg      = data if "message" in data else {}
    key      = msg.get("key", {})
    from_me  = key.get("fromMe", False)
    if from_me:
        return JSONResponse({"status": "ignored", "reason": "own_message"})

    number      = key.get("remoteJid", "").replace("@s.whatsapp.net", "").replace("@c.us", "")
    text        = (
        (msg.get("message") or {}).get("conversation")
        or (msg.get("message") or {}).get("extendedTextMessage", {}).get("text", "")
    ).strip()
    instance_id = body.get("instance", "")  # Evolution API instance name = user_id

    if not text or not number or not instance_id:
        return JSONResponse({"status": "ignored", "reason": "missing_fields"})

    asyncio.create_task(_process_and_reply(instance_id, number, text))
    return JSONResponse({"status": "received"})


@app.get("/webhook")
def webhook_verify():
    return JSONResponse({"status": "ok"})


@app.get("/health")
def health():
    return {"status": "ok", "service": "evolution-api-gateway"}


# ─────────────────────────────────────────────────────────────────────
# QR page HTML (no form — instant QR)
# ─────────────────────────────────────────────────────────────────────

def _qr_page(user_id: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Connect WhatsApp – Nexus AI</title>
  <style>
    body {{ font-family: sans-serif; text-align: center; padding: 40px; background: #f0f4f8; }}
    h2   {{ color: #1a202c; }}
    #qr-box {{ margin: 30px auto; width: 280px; min-height: 280px;
               background: white; border-radius: 12px; padding: 20px;
               box-shadow: 0 4px 12px rgba(0,0,0,.1); }}
    #qr-box img {{ width: 240px; height: 240px; }}
    #status {{ margin-top: 16px; font-size: 14px; color: #666; }}
    .connected {{ color: #22c55e; font-weight: bold; font-size: 18px; }}
  </style>
</head>
<body>
  <h2>🔗 Connect WhatsApp to Nexus AI</h2>
  <p>Scan the QR code below with your WhatsApp app</p>
  <div id="qr-box">
    <img id="qr-img" src="" alt="Loading QR..." />
    <p id="status">Loading...</p>
  </div>
  <p style="color:#999;font-size:12px;">Session ID: {user_id}</p>

  <script>
    async function refresh() {{
      const res  = await fetch('/qr/{user_id}');
      const data = await res.json();

      if (data.status === 'connected') {{
        document.getElementById('qr-box').innerHTML =
          '<p class="connected">✅ WhatsApp Connected!<br>You can start sending queries.</p>';
        return;
      }}

      if (data.status === 'qr' && data.qr) {{
        document.getElementById('qr-img').src = 'data:image/png;base64,' + data.qr;
        document.getElementById('status').textContent = 'Scan with WhatsApp → Linked Devices → Link a Device';
      }} else {{
        document.getElementById('status').textContent =
          'Waiting for QR... (' + (data.status || 'pending') + ')';
      }}
      setTimeout(refresh, 8000);  // refresh every 8s
    }}
    refresh();
  </script>
</body>
</html>"""


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    logger.info("Starting Evolution API gateway on port %d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=8031,reload=False)
