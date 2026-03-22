from __future__ import annotations
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

class AgentRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, dict] = {}

    async def discover(self, urls: list[str]) -> None:
        async with httpx.AsyncClient(timeout=8) as client:
            for url in urls:
                try:
                    resp = await client.get(f"{url.rstrip('/')}/.well-known/agent.json")
                    resp.raise_for_status()
                    card = resp.json()
                    card["url"] = url.rstrip("/")
                    self._cards[card["url"]] = card
                    logger.info(
                        "Discovered %-22s  requires=%-30s  any_of=%s  produces=%s",
                        card.get("name"),
                        card.get("requires", []),
                        card.get("any_of_requires", []),
                        card.get("produces", []),
                    )
                except Exception as exc:
                    logger.warning("Cannot reach agent at %s: %s", url, exc)

    def all(self) -> list[dict]:
        return list(self._cards.values())

    def get(self, url: str) -> Optional[dict]:
        return self._cards.get(url.rstrip("/"))

    def summary(self) -> dict:
        return {
            c["url"]: {
                "name":            c["name"],
                "requires":        c.get("requires", []),
                "any_of_requires": c.get("any_of_requires", []),
                "produces":        c.get("produces", []),
            }
            for c in self._cards.values()
        }


registry = AgentRegistry()