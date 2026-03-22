from __future__ import annotations
import json
import logging
from groq import AsyncGroq
from common.config import get_settings
logger = logging.getLogger(__name__)

def _settings():
    return get_settings()

def _llm() -> AsyncGroq:
    settings = _settings()
    return AsyncGroq(api_key=settings.groq_api_key)

def _model() -> str:
    return _settings().groq_model

async def ask_llm(system: str, user: str, max_tokens: int = 200, temperature: float = 0.0, json_mode: bool = False) -> str:
    kwargs: dict = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await _llm().chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return (content.strip().replace("```json", "").replace("```", "").strip())
    except Exception as exc:
        logger.exception("LLM call failed")
        raise RuntimeError(f"LLM call failed: {exc}") from exc

async def ask_llm_json( system: str, user: str, max_tokens: int = 200) -> dict:
    raw = await ask_llm( system=system, user=user, max_tokens=max_tokens, json_mode=True)
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("Failed to parse json_mode response, retrying with normal mode")

    try:
        raw = await ask_llm( system=system, user=user, max_tokens=max_tokens, json_mode=False)
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to parse LLM JSON response")
        return {}