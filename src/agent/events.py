"""Trace event types for agent observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

TraceEventType = Literal[
    "run_start",
    "round_start",
    "llm_response",
    "tool_call",
    "tool_result",
    "run_end",
    "error",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TraceEvent:
    run_id: str
    event_type: TraceEventType
    round: int
    timestamp: str = field(default_factory=_utc_now)
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    response_type: str | None = None
    ok: bool | None = None
    summary: str | None = None
    latency_ms: float | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
