from __future__ import annotations
from datetime import datetime
from typing import Any
from common.errors import MCPError
from common.models import Report, ReportSection

TOOL_NAME = "generate_report"
TOOL_DESCRIPTION = "Generate a structured markdown report from provided data sections."
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Report title"},
        "summary": {"type": "string", "description": "Executive summary paragraph"},
        "sections": {
            "type": "array",
            "description": "List of report sections",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["heading", "content"],
            },
        },
        "metadata": {
            "type": "object",
            "description": "Optional key-value metadata (author, topic, etc.)",
            "additionalProperties": True,
        },
    },
    "required": ["title", "summary", "sections"],
}

async def handle(
    title: str,
    summary: str,
    sections: list[dict],
    metadata: dict[str, Any] | None = None,
) -> Report:
    if not title or not title.strip():
        raise MCPError("Report title cannot be empty", tool=TOOL_NAME)

    if not sections:
        raise MCPError("Report must have at least one section", tool=TOOL_NAME)

    metadata = metadata or {}

    report_sections = []
    for section in sections:
        heading = section.get("heading", "").strip()
        content = section.get("content", "").strip()

        if not heading:
            raise MCPError("Each section must have a heading", tool=TOOL_NAME)

        report_sections.append(ReportSection(heading=heading, content=content))

    return Report(
        title=title,
        summary=summary,
        sections=report_sections,
        generated_at=datetime.utcnow(),
        metadata=metadata,
    )
