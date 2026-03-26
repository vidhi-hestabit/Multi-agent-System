from __future__ import annotations
from functools import lru_cache
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from common.config import get_settings

@lru_cache(maxsize=1)
def _client() -> AsyncIOMotorClient:
    settings = get_settings()
    return AsyncIOMotorClient(settings.mongodb_url)

def get_db() -> AsyncIOMotorDatabase:
    settings = get_settings()
    return _client()[settings.mongodb_db]
