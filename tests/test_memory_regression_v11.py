from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from src.character_profile import CharacterProfile
from src.database import Database
from src.memory_service import MemoryService
from src.prompt_builder import build_system_prompt


NICKNAME = "小岚"
NICKNAME_MEMORY = f"用户希望被称呼为：{NICKNAME}"
STUDY_MEMORY = "用户喜欢晚上学习"


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        storage=SimpleNamespace(
            backend="sqlite",
            memory_store_path=tmp_path / "memory.json",
            chat_logs_path=tmp_path / "chat.json",
        ),
        session_id="memory-regression-v11",
    )


def _service(tmp_path: Path) -> tuple[Database, MemoryService]:
    db = Database(tmp_path / "memory-regression-v11.db")
    db.init_schema()
    return db, MemoryService(_config(tmp_path), db)


class _FakeMemoryExtractionLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.last_system = ""
        self.last_user = ""

    def chat_json(self, system: str, user: str, model: str | None = None) -> str:
        self.last_system = system
        self.last_user = user
        return json.dumps(self.payload, ensure_ascii=False)


def _character() -> CharacterProfile:
    return CharacterProfile(
        name="测试角色",
        role="陪伴角色",
        personality="温柔、尊重",
        speaking_style="自然、简洁",
        relationship="初识",
        forbidden="不得编造记忆",
        opening_message="你好",
    )


def _build_prompt(
    service: MemoryService,
    *,
    chat_history: list[dict] | None = None,
    user_input: str = "你还记得我的偏好吗？",
) -> str:
    context = service.get_prompt_memory_context()
    return build_system_prompt(
        character=_character(),
        long_term_memory=context.long_term_memory,
        chat_history=chat_history or [],
        user_input=user_input,
        excluded_message_ids=context.excluded_message_ids,
    )


def _create_pending_nickname(
    db: Database, source_message_id: int = 101
) -> int:
    return db.insert_pending_memory(
        "nickname",
        NICKNAME_MEMORY,
        importance=4,
        source="regression-test",
        source_message_ids=[source_message_id],
    )


def _mem_reg_001(tmp_path: Path) -> None:
    """MEM-REG-001: candidate is transient; valid candidates persist as pending."""
    db, service = _service(tmp_path)
    candidate_payload = {
        "items": [
            {
                "type": "nickname",
                "content": NICKNAME_MEMORY,
                "importance": 4,
                "source_message_ids": [101],
            }
        ]
    }
    llm = _FakeMemoryExtractionLLM(candidate_payload)

    service.summarize_memory(
        llm,
        [{"id": 101, "role": "user", "content": f"以后叫我{NICKNAME}"}],
    )

    extraction_request = json.loads(llm.last_user)
    pending = db.list_pending_memories()
    assert f"以后叫我{NICKNAME}" in extraction_request["recent_conversation"], (
        "MEM-REG-001: 用户偏好没有进入memory extraction请求"
    )
    assert candidate_payload["items"], "MEM-REG-001: 提取器没有产生candidate"
    assert len(pending) == 1, "MEM-REG-001: candidate没有进入pending候选流程"
    assert pending[0]["status"] == "pending", (
        "MEM-REG-001: 合法candidate持久化后状态不是pending"
    )
    assert NICKNAME in pending[0]["content"], (
        "MEM-REG-001: 候选记忆没有保留用户称呼"
    )


def _mem_reg_002(tmp_path: Path) -> None:
    """MEM-REG-002: confirming pending memory creates one active memory."""
    db, service = _service(tmp_path)
    pending_id = _create_pending_nickname(db)

    confirmed = service.confirm_pending(pending_id)
    active = db.list_memories()

    assert confirmed is True, "MEM-REG-002: confirm操作返回失败"
    assert db.get_pending_memory(pending_id)["status"] == "confirmed", (
        "MEM-REG-002: pending记录没有更新为confirmed"
    )
    assert len(active) == 1, "MEM-REG-002: confirm后没有写入长期记忆"
    assert active[0]["status"] == "active", (
        "MEM-REG-002: confirm后长期记忆状态不是active"
    )


def _mem_reg_003(tmp_path: Path) -> None:
    """MEM-REG-003: active memory is admitted to the generated prompt."""
    db, service = _service(tmp_path)
    pending_id = _create_pending_nickname(db)
    assert service.confirm_pending(pending_id) is True, (
        "MEM-REG-003: 测试前置confirm失败"
    )

    prompt = _build_prompt(service)

    assert NICKNAME in prompt, "MEM-REG-003: active记忆没有进入Prompt"


def _mem_reg_004(tmp_path: Path) -> None:
    """MEM-REG-004: rejected pending memory is isolated from the prompt."""
    db, service = _service(tmp_path)
    pending_id = db.insert_pending_memory(
        "preference",
        STUDY_MEMORY,
        importance=3,
        source="regression-test",
        source_message_ids=[201],
    )

    rejected = service.reject_pending(pending_id)
    prompt = _build_prompt(service, user_input="请给我一个学习安排建议。")

    assert rejected is True, "MEM-REG-004: reject操作返回失败"
    assert db.get_pending_memory(pending_id)["status"] == "rejected", (
        "MEM-REG-004: 候选状态没有更新为rejected"
    )
    assert db.list_memories() == [], (
        "MEM-REG-004: rejected候选错误写入了active长期记忆"
    )
    assert STUDY_MEMORY not in prompt, (
        "MEM-REG-004: rejected记忆仍进入了Prompt"
    )


def _mem_reg_005(tmp_path: Path) -> None:
    """MEM-REG-005: deleted memory and its source no longer enter the prompt."""
    db, service = _service(tmp_path)
    source_user_id = service.append_chat("user", f"以后叫我{NICKNAME}")
    service.append_chat("assistant", f"好的，{NICKNAME}")
    assert source_user_id is not None, "MEM-REG-005: 无法创建来源消息"
    pending_id = _create_pending_nickname(db, source_user_id)
    assert service.confirm_pending(pending_id) is True, (
        "MEM-REG-005: 测试前置confirm失败"
    )
    active = db.list_memories()
    assert len(active) == 1, "MEM-REG-005: 测试前置active记忆不存在"
    assert NICKNAME in _build_prompt(service), (
        "MEM-REG-005: 删除前active记忆没有进入Prompt"
    )

    delete_result = service.delete_memory_by_id(
        int(active[0]["id"]), scope="all_prompt_sources"
    )
    prompt_after_delete = _build_prompt(
        service,
        chat_history=service.get_session_messages_with_ids(),
        user_input="你还记得应该怎么称呼我吗？",
    )
    audit_row = db.get_memory(int(active[0]["id"]))

    assert delete_result.status == "deleted", (
        "MEM-REG-005: delete没有返回deleted状态"
    )
    assert delete_result.affected_rows == 1, (
        "MEM-REG-005: delete没有实际更新数据库记录"
    )
    assert audit_row is not None and audit_row["status"] == "deleted", (
        "MEM-REG-005: 数据库状态没有更新为deleted"
    )
    assert db.list_memories() == [], (
        "MEM-REG-005: deleted记忆仍被active retrieval读取"
    )
    assert NICKNAME not in prompt_after_delete, (
        "MEM-REG-005: 删除后Prompt仍包含小岚，BC-004回归失败"
    )


REGRESSION_CASES: dict[str, Callable[[Path], None]] = {
    "MEM-REG-001": _mem_reg_001,
    "MEM-REG-002": _mem_reg_002,
    "MEM-REG-003": _mem_reg_003,
    "MEM-REG-004": _mem_reg_004,
    "MEM-REG-005": _mem_reg_005,
}


@pytest.mark.parametrize(
    "case_id",
    list(REGRESSION_CASES),
    ids=list(REGRESSION_CASES),
)
def test_memory_regression_v11(case_id: str, tmp_path: Path) -> None:
    """Run one named V1.1 memory regression case with isolated storage."""
    REGRESSION_CASES[case_id](tmp_path)
