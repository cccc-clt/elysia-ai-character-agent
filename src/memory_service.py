"""Long-term memory and chat persistence — SQLite primary, JSON fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.database import MEMORY_TYPES, Database
from src.llm_client import LLMClient


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


TYPE_TO_LIST = {
    "preference": "preferences",
    "nickname": "nicknames",
    "important_event": "important_events",
    "emotional_state": "emotional_states",
    "relationship": "relationships",
    "summary": "summary",
}


@dataclass
class MemoryStore:
    preferences: list[str] = field(default_factory=list)
    nicknames: list[str] = field(default_factory=list)
    important_events: list[str] = field(default_factory=list)
    emotional_states: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    summary: str = ""
    turn_count: int = 0
    last_summarized_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferences": self.preferences,
            "nicknames": self.nicknames,
            "important_events": self.important_events,
            "emotional_states": self.emotional_states,
            "relationships": self.relationships,
            "summary": self.summary,
            "turn_count": self.turn_count,
            "last_summarized_at": self.last_summarized_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryStore:
        return cls(
            preferences=list(data.get("preferences", [])),
            nicknames=list(data.get("nicknames", [])),
            important_events=list(data.get("important_events", [])),
            emotional_states=list(data.get("emotional_states", [])),
            relationships=list(data.get("relationships", [])),
            summary=str(data.get("summary", "")),
            turn_count=int(data.get("turn_count", 0)),
            last_summarized_at=str(data.get("last_summarized_at", "")),
        )

    def to_display_text(self) -> str:
        parts: list[str] = []
        if self.summary:
            parts.append(f"【记忆摘要】\n{self.summary}")
        if self.preferences:
            parts.append("【用户偏好】\n" + "\n".join(f"- {p}" for p in self.preferences))
        if self.nicknames:
            parts.append("【用户称呼】\n" + "\n".join(f"- {n}" for n in self.nicknames))
        if self.important_events:
            parts.append("【重要事件】\n" + "\n".join(f"- {e}" for e in self.important_events))
        if self.emotional_states:
            parts.append("【情绪状态】\n" + "\n".join(f"- {s}" for s in self.emotional_states))
        if self.relationships:
            parts.append("【关系变化】\n" + "\n".join(f"- {r}" for r in self.relationships))
        return "\n\n".join(parts) if parts else "（暂无长期记忆）"

    def clear(self) -> None:
        self.preferences.clear()
        self.nicknames.clear()
        self.important_events.clear()
        self.emotional_states.clear()
        self.relationships.clear()
        self.summary = ""
        self.turn_count = 0
        self.last_summarized_at = ""


@dataclass(frozen=True)
class PromptMemoryContext:
    long_term_memory: str
    excluded_message_ids: frozenset[int] = frozenset()
    excluded_profile_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DeleteMemoryResult:
    memory_id: int
    status: str
    previous_status: str | None
    affected_rows: int
    scope: str
    excluded_message_ids: tuple[int, ...] = ()
    excluded_profile_fields: tuple[str, ...] = ()


def _parse_json_ints(raw: Any) -> tuple[int, ...]:
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
        return tuple(int(value) for value in values or [])
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()


def _parse_json_strings(raw: Any) -> tuple[str, ...]:
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
        return tuple(str(value) for value in values or [])
    except (TypeError, json.JSONDecodeError):
        return ()


class MemoryService:
    def __init__(self, config: AppConfig, db: Database | None = None) -> None:
        self.config = config
        self.memory_path = config.storage.memory_store_path
        self.chat_logs_path = config.storage.chat_logs_path
        self.session_id = config.session_id
        self._db = db
        self._use_sqlite = config.storage.backend == "sqlite" and db is not None
        self._json_fallback = False
        self.memory = MemoryStore()
        self.chat_logs: list[dict[str, Any]] = []

        if self._use_sqlite and db is not None:
            try:
                db.init_schema()
                db.migrate_from_json(self.memory_path, self.chat_logs_path)
                self._sync_memory_from_db()
                self._load_turn_from_settings()
            except Exception:
                self._use_sqlite = False
                self._json_fallback = True

        if not self._use_sqlite:
            self.memory = self._load_memory_json()
            self.chat_logs = self._load_chat_logs_json()

    def _sync_memory_from_db(self) -> None:
        if not self._db:
            return
        store = MemoryStore()
        for row in self._db.list_memories():
            mtype = row["memory_type"]
            content = row["content"]
            attr = TYPE_TO_LIST.get(mtype)
            if mtype == "summary":
                store.summary = content
            elif attr and hasattr(store, attr):
                getattr(store, attr).append(content)
        self.memory = store

    def _load_turn_from_settings(self) -> None:
        if not self._db:
            return
        try:
            self.memory.turn_count = int(self._db.get_setting("turn_count", "0"))
            self.memory.last_summarized_at = self._db.get_setting("last_summarized_at", "")
        except ValueError:
            pass

    def _save_turn_settings(self) -> None:
        if self._db:
            self._db.set_setting("turn_count", str(self.memory.turn_count))
            self._db.set_setting("last_summarized_at", self.memory.last_summarized_at)

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_memory_json(self) -> MemoryStore:
        raw = self._load_json(self.memory_path, {})
        return MemoryStore.from_dict(raw) if raw else MemoryStore()

    def _load_chat_logs_json(self) -> list[dict[str, Any]]:
        raw = self._load_json(self.chat_logs_path, [])
        return raw if isinstance(raw, list) else []

    def _persist_memory_json(self) -> None:
        self._save_json(self.memory_path, self.memory.to_dict())

    def _upsert_memory_item(self, memory_type: str, content: str, importance: int = 3) -> None:
        content = content.strip()
        if not content:
            return
        if self._use_sqlite and self._db:
            self._db.upsert_memory(memory_type, content, importance)
            self._sync_memory_from_db()
        else:
            mapping = {
                "preference": self.memory.preferences,
                "nickname": self.memory.nicknames,
                "important_event": self.memory.important_events,
                "emotional_state": self.memory.emotional_states,
                "relationship": self.memory.relationships,
            }
            if memory_type == "summary":
                self.memory.summary = content
            elif memory_type in mapping:
                lst = mapping[memory_type]
                if content not in lst:
                    lst.append(content)
                while len(lst) > 30:
                    lst.pop(0)
            self._persist_memory_json()

    def save_memory(self) -> None:
        if self._use_sqlite:
            self._save_turn_settings()
        else:
            self._persist_memory_json()

    def get_long_term_memory_text(self) -> str:
        if self._use_sqlite and self._db:
            self._sync_memory_from_db()
        return self.memory.to_display_text()

    def get_prompt_memory_context(self) -> PromptMemoryContext:
        exclusions: dict[str, set[Any]] = {
            "message_ids": set(),
            "profile_fields": set(),
        }
        if self._use_sqlite and self._db:
            exclusions = self._db.get_deleted_prompt_exclusions()
        return PromptMemoryContext(
            long_term_memory=self.get_long_term_memory_text(),
            excluded_message_ids=frozenset(
                int(value) for value in exclusions["message_ids"]
            ),
            excluded_profile_fields=frozenset(
                str(value) for value in exclusions["profile_fields"]
            ),
        )

    def has_substantive_memory(self) -> bool:
        m = self.memory
        return bool(
            m.summary
            or m.preferences
            or m.nicknames
            or m.important_events
            or m.emotional_states
        )

    def append_chat(
        self,
        role: str,
        content: str,
        character_name: str = "",
        **voice_fields: Any,
    ) -> int | None:
        if self._use_sqlite and self._db:
            return self._db.insert_conversation(
                role, content, character_name, self.session_id, **voice_fields
            )
        self.chat_logs.append(
            {
                "role": role,
                "content": content,
                "character": character_name,
                "timestamp": _utc_now(),
            }
        )
        self._save_json(self.chat_logs_path, self.chat_logs)
        return None

    def get_session_messages(self) -> list[dict[str, str]]:
        if self._use_sqlite and self._db:
            return self._db.list_conversations(self.session_id)
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self.chat_logs
            if m.get("role") in ("user", "assistant")
        ]

    def get_session_messages_with_ids(self) -> list[dict[str, Any]]:
        if self._use_sqlite and self._db:
            return self._db.list_conversations_with_ids(self.session_id)
        out: list[dict[str, Any]] = []
        for i, m in enumerate(self.chat_logs):
            if m.get("role") in ("user", "assistant"):
                out.append({"id": i, "role": m["role"], "content": m["content"]})
        return out

    def clear_session_chat(self) -> None:
        if self._use_sqlite and self._db:
            self._db.clear_conversations(self.session_id)
        else:
            self.chat_logs = []
            self._save_json(self.chat_logs_path, [])

    def clear_memory(self) -> None:
        self.memory.clear()
        if self._use_sqlite and self._db:
            self._db.clear_memories()
            self._save_turn_settings()
        else:
            self._persist_memory_json()

    def increment_turn(self) -> int:
        self.memory.turn_count += 1
        self.save_memory()
        return self.memory.turn_count

    def should_summarize(self, interval: int) -> bool:
        if interval <= 0:
            return False
        return self.memory.turn_count > 0 and self.memory.turn_count % interval == 0

    def list_pending(self) -> list[dict[str, Any]]:
        if self._use_sqlite and self._db:
            return self._db.list_pending_memories()
        return []

    def list_confirmed_memories(self) -> list[dict[str, Any]]:
        if self._use_sqlite and self._db:
            return self._db.list_memories()
        return []

    def confirm_pending(self, pending_id: int) -> bool:
        if self._use_sqlite and self._db:
            ok = self._db.confirm_pending_memory(pending_id)
            self._sync_memory_from_db()
            return ok
        return False

    def reject_pending(self, pending_id: int) -> bool:
        if self._use_sqlite and self._db:
            return self._db.reject_pending_memory(pending_id)
        return False

    def edit_and_confirm(self, pending_id: int, new_content: str) -> bool:
        if self._use_sqlite and self._db:
            if not self._db.update_pending_content(pending_id, new_content):
                return False
            return self.confirm_pending(pending_id)
        return False

    def delete_memory_by_id(
        self, memory_id: int, scope: str = "all_prompt_sources"
    ) -> DeleteMemoryResult:
        if self._use_sqlite and self._db:
            raw = self._db.delete_memory(memory_id, scope)
            self._sync_memory_from_db()
            return DeleteMemoryResult(
                memory_id=memory_id,
                status=str(raw["status"]),
                previous_status=raw.get("previous_status"),
                affected_rows=int(raw["affected_rows"]),
                scope=str(raw["scope"]),
                excluded_message_ids=_parse_json_ints(raw.get("source_message_ids")),
                excluded_profile_fields=_parse_json_strings(
                    raw.get("source_profile_fields")
                ),
            )
        return DeleteMemoryResult(
            memory_id=memory_id,
            status="unsupported",
            previous_status=None,
            affected_rows=0,
            scope=scope,
        )

    def add_manual_pending(self, content: str, memory_type: str = "important_event") -> int | None:
        if self._use_sqlite and self._db:
            return self._db.insert_pending_memory(memory_type, content, 4, source="manual")
        return None

    def summarize_memory(
        self,
        llm: LLMClient,
        recent_messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> str:
        recent = recent_messages[-12:]
        history_text = "\n".join(
            f"{'玩家' if m['role'] == 'user' else '角色'}：{m['content']}"
            for m in recent
        )
        valid_source_ids = {
            int(m["id"])
            for m in recent
            if m.get("role") == "user" and isinstance(m.get("id"), int)
        }
        existing = self.memory.to_display_text()

        system = (
            "你是记忆整理助手。根据对话提取长期记忆，输出 JSON。"
            "规则：不记录无价值闲聊；不记录身份证/密码/地址等敏感信息；不编造用户信息。"
            "字段：items 数组，每项含 type(preference|nickname|important_event|emotional_state|relationship|summary)、"
            "content(字符串)、importance(1-5整数)。"
            "另含 summary 字符串(200字内，可选)。"
            "只提取对话中明确出现的信息。"
        )
        system += (
            "每个 item 必须包含 source_message_ids 数组，只能填写 recent_messages 中"
            "直接支持该记忆的用户消息 id。"
        )
        user_msg = json.dumps(
            {
                "existing_memory": existing,
                "recent_conversation": history_text,
                "recent_messages": [
                    {
                        "id": m.get("id"),
                        "role": m.get("role"),
                        "content": m.get("content", ""),
                    }
                    for m in recent
                ],
            },
            ensure_ascii=False,
        )

        try:
            raw = llm.chat_json(system, user_msg, model=model)
            data = json.loads(raw)
        except Exception:
            data = {}

        pending_count = 0
        items = data.get("items", [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                mtype = str(item.get("type", "")).strip()
                content = str(item.get("content", "")).strip()
                if mtype not in MEMORY_TYPES or not content:
                    continue
                try:
                    imp = max(1, min(5, int(item.get("importance", 3))))
                except (TypeError, ValueError):
                    imp = 3
                requested_ids = _parse_json_ints(item.get("source_message_ids", []))
                source_ids = [
                    value for value in requested_ids if value in valid_source_ids
                ]
                if valid_source_ids and not source_ids:
                    continue
                if self._use_sqlite and self._db:
                    self._db.insert_pending_memory(
                        mtype,
                        content,
                        imp,
                        "auto",
                        source_message_ids=source_ids,
                    )
                    pending_count += 1

        if data.get("summary"):
            summary = str(data["summary"]).strip()
            if summary and self._use_sqlite and self._db:
                self._db.insert_pending_memory(
                    "summary",
                    summary,
                    4,
                    "auto",
                    source_message_ids=sorted(valid_source_ids),
                )
                pending_count += 1

        self.memory.last_summarized_at = _utc_now()
        self.save_memory()
        if pending_count:
            return f"已整理 {pending_count} 条待确认记忆，请到「记忆」页确认。"
        if not self._use_sqlite:
            return "当前 JSON 存储后端不支持候选记忆确认，本次未写入长期记忆。"
        return self.get_long_term_memory_text()

    @property
    def using_sqlite(self) -> bool:
        return self._use_sqlite

    @property
    def json_fallback(self) -> bool:
        return self._json_fallback
