"""Agent run state for a single harness execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

AgentMode = Literal["chat", "work"]
AgentStatus = Literal[
    "running",
    "completed",
    "failed",
    "max_rounds_exceeded",
    "cancelled",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolHistoryEntry:
    round: int
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    error_type: str | None = None


@dataclass
class AgentRunState:
    run_id: str = field(default_factory=lambda: uuid4().hex)
    mode: AgentMode = "chat"
    status: AgentStatus = "running"
    round: int = 0
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None
    current_tool: str | None = None
    tool_history: list[ToolHistoryEntry] = field(default_factory=list)
    error: str | None = None
    final_content: str | None = None

    def mark_finished(self, status: AgentStatus, error: str | None = None) -> None:
        self.status = status
        self.finished_at = _utc_now()
        if error:
            self.error = error
