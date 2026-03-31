from __future__ import annotations
import asyncio
import logging
import uuid
import httpx
from agents.task_store import store
from agents.registry   import registry

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}

def _lock(task_id: str) -> asyncio.Lock:
    if task_id not in _locks:
        _locks[task_id] = asyncio.Lock()
    return _locks[task_id]

async def resolve_and_trigger(task_id: str) -> None:
    async with _lock(task_id):
        await _resolve(task_id)

async def _resolve(task_id: str) -> None:
    task = store.get(task_id)
    if not task or task["final_status"] != "running":
        return
    context_keys = set(task["context"].keys())
    required = set(task["required_outputs"])
    remaining = required - context_keys
    logger.info(
        "RESOLVE task=%s  have=%s  need=%s",
        task_id[:8], sorted(context_keys), sorted(remaining),
    )

    # All done 
    if not remaining:
        result = _pick_result(task["context"], required)
        store.complete(task_id, result)
        logger.info("Task %s  →  COMPLETED", task_id[:8])
        return

    # Categorise each registered agent 
    eligible:       list[dict] = []
    still_running:  list[str]  = []
    failed_agents:  list[str]  = []

    report_producers = [
        c for c in registry.all()
        if "report_markdown" in c.get("produces", [])
    ]

    for card in registry.all():
        url    = card["url"]
        status = task["agent_runs"].get(url)
        if status == "running":
            still_running.append(card["name"])
            continue
        if status == "failed":
            failed_agents.append(card["name"])
            continue
        if status == "done":
            continue
        requires = card.get("requires", [])   # ALL must be present
        any_of_requires = card.get("any_of_requires", [])   # at least ONE must be present
        produces = card.get("produces", [])

        # Check ALL hard prerequisites
        if not all(r in context_keys for r in requires):
            continue
        # Check OR prerequisites (if declared)
        if any_of_requires and not any(r in context_keys for r in any_of_requires):
            continue
        # Must contribute at least one still-needed output
        if not any(p in remaining for p in produces):
            continue

        if "message_sent_confirmation" in produces:
            if (
                "report_markdown" in required
                and "report_markdown" not in context_keys
                and report_producers
                and not all(
                    task["agent_runs"].get(c["url"]) == "done"
                    for c in report_producers
                )
            ):
                logger.info(
                    "Composio blocked — waiting for Report Agent  task=%s",
                    task_id[:8],
                )
                continue        
        eligible.append(card)

    # Nothing eligible right now 
    if not eligible:
        if still_running:
            logger.info("Task %s  waiting for: %s", task_id[:8], still_running)
            return 
        failed_str = f", failed: {failed_agents}" if failed_agents else ""
        error = (
            f"Cannot produce: {sorted(remaining)}. "
            f"Context has: {sorted(context_keys)}{failed_str}. "
            f"Registered agents: {[c['name'] for c in registry.all()]}. "
            f"Tip: make sure all required agents are running and reachable."
        )
        store.fail(task_id, error)
        logger.error("DEADLOCK task=%s  %s", task_id[:8], error)
        return

    # Mark + fire 
    for card in eligible:
        store.mark_agent(task_id, card["url"], "running")
        logger.info("Scheduled  %-24s  task=%s", card["name"], task_id[:8])

    for card in eligible:
        asyncio.create_task(_call_agent(task_id, card))


async def _call_agent(task_id: str, card: dict) -> None:
    url  = card["url"]
    name = card["name"]
    task = store.get(task_id)
    if not task:
        return
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{url}/",
                json={
                    "jsonrpc": "2.0",
                    "id":      str(uuid.uuid4()),
                    "method":  "tasks/send",
                    "params":  {
                        "id":          task_id,
                        "instruction": task["original_query"],
                    },
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()

        body   = resp.json()
        result = body.get("result", {})

        if result.get("status") == "failed":
            err = result.get("error", "unknown")
            logger.error("%-24s  FAILED (run error)  task=%s  err=%s", name, task_id[:8], err)
            store.mark_agent(task_id, url, "failed")
        else:
            logger.info("%-24s  DONE  task=%s  wrote=%s",
                        name, task_id[:8], result.get("keys_written", []))
            store.mark_agent(task_id, url, "done")

    except Exception as exc:
        logger.error("%-24s  FAILED (http)  task=%s  err=%s", name, task_id[:8], exc)
        store.mark_agent(task_id, url, "failed")

    await resolve_and_trigger(task_id)

def _pick_result(context: dict, required: set[str] | list[str]) -> str:
    for key in (
        "chat",
        "message_sent_confirmation",
        "report_markdown",
        "news_summary",
        "rag_answer",
        "sql_answer",
        "weather_data_text",
    ):
        if key in required and context.get(key):
            return str(context[key])
    
        for key in ("chat","message_sent_confirmation","report_markdown","news_summary","rag_answer","sql_answer","weather_data_text"):
            if context.get(key):
                return str(context[key])

    return str(context)