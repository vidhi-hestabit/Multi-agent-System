from __future__ import annotations
import json
import logging
from typing import Any
import uvicorn
from groq import AsyncGroq
from agents.base import BaseAgent
from agents.llm_utils import ask_llm
from common.config import get_settings
from common.prompts.report_prompts import TITLE_GENERATION_SYSTEM, REPORT_WRITER_SYSTEM

logger = logging.getLogger(__name__)
settings = get_settings()
PORT = settings.report_agent_port
HOST = settings.report_agent_host

# Keys that are orchestration / runtime noise — never included in report body.
IGNORE_KEYS = {
    "task_id", "original_query", "required_outputs", "agent_runs",
    "final_status", "created_at", "result", "error",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pretty_label(key: str) -> str:
    return key.replace("_", " ").strip().title()


def _format_scalar(value: Any) -> str:
    return "N/A" if value is None else str(value)


def _format_list(value: list[Any]) -> str:
    if not value:
        return "_No items available._"
    if all(not isinstance(item, (dict, list)) for item in value):
        return "\n".join(f"- {item}" for item in value)

    lines: list[str] = []
    for i, item in enumerate(value[:10], start=1):
        if isinstance(item, (dict, list)):
            pretty = json.dumps(item, indent=2, ensure_ascii=False)
            lines.append(f"- Item {i}:\n```json\n{pretty}\n```")
        else:
            lines.append(f"- {item}")
    if len(value) > 10:
        lines.append(f"\n_And {len(value) - 10} more items._")
    return "\n".join(lines)


def _format_dict(value: dict[str, Any]) -> str:
    if not value:
        return "_No details available._"
    is_flat = all(not isinstance(v, (dict, list)) for v in value.values())
    if is_flat:
        lines = ["| Field | Value |", "|---|---|"]
        for k, v in value.items():
            lines.append(f"| {_pretty_label(str(k))} | {_format_scalar(v)} |")
        return "\n".join(lines)
    pretty = json.dumps(value, indent=2, ensure_ascii=False)
    return f"json\n{pretty}\n"


def _format_value(value: Any) -> str:
    if isinstance(value, dict):
        return _format_dict(value)
    if isinstance(value, list):
        return _format_list(value)
    return _format_scalar(value)


def _collect_report_sections(context: dict[str, Any]) -> list[str]:
    sections: list[str] = []
    for key, value in context.items():
        if key in IGNORE_KEYS or value in (None, "", [], {}):
            continue
        sections.append(f"## {_pretty_label(key)}\n{_format_value(value)}")
    return sections


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ReportAgent(BaseAgent):
    @property
    def agent_card(self) -> dict:
        return {
            "name": "Report Agent",
            "description": "Generates a simple Markdown report from any available blackboard/context data.",
            "url": f"http://{HOST}:{PORT}",
            "version": "2.0.0",
            "protocolVersion": "0.3.0",
            "requires": [],
            "any_of_requires": [
                "news_summary",
                "weather_data_text",
                "sql_answer",
                "rag_answer",
                "chat",
            ],
            "produces": ["report_markdown", "report_title"],
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "generate_report",
                    "name": "Generate Report",
                    "description": "Build a simple Markdown report from any context data.",
                    "tags": ["report", "summary", "markdown"],
                }
            ],
        }

    async def run(self, task_id: str, instruction: str, context: dict) -> dict:
        sections = _collect_report_sections(context)
        data_block = "\n\n".join(sections).strip() or "No meaningful context data was available."

        # Generate title dynamically based ONLY on context keys (not user instruction)
        keys_summary = ", ".join(k for k in context if context.get(k) not in (None, "", [], {}))
        title_prompt = f"User Request: {instruction}\nAvailable content categories: {keys_summary}"
        title = (
            await ask_llm(TITLE_GENERATION_SYSTEM, title_prompt, max_tokens=25)
        ).strip().strip("\"'.") or "Generated Report"

        llm = AsyncGroq(api_key=settings.groq_api_key)
        response = await llm.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": REPORT_WRITER_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"User request:\n{instruction}\n\n"
                        f"Report title:\n{title}\n\n"
                        f"Available context:\n{data_block}\n\n"
                        "Write the complete Markdown report now."
                    ),
                },
            ],
            max_tokens=1200,
            temperature=0.2,
        )
        report = (
            response.choices[0].message.content
            or f"# {title}\n\nNo report content generated."
        )
        logger.info("ReportAgent: '%s' — %d chars", title, len(report))
        return {"report_markdown": report, "report_title": title}


app = ReportAgent().build_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)