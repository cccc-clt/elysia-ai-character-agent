from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.database import Database
from src.memory_service import MemoryService
from src.prompt_builder import format_chat_history
from src.user_profile_service import UserProfile


def _config(tmp_path: Path, backend: str = "sqlite") -> SimpleNamespace:
    return SimpleNamespace(
        storage=SimpleNamespace(
            backend=backend,
            memory_store_path=tmp_path / "memory.json",
            chat_logs_path=tmp_path / "chat.json",
        ),
        session_id="memory-regression",
    )


class _FakeMemoryLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat_json(self, system: str, user: str, model: str | None = None) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def test_v10_schema_migrates_existing_memory_to_active(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(memory_type, content)
            );
            CREATE TABLE pending_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT DEFAULT 'auto',
                created_at TEXT NOT NULL
            );
            INSERT INTO memories (
                memory_type, content, importance, created_at, updated_at
            ) VALUES ('nickname', '称呼小岚', 4, 'old', 'old');
            """
        )

    db = Database(db_path)
    db.init_schema()

    row = db.list_memories()[0]
    assert row["status"] == "active"
    assert row["source_message_ids"] == "[]"
    with sqlite3.connect(db_path) as conn:
        pending_columns = {
            item[1] for item in conn.execute("PRAGMA table_info(pending_memories)")
        }
    assert {"source_message_ids", "source_profile_fields", "updated_at"} <= pending_columns


def test_rejected_pending_memory_never_becomes_active(tmp_path: Path) -> None:
    db = Database(tmp_path / "reject.db")
    db.init_schema()
    pending_id = db.insert_pending_memory(
        "nickname", "称呼小羽", source_message_ids=[11]
    )

    assert db.reject_pending_memory(pending_id) is True
    assert db.reject_pending_memory(pending_id) is False
    assert db.get_pending_memory(pending_id)["status"] == "rejected"
    assert db.list_memories() == []


def test_confirm_is_atomic_and_carries_source_metadata(tmp_path: Path) -> None:
    db = Database(tmp_path / "confirm.db")
    db.init_schema()
    pending_id = db.insert_pending_memory(
        "preference",
        "喜欢简短回复",
        source_message_ids=[21],
        source_profile_fields=["reply_style"],
    )

    assert db.confirm_pending_memory(pending_id) is True
    assert db.confirm_pending_memory(pending_id) is False
    assert db.get_pending_memory(pending_id)["status"] == "confirmed"
    active = db.list_memories()
    assert len(active) == 1
    assert json.loads(active[0]["source_message_ids"]) == [21]
    assert json.loads(active[0]["source_profile_fields"]) == ["reply_style"]


def test_deleted_memory_requires_a_new_confirmation_to_reactivate(tmp_path: Path) -> None:
    db = Database(tmp_path / "reactivate.db")
    db.init_schema()
    memory_id = db.upsert_memory("nickname", "称呼小岚", source_message_ids=[31])
    assert memory_id is not None
    assert db.delete_memory(memory_id)["status"] == "deleted"

    db.upsert_memory("nickname", "称呼小岚", source_message_ids=[32])
    assert db.list_memories() == []

    pending_id = db.insert_pending_memory(
        "nickname", "称呼小岚", source_message_ids=[33]
    )
    assert db.confirm_pending_memory(pending_id) is True
    active = db.list_memories()
    assert len(active) == 1
    assert json.loads(active[0]["source_message_ids"]) == [33]


def test_memory_capacity_trim_uses_lifecycle_state(tmp_path: Path) -> None:
    db = Database(tmp_path / "trim.db")
    db.init_schema()
    for index in range(31):
        db.upsert_memory("preference", f"偏好-{index}", importance=3)

    assert len(db.list_memories()) == 30
    audit_rows = db.list_memories(include_deleted=True)
    deleted = [row for row in audit_rows if row["status"] == "deleted"]
    assert len(audit_rows) == 31
    assert len(deleted) == 1
    assert deleted[0]["delete_scope"] == "long_term_only"


def test_all_prompt_sources_delete_filters_memory_history_and_profile(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "delete.db")
    db.init_schema()
    memory_id = db.upsert_memory(
        "nickname",
        "称呼小岚",
        source_message_ids=[41],
        source_profile_fields=["display_name"],
    )
    service = MemoryService(_config(tmp_path), db)

    result = service.delete_memory_by_id(memory_id, scope="all_prompt_sources")
    assert result.status == "deleted"
    assert result.affected_rows == 1
    assert result.excluded_message_ids == (41,)
    assert result.excluded_profile_fields == ("display_name",)
    assert "称呼小岚" not in service.get_long_term_memory_text()

    context = service.get_prompt_memory_context()
    history = format_chat_history(
        [
            {"id": 41, "role": "user", "content": "请叫我小岚"},
            {"id": 42, "role": "assistant", "content": "好的，小岚"},
            {"id": 43, "role": "user", "content": "今天天气不错"},
        ],
        excluded_message_ids=context.excluded_message_ids,
    )
    profile = UserProfile("小岚", "日常聊天", "细腻", True, True)
    profile_text = profile.to_prompt_context(context.excluded_profile_fields)
    assert "小岚" not in history
    assert "小岚" not in profile_text
    assert "今天天气不错" in history

    repeated = service.delete_memory_by_id(memory_id)
    assert repeated.status == "already_deleted"
    assert repeated.affected_rows == 0
    missing = service.delete_memory_by_id(999999)
    assert missing.status == "not_found"


def test_long_term_only_delete_keeps_chat_source_visible(tmp_path: Path) -> None:
    db = Database(tmp_path / "long-term-only.db")
    db.init_schema()
    memory_id = db.upsert_memory(
        "preference", "喜欢夜间学习", source_message_ids=[51]
    )
    service = MemoryService(_config(tmp_path), db)

    result = service.delete_memory_by_id(memory_id, scope="long_term_only")
    context = service.get_prompt_memory_context()
    assert result.status == "deleted"
    assert context.excluded_message_ids == frozenset()
    assert "喜欢夜间学习" not in context.long_term_memory


def test_extraction_creates_pending_with_validated_source_ids(tmp_path: Path) -> None:
    db = Database(tmp_path / "extract.db")
    db.init_schema()
    service = MemoryService(_config(tmp_path), db)
    llm = _FakeMemoryLLM(
        {
            "items": [
                {
                    "type": "preference",
                    "content": "喜欢25分钟学习节奏",
                    "importance": 4,
                    "source_message_ids": [61, 999],
                }
            ]
        }
    )

    result = service.summarize_memory(
        llm,
        [
            {"id": 61, "role": "user", "content": "我喜欢25分钟一段地学习"},
            {"id": 62, "role": "assistant", "content": "这是很清晰的节奏"},
        ],
    )

    pending = db.list_pending_memories()
    assert "1 条待确认记忆" in result
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert json.loads(pending[0]["source_message_ids"]) == [61]
    assert db.list_memories() == []


def test_extraction_discards_candidate_without_a_valid_source_id(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "invalid-source.db")
    db.init_schema()
    service = MemoryService(_config(tmp_path), db)
    llm = _FakeMemoryLLM(
        {
            "items": [
                {
                    "type": "nickname",
                    "content": "称呼小岚",
                    "importance": 4,
                    "source_message_ids": [999],
                }
            ]
        }
    )

    service.summarize_memory(
        llm,
        [{"id": 81, "role": "user", "content": "以后可以叫我小岚"}],
    )

    assert db.list_pending_memories() == []
    assert db.list_memories() == []


def test_json_fallback_does_not_silently_promote_extracted_memory(
    tmp_path: Path,
) -> None:
    service = MemoryService(_config(tmp_path, backend="json"))
    llm = _FakeMemoryLLM(
        {
            "items": [
                {
                    "type": "preference",
                    "content": "喜欢简短回复",
                    "importance": 3,
                    "source_message_ids": [71],
                }
            ]
        }
    )

    result = service.summarize_memory(
        llm,
        [{"id": 71, "role": "user", "content": "我喜欢简短回复"}],
    )
    delete_result = service.delete_memory_by_id(1)

    assert "不支持候选记忆确认" in result
    assert service.memory.preferences == []
    assert delete_result.status == "unsupported"


def test_invalid_delete_scope_is_rejected(tmp_path: Path) -> None:
    db = Database(tmp_path / "invalid-scope.db")
    db.init_schema()
    memory_id = db.upsert_memory("summary", "测试摘要")
    with pytest.raises(ValueError, match="Unsupported delete scope"):
        db.delete_memory(memory_id, "everything")
