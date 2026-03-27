"""
Green API WhatsApp MCP Tool
────────────────────────────
Sends WhatsApp messages via Green API (Baileys-based).
Supports both phone numbers AND contact names (looks up your WhatsApp contacts).
"""
from __future__ import annotations
import httpx
import re
import logging
from difflib import SequenceMatcher
from common.config import get_settings
from common.errors import MCPError
from mcp_server.app import mcp

logger = logging.getLogger(__name__)

TOOL_NAME = "send_whatsapp_green"
TOOL_DESCRIPTION = (
    "Send a WhatsApp message using Green API (Baileys-based, no business account needed). "
    "The 'phone_number' field accepts: a phone number (e.g. 917599292135) OR a contact name "
    "(e.g. 'Vidhi HestaBit') — it will look up the name in your WhatsApp contacts automatically."
)

_CONTACTS_CACHE: list[dict] = []  # in-memory cache, refreshed each time


def _normalise_number(number: str) -> str:
    """Convert any phone number format to chatId: 917599292135@c.us"""
    digits = re.sub(r"\D", "", number)
    if not digits:
        raise ValueError("Phone number contains no digits")
    if len(digits) == 10:
        digits = "91" + digits  # assume India if no country code
    return f"{digits}@c.us"


def _looks_like_number(value: str) -> bool:
    """True if value is mostly digits (a phone number, not a name)."""
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 7 and len(digits) / max(len(value), 1) > 0.6


def _best_contact_match(contacts: list[dict], query: str) -> dict | None:
    """
    Find the best matching contact by name using fuzzy matching.
    Returns the contact dict or None if no good match found.
    """
    query_lower = query.lower().strip()
    best_score = 0.0
    best_contact = None

    for contact in contacts:
        name = (contact.get("name") or contact.get("contactName") or "").lower().strip()
        if not name:
            continue

        # Exact match wins immediately
        if name == query_lower:
            return contact

        # Fuzzy ratio
        score = SequenceMatcher(None, query_lower, name).ratio()

        # Bonus for substring match (e.g. "Vidhi" matches "Vidhi HestaBit")
        if query_lower in name or name in query_lower:
            score = max(score, 0.85)

        if score > best_score:
            best_score = score
            best_contact = contact

    # Only return if confidence >= 70%
    return best_contact if best_score >= 0.70 else None


async def _get_contacts(instance_id: str, token: str) -> list[dict]:
    """Fetch contact list from Green API."""
    url = f"https://api.green-api.com/waInstance{instance_id}/getContacts/{token}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            return resp.json() or []
        logger.warning("Green API getContacts returned %s", resp.status_code)
    except Exception as exc:
        logger.warning("Green API getContacts failed: %s", exc)
    return []


async def _resolve_recipient(
    phone_number_or_name: str,
    instance_id: str,
    token: str,
) -> str:
    """
    Resolve a phone number OR contact name to a chatId.
    Returns chatId like '917599292135@c.us'.
    """
    value = phone_number_or_name.strip()

    # If it looks like a number, normalise directly
    if _looks_like_number(value):
        return _normalise_number(value)

    # It's a name — fetch contacts and fuzzy-match
    logger.info("Green API: resolving contact name %r", value)
    contacts = await _get_contacts(instance_id, token)

    if not contacts:
        raise MCPError(
            f"Could not fetch contacts to resolve '{value}'. "
            "Is your Green API instance connected (QR scanned)?",
            tool=TOOL_NAME,
        )

    match = _best_contact_match(contacts, value)
    if not match:
        # List top 5 available names for debugging
        names = [c.get("name") or c.get("contactName", "") for c in contacts[:5]]
        raise MCPError(
            f"No contact found matching '{value}'. "
            f"Available contacts (sample): {names}",
            tool=TOOL_NAME,
        )

    # Contact found — extract chatId or phone number
    chat_id = match.get("id") or match.get("chatId") or ""
    if not chat_id:
        number = match.get("phone") or match.get("phoneNumber") or ""
        chat_id = _normalise_number(number)

    # Ensure @c.us suffix
    if "@" not in chat_id:
        chat_id = _normalise_number(chat_id)

    logger.info(
        "Green API: resolved %r → %s (%s)",
        value,
        chat_id,
        match.get("name") or match.get("contactName", ""),
    )
    return chat_id


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(phone_number: str, message: str) -> dict:
    """
    Send a WhatsApp message. phone_number can be a number OR a contact name.
    """
    settings    = get_settings()
    instance_id = getattr(settings, "green_api_instance_id", "")
    token       = getattr(settings, "green_api_token", "")

    if not instance_id or not token:
        raise MCPError(
            "GREEN_API_INSTANCE_ID or GREEN_API_TOKEN not set in .env.local",
            tool=TOOL_NAME,
        )
    if not message.strip():
        raise MCPError("Message cannot be empty", tool=TOOL_NAME)

    # Resolve name → chatId (or normalise number)
    chat_id = await _resolve_recipient(phone_number, instance_id, token)

    url     = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{token}"
    payload = {"chatId": chat_id, "message": message}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
        body = resp.json()
    except Exception as exc:
        raise MCPError(f"HTTP request to Green API failed: {exc}", tool=TOOL_NAME)

    if resp.status_code != 200:
        raise MCPError(
            f"Green API returned {resp.status_code}: {body}",
            tool=TOOL_NAME,
        )

    if body.get("idMessage"):
        return {
            "success":    True,
            "chat_id":    chat_id,
            "to":         phone_number,
            "message_id": body["idMessage"],
        }

    raise MCPError(f"Green API unexpected response: {body}", tool=TOOL_NAME)
