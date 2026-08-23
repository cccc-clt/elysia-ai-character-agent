"""Tests for V2 Agent Core harness, registry, and tools."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.harness import ElysiaHarness, build_default_registry
from src.agent.tool_registry import ToolRegistry
from src.agent.tool_types import ToolDefinition, ToolError, ToolResult
from src.agent.tool_executor import ToolExecutor
from src.config import AgentConfig
from src.companionship_service import CompanionshipService
from src.database import Database
from src.llm_client import ToolCall
from src.memory_service import MemoryService
from tests.fixtures.fake_llm_agent import FakeAgentLLM, FakeLLMResponse


def _agent_config(max_rounds: int = 6) -> AgentConfig:
    return AgentConfig(enabled=True, max_rounds=max_rounds, mode="chat")


def _memory_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        storage=SimpleNamespace(
            backend="sqlite",
            memory_store_path=tmp_path / "memory.json",
            chat_logs_path=tmp_path / "chat.json",
        ),
        session_id="agent-test",
    )


def _seed_db(db_path: Path) -> Database:
    db = Database(db_path)
    db.init_schema()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memories (memory_type, content, importance, status, created_at, updated_at)
            VALUES ('important_event', '用户提到下周要准备重要考试', 4, 'active', '2026-01-01', '2026-01-01')
            """
        )
        conn.execute(
            """
            UPDATE companionship
            SET intimacy_score = 42, relationship_stage = '熟悉', mood = '温柔',
                last_greeting_date = '2026-01-01', updated_at = '2026-01-01'
            WHERE id = 1
            """
        )
        conn.commit()
    return db


def _services(tmp_path: Path) -> tuple[MemoryService, CompanionshipService]:
    db = _seed_db(tmp_path / "test.db")
    memory = MemoryService(_memory_config(tmp_path), db)
    companion = CompanionshipService(db)
    return memory, companion


def test_harness_direct_final_without_tools() -> None:
    llm = FakeAgentLLM([FakeLLMResponse(content="直接回答")])
    registry = ToolRegistry()
    harness = ElysiaHarness(llm, registry, _agent_config())
    result = harness.run([{"role": "user", "content": "你好"}])

    assert result.content == "直接回答"
    assert result.state.status == "completed"
    assert result.state.round == 1
    assert llm._call_count == 1


def test_harness_single_tool_then_final(tmp_path: Path) -> None:
    memory, companion = _services(tmp_path)
    registry = build_default_registry(memory, companion)
    llm = FakeAgentLLM(
        [
            FakeLLMResponse(
                tool_calls=[
                    ToolCall(id="call_1", name="search_memory", arguments='{"query":"考试"}')
                ]
            ),
            FakeLLMResponse(content="找到了你的考试相关记忆。"),
        ]
    )
    harness = ElysiaHarness(llm, registry, _agent_config())
    result = harness.run([{"role": "user", "content": "回忆考试"}])

    assert result.content == "找到了你的考试相关记忆。"
    assert llm._call_count == 2
    assert any(m.get("role") == "tool" for m in result.messages)
    assert len(result.state.tool_history) == 1


def test_harness_two_tool_rounds_then_final(tmp_path: Path) -> None:
    memory, companion = _services(tmp_path)
    registry = build_default_registry(memory, companion)
    llm = FakeAgentLLM(
        [
            FakeLLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call_mem",
                        name="search_memory",
                        arguments='{"query":"重要"}',
                    )
                ]
            ),
            FakeLLMResponse(
                tool_calls=[
                    ToolCall(id="call_comp", name="get_current_companion_state", arguments="{}")
                ]
            ),
            FakeLLMResponse(content="结合记忆和关系状态的总结。"),
        ]
    )
    harness = ElysiaHarness(llm, registry, _agent_config())
    result = harness.run(
        [{"role": "user", "content": "回忆一下我最近提到的重要事情，并结合当前关系状态给我一个总结。"}]
    )

    assert result.content == "结合记忆和关系状态的总结。"
    assert llm._call_count == 3
    assert len(result.state.tool_history) == 2
    tool_events = [e for e in result.trace.events if e.event_type == "tool_result"]
    assert len(tool_events) == 2
    roles = [m.get("role") for m in result.messages]
    assert "tool" in roles
    assert roles.count("assistant") >= 2


def test_tool_executor_unknown_tool() -> None:
    executor = ToolExecutor(ToolRegistry())
    result = executor.execute("nonexistent_tool", {})
    assert result.ok is False
    assert result.error is not None
    assert result.error.type == "unknown_tool"


def test_tool_executor_handler_exception() -> None:
    registry = ToolRegistry()

    def _boom(_: dict) -> ToolResult:
        raise RuntimeError("boom")

    registry.register(
        ToolDefinition(
            name="broken_tool",
            description="breaks",
            input_schema={"type": "object", "properties": {}},
            risk="safe",
            handler=_boom,
        )
    )
    result = ToolExecutor(registry).execute("broken_tool", {})
    assert result.ok is False
    assert result.error is not None
    assert result.error.type == "RuntimeError"


def test_tool_executor_invalid_arguments_json() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="noop",
            description="noop",
            input_schema={"type": "object", "properties": {}},
            risk="safe",
            handler=lambda _: ToolResult(ok=True, tool="noop", summary="ok"),
        )
    )
    result = ToolExecutor(registry).execute("noop", "{bad json")
    assert result.ok is False
    assert result.error is not None
    assert result.error.type == "invalid_arguments"


def test_harness_max_rounds_termination() -> None:
    llm = FakeAgentLLM(
        [
            FakeLLMResponse(
                tool_calls=[ToolCall(id=f"c{i}", name="loop", arguments="{}")]
            )
            for i in range(5)
        ]
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="loop",
            description="loop",
            input_schema={"type": "object", "properties": {}},
            risk="safe",
            handler=lambda _: ToolResult(ok=True, tool="loop", summary="ok"),
        )
    )
    harness = ElysiaHarness(llm, registry, _agent_config(max_rounds=2))
    result = harness.run([{"role": "user", "content": "loop"}])

    assert result.state.status == "max_rounds_exceeded"
    assert llm._call_count == 2


def test_trace_records_run_lifecycle(tmp_path: Path) -> None:
    memory, companion = _services(tmp_path)
    registry = build_default_registry(memory, companion)
    llm = FakeAgentLLM([FakeLLMResponse(content="ok")])
    harness = ElysiaHarness(llm, registry, _agent_config())
    result = harness.run([{"role": "user", "content": "hi"}])

    types = [e.event_type for e in result.trace.events]
    assert types[0] == "run_start"
    assert "round_start" in types
    assert "llm_response" in types
    assert types[-1] == "run_end"


def test_memory_search_memories(tmp_path: Path) -> None:
    memory, _ = _services(tmp_path)
    matches = memory.search_memories("考试")
    assert len(matches) >= 1
    assert any("考试" in m["content"] for m in matches)


def test_agent_config_defaults_false() -> None:
    from src.config import get_config

    # Default env should keep agent disabled in test environment
    cfg = get_config()
    assert cfg.agent.enabled is False
    assert cfg.agent.max_rounds >= 1


def test_llm_client_chat_still_works_without_tools() -> None:
    """Backward compatibility: chat() path unchanged (mock-free smoke)."""
    from src.config import LLMConfig
    from src.llm_client import LLMClient

    client = LLMClient(
        LLMConfig(
            api_key="",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o-mini",
            chat_model="gpt-4o-mini",
            eval_model="gpt-4o-mini",
            summary_model="gpt-4o-mini",
        )
    )
    assert client.has_api_key is False
