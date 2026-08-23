"""Deterministic fake LLM for agent harness tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.llm_client import ChatResponse, ToolCall


@dataclass
class FakeLLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class FakeAgentLLM:
    """Queue-based LLM that returns preset ChatResponse objects."""

    def __init__(self, responses: list[FakeLLMResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.last_messages: list[dict[str, Any]] | None = None
        self.last_tools: list[dict[str, Any]] | None = None

    def chat_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        self.last_messages = messages
        self.last_tools = tools
        if self._call_count >= len(self._responses):
            return ChatResponse(content="fallback final", tool_calls=[])
        item = self._responses[self._call_count]
        self._call_count += 1
        return ChatResponse(content=item.content, tool_calls=list(item.tool_calls))
