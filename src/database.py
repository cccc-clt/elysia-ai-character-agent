"""SQLite persistence for Elysia companion app."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


MEMORY_TYPES = (
    "preference",
    "nickname",
    "important_event",
    "emotional_state",
    "relationship",
    "summary",
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    character_name TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 3,
                    status TEXT NOT NULL DEFAULT 'active',
                    deleted_at TEXT,
                    delete_scope TEXT,
                    source_message_ids TEXT NOT NULL DEFAULT '[]',
                    source_profile_fields TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(memory_type, content)
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_input TEXT NOT NULL,
                    assistant_reply TEXT NOT NULL,
                    personality_score INTEGER NOT NULL,
                    tone_score INTEGER NOT NULL,
                    memory_usage_score INTEGER NOT NULL,
                    emotional_response_score INTEGER NOT NULL,
                    immersion_score INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS companionship (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    intimacy_score INTEGER NOT NULL DEFAULT 20,
                    relationship_stage TEXT NOT NULL DEFAULT '初识',
                    mood TEXT NOT NULL DEFAULT '温柔',
                    last_greeting_date TEXT DEFAULT '',
                    last_important_interaction TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(memory_type, updated_at);

                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    display_name TEXT DEFAULT '',
                    preferred_mode TEXT DEFAULT '日常聊天',
                    reply_style TEXT DEFAULT '细腻',
                    remember_prefs INTEGER DEFAULT 1,
                    onboarding_completed INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 3,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source TEXT DEFAULT 'auto',
                    source_message_ids TEXT NOT NULL DEFAULT '[]',
                    source_profile_fields TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_companion (
                    date TEXT PRIMARY KEY,
                    greeting TEXT NOT NULL,
                    little_note TEXT NOT NULL,
                    streak_days INTEGER NOT NULL DEFAULT 1,
                    last_visit_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS relationship_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    intimacy_at_unlock INTEGER DEFAULT 0,
                    unlocked_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS message_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER,
                    feedback_type TEXT NOT NULL,
                    user_input_snippet TEXT DEFAULT '',
                    reply_snippet TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_memories(status);
                CREATE INDEX IF NOT EXISTS idx_feedback_type ON message_feedback(feedback_type);

                CREATE TABLE IF NOT EXISTS voice_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    stt_provider TEXT DEFAULT '',
                    tts_provider TEXT DEFAULT '',
                    input_audio_path TEXT DEFAULT '',
                    output_audio_path TEXT DEFAULT '',
                    transcript TEXT DEFAULT '',
                    source_text TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'ok',
                    error_message TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_voice_logs_conv ON voice_logs(conversation_id);
                """
            )
            self._migrate_schema(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status, updated_at)"
            )
            row = conn.execute("SELECT id FROM companionship WHERE id = 1").fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO companionship (
                        id, intimacy_score, relationship_stage, mood,
                        last_greeting_date, last_important_interaction, updated_at
                    ) VALUES (1, 20, '初识', '温柔', '', '', ?)
                    """,
                    (_utc_now(),),
                )
            profile = conn.execute("SELECT id FROM user_profile WHERE id = 1").fetchone()
            if profile is None:
                conn.execute(
                    """
                    INSERT INTO user_profile (
                        id, display_name, preferred_mode, reply_style,
                        remember_prefs, onboarding_completed, updated_at
                    ) VALUES (1, '', '日常聊天', '细腻', 1, 0, ?)
                    """,
                    (_utc_now(),),
                )

    _CONV_VOICE_COLS = (
        ("input_audio_path", "TEXT DEFAULT ''"),
        ("output_audio_path", "TEXT DEFAULT ''"),
        ("message_type", "TEXT DEFAULT 'text'"),
        ("stt_text", "TEXT DEFAULT ''"),
        ("tts_provider", "TEXT DEFAULT ''"),
        ("stt_provider", "TEXT DEFAULT ''"),
    )

    _MEMORY_LIFECYCLE_COLS = (
        ("status", "TEXT NOT NULL DEFAULT 'active'"),
        ("deleted_at", "TEXT"),
        ("delete_scope", "TEXT"),
        ("source_message_ids", "TEXT NOT NULL DEFAULT '[]'"),
        ("source_profile_fields", "TEXT NOT NULL DEFAULT '[]'"),
    )

    _PENDING_SOURCE_COLS = (
        ("source_message_ids", "TEXT NOT NULL DEFAULT '[]'"),
        ("source_profile_fields", "TEXT NOT NULL DEFAULT '[]'"),
        ("updated_at", "TEXT"),
    )

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        conversation_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(conversations)").fetchall()
        }
        for col_name, col_def in self._CONV_VOICE_COLS:
            if col_name not in conversation_cols:
                conn.execute(f"ALTER TABLE conversations ADD COLUMN {col_name} {col_def}")

        memory_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        for col_name, col_def in self._MEMORY_LIFECYCLE_COLS:
            if col_name not in memory_cols:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")

        pending_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(pending_memories)").fetchall()
        }
        for col_name, col_def in self._PENDING_SOURCE_COLS:
            if col_name not in pending_cols:
                conn.execute(
                    f"ALTER TABLE pending_memories ADD COLUMN {col_name} {col_def}"
                )

        conn.execute(
            "UPDATE memories SET status = 'active' WHERE status IS NULL OR status = ''"
        )

    @staticmethod
    def _json_list(values: list[int] | list[str] | None) -> str:
        return json.dumps(values or [], ensure_ascii=False)

    def insert_conversation(
        self,
        role: str,
        content: str,
        character_name: str = "",
        session_id: str = "default",
        *,
        input_audio_path: str = "",
        output_audio_path: str = "",
        message_type: str = "text",
        stt_text: str = "",
        tts_provider: str = "",
        stt_provider: str = "",
    ) -> int:
        now = _utc_now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO conversations (
                    session_id, role, content, character_name, created_at,
                    input_audio_path, output_audio_path, message_type,
                    stt_text, tts_provider, stt_provider
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    character_name,
                    now,
                    input_audio_path,
                    output_audio_path,
                    message_type,
                    stt_text,
                    tts_provider,
                    stt_provider,
                ),
            )
            return int(cur.lastrowid or 0)

    def update_conversation_voice(
        self,
        conv_id: int,
        *,
        output_audio_path: str | None = None,
        input_audio_path: str | None = None,
        tts_provider: str | None = None,
        stt_provider: str | None = None,
        message_type: str | None = None,
        stt_text: str | None = None,
    ) -> None:
        fields: dict[str, str] = {}
        if output_audio_path is not None:
            fields["output_audio_path"] = output_audio_path
        if input_audio_path is not None:
            fields["input_audio_path"] = input_audio_path
        if tts_provider is not None:
            fields["tts_provider"] = tts_provider
        if stt_provider is not None:
            fields["stt_provider"] = stt_provider
        if message_type is not None:
            fields["message_type"] = message_type
        if stt_text is not None:
            fields["stt_text"] = stt_text
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE conversations SET {cols} WHERE id = ?",
                (*fields.values(), conv_id),
            )

    def insert_voice_log(
        self,
        *,
        session_id: str = "default",
        conversation_id: int | None = None,
        stt_provider: str = "",
        tts_provider: str = "",
        input_audio_path: str = "",
        output_audio_path: str = "",
        transcript: str = "",
        source_text: str = "",
        status: str = "ok",
        error_message: str = "",
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO voice_logs (
                    conversation_id, session_id, stt_provider, tts_provider,
                    input_audio_path, output_audio_path, transcript, source_text,
                    status, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    session_id,
                    stt_provider,
                    tts_provider,
                    input_audio_path,
                    output_audio_path,
                    transcript,
                    source_text,
                    status,
                    error_message,
                    _utc_now(),
                ),
            )
            return int(cur.lastrowid or 0)

    def list_voice_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM voice_logs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_conversations(
        self, session_id: str = "default", limit: int = 200
    ) -> list[dict[str, str]]:
        rows = self.list_conversations_with_ids(session_id, limit)
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def list_conversations_with_ids(
        self, session_id: str = "default", limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, created_at,
                       input_audio_path, output_audio_path, message_type,
                       stt_text, tts_provider, stt_provider
                FROM conversations
                WHERE session_id = ? AND role IN ('user', 'assistant')
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation_by_id(self, conv_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_last_assistant_message(self, session_id: str = "default") -> int | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id FROM conversations
                WHERE session_id = ? AND role = 'assistant'
                ORDER BY id DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if not row:
                return None
            conv_id = int(row["id"])
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return conv_id

    def list_conversations_today(self, session_id: str = "default") -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, created_at FROM conversations
                WHERE session_id = ? AND role IN ('user', 'assistant')
                AND created_at LIKE ?
                ORDER BY id ASC
                """,
                (session_id, f"{today}%"),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_conversations(self, session_id: str = "default") -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))

    def upsert_memory(
        self,
        memory_type: str,
        content: str,
        importance: int = 3,
        source_message_ids: list[int] | None = None,
        source_profile_fields: list[str] | None = None,
    ) -> int | None:
        content = content.strip()
        if not content or memory_type not in MEMORY_TYPES:
            return None
        importance = max(1, min(5, importance))
        now = _utc_now()
        with self._conn() as conn:
            memory_id = self._upsert_memory_conn(
                conn,
                memory_type,
                content,
                importance,
                source_message_ids,
                source_profile_fields,
                now,
                allow_reactivate=False,
            )
            self._trim_memory_type(conn, memory_type, 30)
            return memory_id

    def _upsert_memory_conn(
        self,
        conn: sqlite3.Connection,
        memory_type: str,
        content: str,
        importance: int,
        source_message_ids: list[int] | None,
        source_profile_fields: list[str] | None,
        now: str,
        allow_reactivate: bool,
    ) -> int:
        existing = conn.execute(
            """
            SELECT id, status, source_message_ids, source_profile_fields
            FROM memories WHERE memory_type = ? AND content = ?
            """,
            (memory_type, content),
        ).fetchone()
        if existing is not None:
            memory_id = int(existing["id"])
            if existing["status"] == "deleted" and not allow_reactivate:
                return memory_id
            if existing["status"] == "deleted":
                merged_message_ids = source_message_ids or []
                merged_profile_fields = source_profile_fields or []
            else:
                try:
                    old_message_ids = [
                        int(value)
                        for value in json.loads(existing["source_message_ids"] or "[]")
                    ]
                except (TypeError, ValueError, json.JSONDecodeError):
                    old_message_ids = []
                try:
                    old_profile_fields = json.loads(
                        existing["source_profile_fields"] or "[]"
                    )
                except (TypeError, json.JSONDecodeError):
                    old_profile_fields = []
                merged_message_ids = sorted(
                    set(old_message_ids) | set(source_message_ids or [])
                )
                merged_profile_fields = sorted(
                    {str(value) for value in old_profile_fields}
                    | set(source_profile_fields or [])
                )
            conn.execute(
                """
                UPDATE memories
                SET importance = MAX(importance, ?), status = 'active',
                    deleted_at = NULL, delete_scope = NULL,
                    source_message_ids = ?, source_profile_fields = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    importance,
                    self._json_list(merged_message_ids),
                    self._json_list(merged_profile_fields),
                    now,
                    memory_id,
                ),
            )
            return memory_id

        cur = conn.execute(
            """
            INSERT INTO memories (
                memory_type, content, importance, status, deleted_at, delete_scope,
                source_message_ids, source_profile_fields, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', NULL, NULL, ?, ?, ?, ?)
            """,
            (
                memory_type,
                content,
                importance,
                self._json_list(source_message_ids),
                self._json_list(source_profile_fields),
                now,
                now,
            ),
        )
        return int(cur.lastrowid)

    def _trim_memory_type(
        self, conn: sqlite3.Connection, memory_type: str, max_count: int
    ) -> None:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE memory_type = ? AND status = 'active'",
            (memory_type,),
        ).fetchone()["c"]
        if count <= max_count:
            return
        excess = count - max_count
        now = _utc_now()
        conn.execute(
            """
            UPDATE memories
            SET status = 'deleted', deleted_at = ?, delete_scope = 'long_term_only',
                updated_at = ?
            WHERE id IN (
                SELECT id FROM memories WHERE memory_type = ?
                AND status = 'active'
                ORDER BY importance ASC, updated_at ASC
                LIMIT ?
            )
            """,
            (now, now, memory_type, excess),
        )

    def list_memories(
        self, memory_type: str | None = None, include_deleted: bool = False
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            status_clause = "" if include_deleted else " AND status = 'active'"
            if memory_type:
                rows = conn.execute(
                    f"""
                    SELECT id, memory_type, content, importance, status, deleted_at,
                           delete_scope, source_message_ids, source_profile_fields, updated_at
                    FROM memories WHERE memory_type = ?{status_clause}
                    ORDER BY importance DESC, updated_at DESC
                    """,
                    (memory_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT id, memory_type, content, importance, status, deleted_at,
                           delete_scope, source_message_ids, source_profile_fields, updated_at
                    FROM memories WHERE 1 = 1{status_clause}
                    ORDER BY memory_type, importance DESC, updated_at DESC
                    """
                ).fetchall()
        return [dict(r) for r in rows]

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def delete_memory(
        self, memory_id: int, scope: str = "all_prompt_sources"
    ) -> dict[str, Any]:
        if scope not in {"long_term_only", "all_prompt_sources"}:
            raise ValueError(f"Unsupported delete scope: {scope}")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                return {
                    "memory_id": memory_id,
                    "status": "not_found",
                    "previous_status": None,
                    "affected_rows": 0,
                    "scope": scope,
                    "source_message_ids": "[]",
                    "source_profile_fields": "[]",
                }
            previous_status = str(row["status"] or "active")
            if previous_status == "deleted":
                return {
                    "memory_id": memory_id,
                    "status": "already_deleted",
                    "previous_status": previous_status,
                    "affected_rows": 0,
                    "scope": str(row["delete_scope"] or scope),
                    "source_message_ids": str(row["source_message_ids"] or "[]"),
                    "source_profile_fields": str(row["source_profile_fields"] or "[]"),
                }
            now = _utc_now()
            cur = conn.execute(
                """
                UPDATE memories
                SET status = 'deleted', deleted_at = ?, delete_scope = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, scope, now, memory_id),
            )
            return {
                "memory_id": memory_id,
                "status": "deleted" if cur.rowcount else "not_found",
                "previous_status": previous_status,
                "affected_rows": int(cur.rowcount),
                "scope": scope,
                "source_message_ids": str(row["source_message_ids"] or "[]"),
                "source_profile_fields": str(row["source_profile_fields"] or "[]"),
            }

    def get_deleted_prompt_exclusions(self) -> dict[str, set[Any]]:
        message_ids: set[int] = set()
        profile_fields: set[str] = set()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT source_message_ids, source_profile_fields
                FROM memories
                WHERE status = 'deleted' AND delete_scope = 'all_prompt_sources'
                """
            ).fetchall()
        for row in rows:
            try:
                message_ids.update(int(value) for value in json.loads(row[0] or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            try:
                profile_fields.update(str(value) for value in json.loads(row[1] or "[]"))
            except (TypeError, json.JSONDecodeError):
                pass
        return {"message_ids": message_ids, "profile_fields": profile_fields}

    def insert_pending_memory(
        self,
        memory_type: str,
        content: str,
        importance: int = 3,
        source: str = "auto",
        source_message_ids: list[int] | None = None,
        source_profile_fields: list[str] | None = None,
    ) -> int:
        now = _utc_now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO pending_memories (
                    memory_type, content, importance, status, source,
                    source_message_ids, source_profile_fields, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    memory_type,
                    content.strip(),
                    importance,
                    source,
                    self._json_list(source_message_ids),
                    self._json_list(source_profile_fields),
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid or 0)

    def list_pending_memories(self, status: str = "pending") -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM pending_memories WHERE status = ?
                ORDER BY created_at DESC
                """,
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_pending_memory(self, pending_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM pending_memories WHERE id = ?", (pending_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_pending_status(self, pending_id: int, status: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE pending_memories SET status = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, _utc_now(), pending_id),
            )
            return bool(cur.rowcount)

    def update_pending_content(self, pending_id: int, content: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE pending_memories SET content = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (content.strip(), _utc_now(), pending_id),
            )
            return bool(cur.rowcount)

    def confirm_pending_memory(self, pending_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM pending_memories WHERE id = ?", (pending_id,)
            ).fetchone()
            if not row or row["status"] != "pending":
                return False
            now = _utc_now()
            try:
                message_ids = [int(value) for value in json.loads(row["source_message_ids"] or "[]")]
            except (TypeError, ValueError, json.JSONDecodeError):
                message_ids = []
            try:
                profile_fields = [str(value) for value in json.loads(row["source_profile_fields"] or "[]")]
            except (TypeError, json.JSONDecodeError):
                profile_fields = []
            self._upsert_memory_conn(
                conn,
                str(row["memory_type"]),
                str(row["content"]),
                int(row["importance"]),
                message_ids,
                profile_fields,
                now,
                allow_reactivate=True,
            )
            self._trim_memory_type(conn, str(row["memory_type"]), 30)
            conn.execute(
                "UPDATE pending_memories SET status = 'confirmed', updated_at = ? WHERE id = ?",
                (now, pending_id),
            )
            return True

    def reject_pending_memory(self, pending_id: int) -> bool:
        return self.update_pending_status(pending_id, "rejected")

    def get_user_profile(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM user_profile WHERE id = 1").fetchone()
        if row:
            return dict(row)
        return {
            "display_name": "",
            "preferred_mode": "日常聊天",
            "reply_style": "细腻",
            "remember_prefs": 1,
            "onboarding_completed": 0,
        }

    def save_user_profile(
        self,
        display_name: str,
        preferred_mode: str,
        reply_style: str,
        remember_prefs: bool,
        onboarding_completed: bool = True,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_profile (
                    id, display_name, preferred_mode, reply_style,
                    remember_prefs, onboarding_completed, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    preferred_mode = excluded.preferred_mode,
                    reply_style = excluded.reply_style,
                    remember_prefs = excluded.remember_prefs,
                    onboarding_completed = excluded.onboarding_completed,
                    updated_at = excluded.updated_at
                """,
                (
                    display_name,
                    preferred_mode,
                    reply_style,
                    1 if remember_prefs else 0,
                    1 if onboarding_completed else 0,
                    _utc_now(),
                ),
            )

    def get_daily_companion(self, date_str: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_companion WHERE date = ?", (date_str,)
            ).fetchone()
        return dict(row) if row else None

    def get_latest_daily_companion(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_companion ORDER BY date DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def upsert_daily_companion(
        self,
        date_str: str,
        greeting: str,
        little_note: str,
        streak_days: int,
        last_visit_date: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO daily_companion (
                    date, greeting, little_note, streak_days, last_visit_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    greeting = excluded.greeting,
                    little_note = excluded.little_note,
                    streak_days = excluded.streak_days,
                    last_visit_date = excluded.last_visit_date
                """,
                (date_str, greeting, little_note, streak_days, last_visit_date, _utc_now()),
            )

    def insert_relationship_event(
        self,
        event_key: str,
        title: str,
        description: str,
        intimacy_at_unlock: int = 0,
    ) -> bool:
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO relationship_events (
                        event_key, title, description, intimacy_at_unlock, unlocked_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_key, title, description, intimacy_at_unlock, _utc_now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def has_relationship_event(self, event_key: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM relationship_events WHERE event_key = ?", (event_key,)
            ).fetchone()
        return row is not None

    def list_relationship_events(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM relationship_events
                ORDER BY unlocked_at ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_message_feedback(
        self,
        conversation_id: int | None,
        feedback_type: str,
        user_snippet: str = "",
        reply_snippet: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO message_feedback (
                    conversation_id, feedback_type,
                    user_input_snippet, reply_snippet, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, feedback_type, user_snippet, reply_snippet, _utc_now()),
            )

    def get_feedback_stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            likes = conn.execute(
                "SELECT COUNT(*) AS c FROM message_feedback WHERE feedback_type = 'like'"
            ).fetchone()["c"]
            ooc = conn.execute(
                """
                SELECT COUNT(*) AS c FROM message_feedback
                WHERE feedback_type = 'out_of_character'
                """
            ).fetchone()["c"]
            total = conn.execute("SELECT COUNT(*) AS c FROM message_feedback").fetchone()["c"]
            samples = conn.execute(
                """
                SELECT reply_snippet FROM message_feedback
                WHERE feedback_type = 'out_of_character' AND reply_snippet != ''
                ORDER BY id DESC LIMIT 5
                """
            ).fetchall()
        like_n = int(likes)
        ooc_n = int(ooc)
        total_n = int(total)
        satisfaction = round(like_n / total_n * 100, 1) if total_n else 0.0
        return {
            "like_count": like_n,
            "out_of_character_count": ooc_n,
            "total_count": total_n,
            "satisfaction_pct": satisfaction,
            "ooc_samples": [r["reply_snippet"] for r in samples],
        }

    def upsert_daily_reflection(self, date_str: str, content: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO daily_reflections (date, content, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET content = excluded.content
                """,
                (date_str, content, _utc_now()),
            )

    def get_daily_reflection(self, date_str: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_reflections WHERE date = ?", (date_str,)
            ).fetchone()
        return dict(row) if row else None

    def list_daily_reflections(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM daily_reflections ORDER BY date DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_memories(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM memories")

    def count_memories(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM memories WHERE status = 'active'"
            ).fetchone()
        return int(row["c"])

    def insert_evaluation(
        self,
        user_input: str,
        assistant_reply: str,
        personality_score: int,
        tone_score: int,
        memory_usage_score: int,
        emotional_response_score: int,
        immersion_score: int,
        comment: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO evaluations (
                    user_input, assistant_reply,
                    personality_score, tone_score, memory_usage_score,
                    emotional_response_score, immersion_score, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_input,
                    assistant_reply,
                    personality_score,
                    tone_score,
                    memory_usage_score,
                    emotional_response_score,
                    immersion_score,
                    comment,
                    _utc_now(),
                ),
            )

    def get_latest_evaluation(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM evaluations ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def get_evaluation_averages(self) -> dict[str, float]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    AVG(personality_score) AS personality_score,
                    AVG(tone_score) AS tone_score,
                    AVG(memory_usage_score) AS memory_usage_score,
                    AVG(emotional_response_score) AS emotional_response_score,
                    AVG(immersion_score) AS immersion_score
                FROM evaluations
                """
            ).fetchone()
        if not row or row["personality_score"] is None:
            return {}
        return {k: round(float(row[k]), 1) for k in row.keys()}

    def count_evaluations(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM evaluations").fetchone()
        return int(row["c"])

    def get_companionship(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM companionship WHERE id = 1").fetchone()
        if row:
            return dict(row)
        return {
            "intimacy_score": 20,
            "relationship_stage": "初识",
            "mood": "温柔",
            "last_greeting_date": "",
            "last_important_interaction": "",
        }

    def update_companionship(self, **fields: Any) -> None:
        allowed = {
            "intimacy_score",
            "relationship_stage",
            "mood",
            "last_greeting_date",
            "last_important_interaction",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _utc_now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE companionship SET {cols} WHERE id = 1",
                tuple(updates.values()),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, _utc_now()),
            )

    def get_stats(self) -> dict[str, Any]:
        comp = self.get_companionship()
        with self._conn() as conn:
            conv = conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()["c"]
            mem = conn.execute(
                "SELECT COUNT(*) AS c FROM memories WHERE status = 'active'"
            ).fetchone()["c"]
            ev = conn.execute("SELECT COUNT(*) AS c FROM evaluations").fetchone()["c"]
            try:
                vl = conn.execute("SELECT COUNT(*) AS c FROM voice_logs").fetchone()["c"]
            except sqlite3.OperationalError:
                vl = 0
        return {
            "database_path": str(self.path),
            "conversations": int(conv),
            "memories": int(mem),
            "evaluations": int(ev),
            "voice_logs": int(vl),
            "intimacy_score": comp.get("intimacy_score", 20),
            "relationship_stage": comp.get("relationship_stage", "初识"),
            "pending_memories": len(self.list_pending_memories()),
            "feedback": self.get_feedback_stats(),
        }

    def migrate_from_json(self, memory_path: Path, chat_logs_path: Path) -> bool:
        with self._conn() as conn:
            existing = conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()["c"]
        if existing > 0:
            return False

        migrated = False
        if chat_logs_path.exists():
            try:
                logs = json.loads(chat_logs_path.read_text(encoding="utf-8"))
                if isinstance(logs, list):
                    for item in logs:
                        role = item.get("role", "")
                        if role in ("user", "assistant"):
                            self.insert_conversation(
                                role,
                                str(item.get("content", "")),
                                str(item.get("character", "")),
                            )
                    migrated = True
            except (json.JSONDecodeError, OSError):
                pass

        if memory_path.exists():
            try:
                data = json.loads(memory_path.read_text(encoding="utf-8"))
                mapping = {
                    "preferences": "preference",
                    "nicknames": "nickname",
                    "important_events": "important_event",
                    "emotional_states": "emotional_state",
                }
                for key, mtype in mapping.items():
                    for item in data.get(key, []):
                        self.upsert_memory(mtype, str(item), 3)
                if data.get("summary"):
                    self.upsert_memory("summary", str(data["summary"]), 4)
                migrated = True
            except (json.JSONDecodeError, OSError):
                pass

        return migrated
