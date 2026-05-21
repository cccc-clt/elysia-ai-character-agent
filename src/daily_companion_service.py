"""Daily greeting, little note, and streak tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.database import Database
from src.llm_client import LLMClient

GREETINGS = [
    "今天也想和你多说说话呢。",
    "见到你真好，今天过得怎么样？",
    "呀，你来啦～有什么想分享的吗？",
    "新的一天，也想把温柔留一点给你。",
    "我一直在哦，想聊什么都可以。",
]

LITTLE_NOTES = [
    "记得照顾好自己，小休息也是温柔的事。",
    "你值得被认真倾听，包括那些说不出口的情绪。",
    "今天也为你留了一小段粉色的时间。",
    "慢慢来没关系，我会在这里。",
    "把烦恼分我一半，快乐留给你自己。",
]


@dataclass
class DailyCompanionView:
    date: str
    greeting: str
    little_note: str
    streak_days: int
    relationship_stage: str

    def to_status_dict(self) -> dict[str, str]:
        return {
            "streak": str(self.streak_days),
            "greeting": self.greeting,
            "little_note": self.little_note,
            "date": self.date,
        }


class DailyCompanionService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_today(self, relationship_stage: str = "初识", llm: LLMClient | None = None) -> DailyCompanionView:
        today = date.today().isoformat()
        existing = self.db.get_daily_companion(today)
        if existing:
            return DailyCompanionView(
                date=today,
                greeting=str(existing["greeting"]),
                little_note=str(existing["little_note"]),
                streak_days=int(existing["streak_days"]),
                relationship_stage=relationship_stage,
            )

        latest = self.db.get_latest_daily_companion()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        streak = 1
        if latest:
            last_visit = str(latest.get("last_visit_date", ""))
            if last_visit == yesterday:
                streak = int(latest.get("streak_days", 1)) + 1
            elif last_visit == today:
                streak = int(latest.get("streak_days", 1))

        seed = int(today.replace("-", ""))
        greeting = GREETINGS[seed % len(GREETINGS)]
        little_note = LITTLE_NOTES[seed % len(LITTLE_NOTES)]

        if llm and llm.has_api_key:
            try:
                raw = llm.chat(
                    "你是爱莉希雅。写一句30字内的今日小纸条，温柔浪漫，不要官方台词。",
                    f"关系阶段：{relationship_stage}，连续陪伴{streak}天。",
                    temperature=0.9,
                )
                if raw and len(raw) < 120:
                    little_note = raw.strip()
            except Exception:
                pass

        self.db.upsert_daily_companion(today, greeting, little_note, streak, today)
        self.db.update_companionship(last_greeting_date=today)
        return DailyCompanionView(
            date=today,
            greeting=greeting,
            little_note=little_note,
            streak_days=streak,
            relationship_stage=relationship_stage,
        )
