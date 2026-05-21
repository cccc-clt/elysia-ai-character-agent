"""Per-message feedback collection."""

from __future__ import annotations

from typing import Any

from src.database import Database


class FeedbackService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(
        self,
        feedback_type: str,
        conversation_id: int | None = None,
        user_snippet: str = "",
        reply_snippet: str = "",
    ) -> None:
        self.db.insert_message_feedback(
            conversation_id,
            feedback_type,
            user_snippet[:200],
            reply_snippet[:500],
        )

    def get_stats(self) -> dict[str, Any]:
        return self.db.get_feedback_stats()
