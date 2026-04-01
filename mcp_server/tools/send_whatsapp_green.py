"""
Evolution API WhatsApp MCP Tool
─────────────────────────────────
Sends WhatsApp messages via self-hosted Evolution API (Baileys).
Supports both phone numbers AND contact names (fuzzy lookup).
"""
from __future__ import annotations
import httpx
import logging
import re
from difflib import SequenceMatcher
from common.config import get_settings
from common.errors import MCPError
from mcp_server.app import mcp

logger    = logging.getLogger(__name__)
TOOL_NAME = "send_whatsapp_green"
TOOL_DESCRIPTION = (
    "Send a WhatsApp message using Evolution API (self-hosted Baileys). "
    "phone_number accepts a phone number (e.g. 917599292135) OR a contact name "
    "(e.g. 'Vidhi HestaBit') — looks up name in WhatsApp contacts automatically. "
    "user_id identifies whose WhatsApp session to use."
)


def _normalise_number(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if not digits:
        raise ValueError("No digits in number")
    if len(digits) == 10:
        digits = "91" + digits
    return digits   # Evolution API uses plain digits (no @c.us)


def _looks_like_number(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 7 and len(digits) / max(len(value), 1) > 0.6


def _best_contact_match(contacts: list[dict], query: str) -> dict | None:
    query_lower = query.lower().strip()
    best_score, best = 0.0, None
    for c in contacts:
        name = (c.get("pushName") or c.get("name") or c.get("verifiedName") or "").lower()
        if not name:
            continue
        if name == query_lower:
            return c
        score = SequenceMatcher(None, query_lower, name).ratio()
        if query_lower in name or name in query_lower:
            score = max(score, 0.85)
        if score > best_score:
            best_score, best = score, c
    return best if best_score >= 0.70 else None


async def _get_contacts(user_id: str, evo_url: str, evo_key: str) -> list[dict]:
    """Fetch contacts from Evolution API for a given instance (user)."""
    headers = {"apikey": evo_key}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{evo_url}/chat/findContacts/{user_id}",
                headers=headers,
            )
        if r.status_code == 200:
            data = r.json()
            # Evolution API returns list directly or {"contacts": [...]}
            return data if isinstance(data, list) else data.get("contacts", [])
    except Exception as exc:
        logger.warning("Evolution API getContacts failed: %s", exc)
    return []


async def _resolve_recipient(value: str, user_id: str, evo_url: str, evo_key: str) -> str:
    """Resolve name or number to a plain phone number string."""
    value = value.strip()
    if _looks_like_number(value):
        return _normalise_number(value)

    logger.info("Resolving contact name %r for user=%s", value, user_id)
    contacts = await _get_contacts(user_id, evo_url, evo_key)
    if not contacts:
        raise MCPError(
            f"Could not fetch contacts for user '{user_id}'. "
            "Is their WhatsApp connected? (visit /connect/{user_id})",
            tool=TOOL_NAME,
        )

    match = _best_contact_match(contacts, value)
    if not match:
        sample = [c.get("pushName") or c.get("name", "") for c in contacts[:5]]
        raise MCPError(
            f"No contact matching '{value}'. Sample: {sample}",
            tool=TOOL_NAME,
        )

    # Extract number from id like "917599292135@s.whatsapp.net"
    jid = match.get("id") or match.get("remoteJid") or ""
    number = re.sub(r"\D", "", jid.split("@")[0]) if jid else ""
    if not number:
        number = _normalise_number(match.get("phone") or match.get("number") or "")

    logger.info("Resolved %r → %s (%s)", value, number,
                match.get("pushName") or match.get("name", ""))
    return number


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(phone_number: str, message: str, user_id: str = "") -> dict:
    """
    Send a WhatsApp message. phone_number = number or contact name.
    user_id = Evolution API instance name (= user's session).
    """
    settings = get_settings()
    evo_url  = settings.evolution_api_url.rstrip("/")
    evo_key  = settings.evolution_api_key

    # Fallback user_id to admin instance if not specified
    if not user_id:
        user_id = "admin"

    if not message.strip():
        raise MCPError("Message cannot be empty", tool=TOOL_NAME)

    number = await _resolve_recipient(phone_number, user_id, evo_url, evo_key)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{evo_url}/message/sendText/{user_id}",
                headers={"apikey": evo_key, "Content-Type": "application/json"},
                json={"number": number, "text": message},
            )
        body = resp.json()
    except Exception as exc:
        raise MCPError(f"Evolution API request failed: {exc}", tool=TOOL_NAME)

    if resp.status_code not in (200, 201):
        raise MCPError(
            f"Evolution API returned {resp.status_code}: {body}",
            tool=TOOL_NAME,
        )

    # Evolution API returns {"key": {"id": "..."}} on success
    msg_id = (body.get("key") or {}).get("id") or body.get("id", "")
    return {
        "success":    True,
        "to":         phone_number,
        "number":     number,
        "message_id": msg_id,
    }
