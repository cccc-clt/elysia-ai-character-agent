"""Daily reflection / today recap generation."""

from __future__ import annotations

import json
from datetime import date

from src.database import Database
from src.llm_client import LLMClient

REFLECTION_SYSTEM = """你是爱莉希雅。根据用户今日真实聊天记录，写一段温柔的「今日回忆」总结（150-250字）。
规则：只总结对话中实际出现的内容；不要编造未发生的对话或事件；语气温柔浪漫。"""


class ReflectionService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_today_reflection(self) -> dict | None:
        today = date.today().isoformat()
        return self.db.get_daily_reflection(today)

    def list_reflections(self, limit: int = 14) -> list[dict]:
        return self.db.list_daily_reflections(limit)

    def generate_today(
        self,
        llm: LLMClient,
        session_id: str = "default",
        model: str | None = None,
    ) -> tuple[str | None, str | None]:
        today = date.today().isoformat()
        messages = self.db.list_conversations_today(session_id)
        if len(messages) < 2:
            return None, "今天还没有足够的对话，聊几句再来生成回忆吧。"

        history = "\n".join(
            f"{'玩家' if m['role'] == 'user' else '爱莉希雅'}：{m['content']}"
            for m in messages
        )

        try:
            content = llm.chat(
                REFLECTION_SYSTEM,
                json.dumps({"date": today, "conversation": history}, ensure_ascii=False),
                model=model,
                temperature=0.7,
            )
            if not content.strip():
                return None, "生成失败，请稍后重试。"
            self.db.upsert_daily_reflection(today, content.strip())
            return content.strip(), None
        except Exception as exc:
            return None, f"生成今日回忆失败：{exc}"
