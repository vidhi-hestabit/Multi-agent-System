from __future__ import annotations
from typing import Any, Callable, Awaitable
from dataclasses import dataclass, field

@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Awaitable[Any]]
    tags: list[str] = field(default_factory=list)

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
                "tags": t.tags,
            }
            for t in self._tools.values()
        ]

    def all_names(self) -> list[str]:
        return list(self._tools.keys())
