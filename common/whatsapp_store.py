"""
common/whatsapp_store.py
─────────────────────────
MongoDB CRUD for per-user Evolution API WhatsApp instances.
Collection: whatsapp_instances
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from common.db import get_db

COLLECTION = "whatsapp_instances"


async def get_instance(user_id: str) -> Optional[dict]:
    """Fetch a user's WhatsApp instance from MongoDB."""
    db = get_db()
    return await db[COLLECTION].find_one({"user_id": user_id}, {"_id": 0})


async def upsert_instance(user_id: str, extra: dict | None = None) -> dict:
    """Create or update an instance record for a user."""
    db  = get_db()
    now = datetime.utcnow()
    doc: dict = {"user_id": user_id, "connected": False, "updated_at": now}
    if extra:
        doc.update(extra)
    await db[COLLECTION].update_one(
        {"user_id": user_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return doc


async def mark_connected(user_id: str, whatsapp_number: str = "") -> None:
    """Mark the user's instance as connected after QR scan."""
    db = get_db()
    await db[COLLECTION].update_one(
        {"user_id": user_id},
        {"$set": {
            "connected":       True,
            "whatsapp_number": whatsapp_number,
            "updated_at":      datetime.utcnow(),
        }},
    )


async def list_instances() -> list[dict]:
    """List all registered WhatsApp instances."""
    db = get_db()
    cursor = db[COLLECTION].find({}, {"_id": 0})
    return await cursor.to_list(length=None)
