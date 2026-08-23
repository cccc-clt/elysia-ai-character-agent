"""Elysia agent runtime — multi-round tool loop harness."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from src.agent.events import TraceEvent
from src.agent.state import AgentRunState, ToolHistoryEntry
from src.agent.tool_executor import ToolExecutor
from src.agent.tool_registry import ToolRegistry
from src.agent.trace import AgentTrace
from src.config import AgentConfig
from src.llm_client import ChatResponse


class ChatMessagesClient(Protocol):
    def chat_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse: ...


@dataclass
class HarnessResult:
    content: str
    state: AgentRunState
    trace: AgentTrace
    messages: list[dict[str, Any]]


class ElysiaHarness:
    """Run OpenAI-compatible function-calling agent loop with tool observations."""

    def __init__(
        self,
        llm: ChatMessagesClient,
        registry: ToolRegistry,
        config: AgentConfig,
        *,
        model: str | None = None,
    ) -> None:
        self._llm = llm
        self._executor = ToolExecutor(registry)
        self._registry = registry
        self._config = config
        self._model = model

    def run(
        self,
        messages: list[dict[str, Any]],
        *,
        mode: str = "chat",
    ) -> HarnessResult:
        state = AgentRunState(mode=mode if mode in ("chat", "work") else "chat")
        trace = AgentTrace(state.run_id)
        working_messages = list(messages)

        trace.record(
            TraceEvent(
                run_id=state.run_id,
                event_type="run_start",
                round=0,
                details={"mode": state.mode, "max_rounds": self._config.max_rounds},
            )
        )

        final_content: str | None = None

        try:
            while state.round < self._config.max_rounds:
                state.round += 1
                trace.record(
                    TraceEvent(
                        run_id=state.run_id,
                        event_type="round_start",
                        round=state.round,
                    )
                )

                start = time.perf_counter()
                response = self._llm.chat_messages(
                    working_messages,
                    tools=self._registry.openai_tools(),
                    model=self._model,
                )
                latency_ms = (time.perf_counter() - start) * 1000

                if response.has_tool_calls:
                    assistant_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": call.arguments,
                                },
                            }
                            for call in response.tool_calls
                        ],
                    }
                    working_messages.append(assistant_message)

                    trace.record(
                        TraceEvent(
                            run_id=state.run_id,
                            event_type="llm_response",
                            round=state.round,
                            response_type="tool_calls",
                            latency_ms=latency_ms,
                            details={"tool_call_count": len(response.tool_calls)},
                        )
                    )

                    for call in response.tool_calls:
                        state.current_tool = call.name
                        parsed_args = _parse_arguments(call.arguments)
                        trace.record(
                            TraceEvent(
                                run_id=state.run_id,
                                event_type="tool_call",
                                round=state.round,
                                tool_name=call.name,
                                tool_arguments=parsed_args,
                            )
                        )

                        tool_start = time.perf_counter()
                        result = self._executor.execute(call.name, call.arguments)
                        tool_latency = (time.perf_counter() - tool_start) * 1000

                        state.tool_history.append(
                            ToolHistoryEntry(
                                round=state.round,
                                tool=call.name,
                                arguments=parsed_args,
                                ok=result.ok,
                                summary=result.summary,
                                error_type=result.error.type if result.error else None,
                            )
                        )

                        trace.record(
                            TraceEvent(
                                run_id=state.run_id,
                                event_type="tool_result",
                                round=state.round,
                                tool_name=call.name,
                                ok=result.ok,
                                summary=result.summary,
                                latency_ms=tool_latency,
                                error=result.error.message if result.error else None,
                            )
                        )

                        working_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": result.to_observation_text(),
                            }
                        )

                    state.current_tool = None
                    continue

                final_content = (response.content or "").strip()
                trace.record(
                    TraceEvent(
                        run_id=state.run_id,
                        event_type="llm_response",
                        round=state.round,
                        response_type="final",
                        latency_ms=latency_ms,
                        summary=final_content[:120] if final_content else "",
                    )
                )
                state.final_content = final_content
                state.mark_finished("completed")
                break

            if final_content is None:
                state.mark_finished(
                    "max_rounds_exceeded",
                    error=f"exceeded max_rounds={self._config.max_rounds}",
                )
                final_content = (
                    "抱歉，我这边处理步骤有点多，还没整理完。"
                    "你可以换个更具体的问题，我再试试哦～"
                )

        except Exception as exc:
            state.mark_finished("failed", error=str(exc))
            trace.record(
                TraceEvent(
                    run_id=state.run_id,
                    event_type="error",
                    round=state.round,
                    error=str(exc),
                )
            )
            final_content = final_content or "抱歉，我这边暂时出了点小状况，稍后再聊好吗？"

        trace.record(
            TraceEvent(
                run_id=state.run_id,
                event_type="run_end",
                round=state.round,
                details={"status": state.status},
            )
        )

        return HarnessResult(
            content=final_content or "",
            state=state,
            trace=trace,
            messages=working_messages,
        )


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw.strip() else {}
        return parsed if isinstance(parsed, dict) else {"_raw": raw}
    except json.JSONDecodeError:
        return {"_raw": raw}


def build_default_registry(
    memory_service: Any,
    companionship_service: Any,
    memory_summary: str = "",
) -> ToolRegistry:
    from src.agent.tools.companion_state import build_companion_state_tool
    from src.agent.tools.memory_search import build_search_memory_tool

    registry = ToolRegistry()
    registry.register(build_search_memory_tool(memory_service))
    registry.register(
        build_companion_state_tool(companionship_service, memory_summary=memory_summary)
    )
    return registry
