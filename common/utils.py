from __future__ import annotations
import time
from typing import Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

def retry_async(max_attempts: int = 3, min_wait: float = 1.0, max_wait: float = 10.0):
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )

def truncate(text: str, max_length: int = 500) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

def safe_get(d: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d

async def measure_ms(coro) -> tuple[Any, float]:
    start = time.perf_counter()
    result = await coro
    elapsed = (time.perf_counter() - start) * 1000
    return result, elapsed