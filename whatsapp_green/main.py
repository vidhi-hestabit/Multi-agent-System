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


@app.get("/success", response_class=HTMLResponse)
def success_page():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Connected – Nexus AI</title>
      <style>
        body { font-family: sans-serif; text-align: center; padding: 100px; background: #0f172a; color: white; }
        .success-card { background: #1e293b; padding: 40px; border-radius: 20px; max-width: 400px; margin: 0 auto; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        h1 { color: #25D366; }
        p { color: #94a3b8; line-height: 1.6; }
        .btn { display: inline-block; margin-top: 24px; padding: 12px 24px; background: #25D366; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; }
      </style>
    </head>
    <body>
      <div class="success-card">
        <h1>✅ Connected!</h1>
        <p>Your WhatsApp has been successfully linked.<br>You can now close this window and start chatting with the agent.</p>
        <a href="javascript:window.close()" class="btn">Close Window</a>
      </div>
    </body>
    </html>
    """)


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
    :root {{ --primary: #25D366; --bg: #0f172a; --card: #1e293b; --text: #f8fafc; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; padding: 20px; background: var(--bg); color: var(--text); margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }}
    .container {{ max-width: 420px; width: 100%; }}
    .card {{ background: var(--card); border-radius: 24px; padding: 40px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.05); }}
    h1 {{ font-size: 28px; margin: 0 0 12px 0; font-weight: 800; letter-spacing: -0.5px; }}
    p {{ color: #94a3b8; margin: 0 0 32px 0; font-size: 16px; line-height: 1.5; }}
    #qr-box {{ 
      background: white; border-radius: 20px; padding: 20px;
      margin: 0 auto; width: fit-content;
      position: relative;
    }}
    #qr-img {{ width: 240px; height: 240px; display: block; border-radius: 12px; }}
    #loader {{
      position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
      border: 4px solid #f3f3f3; border-top: 4px solid var(--primary);
      border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite;
    }}
    @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
    #status {{ margin-top: 24px; font-size: 14px; color: #64748b; font-weight: 500; min-height: 20px; }}
    .session-id {{ margin-top: 40px; font-size: 12px; color: #475569; letter-spacing: 1px; text-transform: uppercase; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="card" id="main-content">
      <h1>Link WhatsApp</h1>
      <p>Scan the QR code with WhatsApp on your phone to link your account.</p>
      <div id="qr-box">
        <div id="loader"></div>
        <img id="qr-img" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" alt="" />
      </div>
      <div id="status">Generating secure QR...</div>
    </div>
    <div class="session-id">Session: {user_id}</div>
  </div>

  <script>
    let connected = false;
    async function refresh() {{
      if (connected) return;
      try {{
        const res  = await fetch('/qr/{user_id}');
        const data = await res.json();

        if (data.status === 'connected') {{
          connected = true;
          document.getElementById('main-content').innerHTML = `
            <div style="padding: 20px 0;">
              <div style="font-size: 64px; margin-bottom: 24px;">✅</div>
              <h1 style="color: var(--primary);">Connected!</h1>
              <p>Success! Your WhatsApp is now linked.<br>Redirecting you now...</p>
            </div>
          `;
          setTimeout(() => {{ window.location.href = '/success'; }}, 2000);
          return;
        }}

        if (data.status === 'qr' && data.qr) {{
          document.getElementById('qr-img').src = 'data:image/png;base64,' + data.qr;
          document.getElementById('loader').style.display = 'none';
          document.getElementById('status').textContent = 'Menu > Linked Devices > Link a Device';
        }} else if (data.status === 'pending') {{
            document.getElementById('status').textContent = 'Evolution API is initializing...';
        }}
      }} catch (e) {{
          console.error("Refresh error:", e);
      }}
      setTimeout(refresh, 5000);
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
