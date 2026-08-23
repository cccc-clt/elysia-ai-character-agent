"""Structured tool definitions and results for the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

ToolRisk = Literal["safe", "read_only", "write", "external"]


@dataclass(frozen=True)
class ToolError:
    type: str
    message: str


@dataclass
class ToolResult:
    ok: bool
    tool: str
    summary: str
    data: Any | None = None
    evidence: list[Any] = field(default_factory=list)
    error: ToolError | None = None

    def to_observation_text(self) -> str:
        """Serialize for LLM tool message content (objective, not persona)."""
        import json

        payload: dict[str, Any] = {
            "ok": self.ok,
            "tool": self.tool,
            "summary": self.summary,
            "data": self.data,
            "evidence": self.evidence,
        }
        if self.error is not None:
            payload["error"] = {"type": self.error.type, "message": self.error.message}
        return json.dumps(payload, ensure_ascii=False)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: ToolRisk
    handler: Callable[[dict[str, Any]], ToolResult]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
