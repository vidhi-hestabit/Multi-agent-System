from __future__ import annotations
import hashlib
import logging
from datetime import datetime, timezone
import bcrypt
import jwt
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from common.config import get_settings
from common.db import get_db

logger = logging.getLogger(__name__)
settings = get_settings()
MCP_URL = settings.mcp_server_url

# Pydantic models
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ChatSaveRequest(BaseModel):
    query: str
    result: str = ""
    agents_called: list[str] = []
    status: str = "completed"
    context_keys: list[str] = []

class ChannelUpdateRequest(BaseModel):
    channel: str
    connected: bool
    user_id: str = ""

# JWT helpers
def _create_token(user_id: str, email: str) -> str:
    return jwt.encode(
        {"sub": user_id, "email": email},
        settings.jwt_secret,
        algorithm="HS256",
    )

def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

async def _get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    payload = _decode_token(auth[7:])
    db = get_db()
    user = await db.users.find_one({"email": payload["email"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# Composio helper
def _composio_user_id(app: str, email: str) -> str:
    seed = f"{app}:{email}"
    return "mas_" + hashlib.md5(seed.encode()).hexdigest()[:16]

async def _check_composio_connection(app: str, user_id: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{MCP_URL}/tools/call",
                json={
                    "tool": "composio_tool",
                    "arguments": {"action": "connect", "app": app, "user_id": user_id},
                },
            )
        body = r.json()
        if r.status_code != 200:
            return {"connected": False, "error": body.get("message", str(body))}
        return body.get("result", {})
    except Exception as exc:
        logger.error("Composio connect check failed: %s", exc)
        return {"connected": False, "error": str(exc)}

# App
def create_app() -> FastAPI:
    app = FastAPI(title="Auth Server", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    db = get_db()

    @app.on_event("startup")
    async def startup():
        await db.users.create_index("email", unique=True)
        await db.chats.create_index([("user_email", 1), ("created_at", -1)])
        logger.info("Auth server indexes ensured")

    # Register
    @app.post("/auth/register")
    async def register(req: RegisterRequest):
        existing = await db.users.find_one({"email": req.email})
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered.")

        pw_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
        composio_uid = _composio_user_id("GMAIL", req.email)

        user_doc = {
            "name": req.name,
            "email": req.email,
            "password_hash": pw_hash,
            "composio_user_id": composio_uid,
            "channels": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(user_doc)
        token = _create_token(composio_uid, req.email)

        # Trigger Gmail OAuth check
        gmail_result = await _check_composio_connection("GMAIL", composio_uid)
        oauth_url = None
        if gmail_result.get("connected"):
            user_doc["channels"]["GMAIL"] = {"connected": True, "user_id": composio_uid}
            await db.users.update_one(
                {"email": req.email},
                {"$set": {"channels.GMAIL": {"connected": True, "user_id": composio_uid}}},
            )
        else:
            oauth_url = gmail_result.get("oauth_url")

        return {
            "token": token,
            "name": req.name,
            "email": req.email,
            "channels": user_doc.get("channels", {}),
            "is_new": True,
            "oauth_url": oauth_url,
        }

    # Login
    @app.post("/auth/login")
    async def login(req: LoginRequest):
        user = await db.users.find_one({"email": req.email})
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        if not bcrypt.checkpw(req.password.encode(), user["password_hash"].encode()):
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        token = _create_token(user["composio_user_id"], req.email)
        return {
            "token": token,
            "name": user["name"],
            "email": user["email"],
            "channels": user.get("channels", {}),
            "is_new": False,
        }

    # Get chats (top 10)
    @app.get("/me/chats")
    async def get_chats(limit: int = 10, user: dict = Depends(_get_current_user)):
        cursor = db.chats.find(
            {"user_email": user["email"]},
            {"_id": 0},
        ).sort("created_at", -1).limit(min(limit, 10))
        return await cursor.to_list(length=10)

    # Save chat (enforce max 10)
    @app.post("/me/chats")
    async def save_chat(req: ChatSaveRequest, user: dict = Depends(_get_current_user)):
        chat_doc = {
            "user_email": user["email"],
            "query": req.query,
            "result": req.result,
            "agents_called": req.agents_called,
            "status": req.status,
            "context_keys": req.context_keys,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.chats.insert_one(chat_doc)
        count = await db.chats.count_documents({"user_email": user["email"]})
        if count > 10:
            overflow = count - 10
            oldest = db.chats.find(
                {"user_email": user["email"]},
            ).sort("created_at", 1).limit(overflow)
            ids_to_delete = [doc["_id"] async for doc in oldest]
            if ids_to_delete:
                await db.chats.delete_many({"_id": {"$in": ids_to_delete}})
        return {"ok": True}

    # Update channel
    @app.patch("/me/channels")
    async def update_channel(req: ChannelUpdateRequest, user: dict = Depends(_get_current_user)):
        channel_key = req.channel.upper()
        if req.connected:
            update = {"$set": {f"channels.{channel_key}": {"connected": True, "user_id": req.user_id}}}
        else:
            update = {"$unset": {f"channels.{channel_key}": ""}}
        await db.users.update_one({"email": user["email"]}, update)
        return {"ok": True}

    # Check channel connection status
    @app.get("/me/channels/{app}/status")
    async def channel_status(app: str, user: dict = Depends(_get_current_user)):
        app_upper = app.upper()
        channel_data = user.get("channels", {}).get(app_upper, {})
        if channel_data.get("connected"):
            return {"app": app_upper, "connected": True, "source": "database"}
        composio_uid = _composio_user_id(app_upper, user["email"])
        result = await _check_composio_connection(app_upper, composio_uid)
        if result.get("connected"):
            await db.users.update_one(
                {"email": user["email"]},
                {"$set": {f"channels.{app_upper}": {"connected": True, "user_id": composio_uid}}},
            )
            return {"app": app_upper, "connected": True, "source": "composio"}

        # Telegram fallback: if native bot token exists, mark as connected
        if app_upper == "TELEGRAM" and settings.telegram_bot_token:
            await db.users.update_one(
                {"email": user["email"]},
                {"$set": {f"channels.TELEGRAM": {"connected": True, "user_id": "native_bot"}}},
            )
            return {"app": "TELEGRAM", "connected": True, "source": "native_bot"}

        return {
            "app": app_upper,
            "connected": False,
            "oauth_url": result.get("oauth_url"),
        }


    # Health
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "auth-server"}

    return app

# Entry point
app = create_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8020)
