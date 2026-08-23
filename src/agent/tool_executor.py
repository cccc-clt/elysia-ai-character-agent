"""Execute registered tools with per-tool error isolation."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tool_registry import ToolRegistry
from src.agent.tool_types import ToolError, ToolResult


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, tool_name: str, arguments: str | dict[str, Any]) -> ToolResult:
        tool = self._registry.get(tool_name)
        if tool is None:
            return ToolResult(
                ok=False,
                tool=tool_name,
                summary=f"unknown tool: {tool_name}",
                data=None,
                evidence=[],
                error=ToolError(type="unknown_tool", message=f"Tool not found: {tool_name}"),
            )

        parsed_args: dict[str, Any]
        if isinstance(arguments, str):
            try:
                parsed_args = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as exc:
                return ToolResult(
                    ok=False,
                    tool=tool_name,
                    summary="invalid tool arguments JSON",
                    data=None,
                    evidence=[],
                    error=ToolError(
                        type="invalid_arguments",
                        message=str(exc),
                    ),
                )
        else:
            parsed_args = arguments

        if not isinstance(parsed_args, dict):
            return ToolResult(
                ok=False,
                tool=tool_name,
                summary="tool arguments must be a JSON object",
                data=None,
                evidence=[],
                error=ToolError(
                    type="invalid_arguments",
                    message="arguments must be an object",
                ),
            )

        try:
            return tool.handler(parsed_args)
        except Exception as exc:  # noqa: BLE001 — isolate per-tool failures
            return ToolResult(
                ok=False,
                tool=tool_name,
                summary=f"tool handler failed: {type(exc).__name__}",
                data=None,
                evidence=[],
                error=ToolError(type=type(exc).__name__, message=str(exc)),
            )
