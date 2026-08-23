"""In-memory agent trace collector with optional logging."""

from __future__ import annotations

import logging
from typing import Any

from src.agent.events import TraceEvent

logger = logging.getLogger("elysia.agent")


class AgentTrace:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)
        logger.info(
            "agent_trace run_id=%s type=%s round=%s tool=%s ok=%s",
            event.run_id,
            event.event_type,
            event.round,
            event.tool_name,
            event.ok,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "events": [
                {
                    "event_type": e.event_type,
                    "round": e.round,
                    "timestamp": e.timestamp,
                    "tool_name": e.tool_name,
                    "tool_arguments": e.tool_arguments,
                    "response_type": e.response_type,
                    "ok": e.ok,
                    "summary": e.summary,
                    "latency_ms": e.latency_ms,
                    "error": e.error,
                    "details": e.details,
                }
                for e in self.events
            ],
        }
