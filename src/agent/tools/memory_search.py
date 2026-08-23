"""search_memory tool — read-only memory retrieval."""

from __future__ import annotations

from typing import Any

from src.agent.tool_types import ToolDefinition, ToolResult
from src.memory_service import MemoryService


def build_search_memory_tool(memory_service: MemoryService) -> ToolDefinition:
    def handler(arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolResult(
                ok=False,
                tool="search_memory",
                summary="query is required",
                data=None,
                evidence=[],
                error=ToolError(type="validation_error", message="query is required"),
            )
        limit = arguments.get("limit", 10)
        try:
            limit_int = max(1, min(50, int(limit)))
        except (TypeError, ValueError):
            limit_int = 10

        matches = memory_service.search_memories(query, limit=limit_int)
        return ToolResult(
            ok=True,
            tool="search_memory",
            summary=f"{len(matches)} memory entries matched",
            data={"query": query, "matches": matches},
            evidence=[],
            error=None,
        )

    return ToolDefinition(
        name="search_memory",
        description=(
            "Search confirmed long-term memories and memory summary fields "
            "for entries related to the query. Returns structured matches only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or phrase to search in memories",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches (1-50)",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["query"],
        },
        risk="read_only",
        handler=handler,
    )
