"""get_current_companion_state tool — read-only companionship snapshot."""

from __future__ import annotations

from typing import Any

from src.agent.tool_types import ToolDefinition, ToolResult
from src.companionship_service import CompanionshipService


def build_companion_state_tool(
    companionship_service: CompanionshipService,
    memory_summary: str = "",
) -> ToolDefinition:
    def handler(arguments: dict[str, Any]) -> ToolResult:
        state = companionship_service.load_state()
        summary = companionship_service.get_summary(memory_summary)
        data = {
            "relationship_stage": state.relationship_stage,
            "intimacy_score": state.intimacy_score,
            "mood": state.mood,
            "last_important_interaction": state.last_important_interaction,
            "daily_greeting": state.daily_greeting if state.show_greeting else "",
            "show_greeting": state.show_greeting,
            "summary": summary,
        }
        return ToolResult(
            ok=True,
            tool="get_current_companion_state",
            summary=(
                f"relationship={state.relationship_stage}, "
                f"intimacy={state.intimacy_score}, mood={state.mood}"
            ),
            data=data,
            evidence=[],
            error=None,
        )

    return ToolDefinition(
        name="get_current_companion_state",
        description=(
            "Return the current companionship state: relationship stage, "
            "intimacy score, mood, and related summary fields."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        risk="read_only",
        handler=handler,
    )
