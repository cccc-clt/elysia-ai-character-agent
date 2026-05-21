"""Companionship: intimacy, relationship stage, mood, daily greeting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from src.database import Database

POSITIVE_KEYWORDS = ("谢谢", "感谢", "喜欢", "信任", "开心", "高兴", "爱你", "真好", "棒")
LOW_KEYWORDS = ("难过", "伤心", "低落", "沮丧", "焦虑", "压力", "累", "孤独", "害怕", "哭")
COMFORT_KEYWORDS = ("陪", "听", "没关系", "会好", "加油", "抱抱", "在这", "理解", "别担心")


def stage_from_intimacy(score: int) -> str:
    if score <= 25:
        return "初识"
    if score <= 50:
        return "熟悉"
    if score <= 75:
        return "信赖"
    return "重要的朋友"


GREETINGS = [
    "今天也想和你多说说话呢。",
    "见到你真好，今天过得怎么样？",
    "呀，你来啦～有什么想分享的吗？",
    "新的一天，也想把温柔留一点给你。",
    "我一直在哦，想聊什么都可以。",
]


@dataclass
class CompanionshipState:
    intimacy_score: int
    relationship_stage: str
    mood: str
    last_greeting_date: str
    last_important_interaction: str
    daily_greeting: str
    show_greeting: bool

    def to_prompt_context(self, daily_greeting: str = "", daily_note: str = "") -> str:
        lines = [
            f"亲密度：{self.intimacy_score}/100",
            f"关系阶段：{self.relationship_stage}",
            f"当前心情：{self.mood}",
        ]
        greet = daily_greeting or (self.daily_greeting if self.show_greeting else "")
        if greet:
            lines.append(f"今日问候（可说一次）：{greet}")
        if daily_note:
            lines.append(f"今日小纸条（可自然融入）：{daily_note}")
        if self.last_important_interaction:
            lines.append(f"最近重要互动：{self.last_important_interaction}")
        return "\n".join(lines)


class CompanionshipService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def load_state(self) -> CompanionshipState:
        raw = self.db.get_companionship()
        today = date.today().isoformat()
        last_greet = str(raw.get("last_greeting_date", ""))
        show_greeting = last_greet != today
        greeting = ""
        if show_greeting:
            seed = int(today.replace("-", ""))
            greeting = GREETINGS[seed % len(GREETINGS)]

        return CompanionshipState(
            intimacy_score=int(raw.get("intimacy_score", 20)),
            relationship_stage=str(raw.get("relationship_stage", "初识")),
            mood=str(raw.get("mood", "温柔")),
            last_greeting_date=last_greet,
            last_important_interaction=str(raw.get("last_important_interaction", "")),
            daily_greeting=greeting,
            show_greeting=show_greeting,
        )

    def mark_greeting_shown(self) -> None:
        today = date.today().isoformat()
        self.db.update_companionship(last_greeting_date=today)

    def process_turn(
        self,
        user_message: str,
        assistant_message: str,
        turn_count: int = 0,
    ) -> CompanionshipState:
        state = self.load_state()
        intimacy = state.intimacy_score + 1

        user_lower = user_message.lower()
        if any(k in user_message for k in POSITIVE_KEYWORDS):
            intimacy += 2
        if any(k in user_message for k in LOW_KEYWORDS):
            if any(k in assistant_message for k in COMFORT_KEYWORDS):
                intimacy += 1

        intimacy = min(100, intimacy)
        mood = self._detect_mood(user_message, turn_count)
        stage = stage_from_intimacy(intimacy)

        important = state.last_important_interaction
        if len(user_message) > 20 and (
            any(k in user_message for k in POSITIVE_KEYWORDS + LOW_KEYWORDS)
            or "重要" in user_message
        ):
            important = user_message[:120]

        self.db.update_companionship(
            intimacy_score=intimacy,
            relationship_stage=stage,
            mood=mood,
            last_important_interaction=important,
        )
        return self.load_state()

    def _detect_mood(self, user_message: str, turn_count: int) -> str:
        if any(k in user_message for k in ("开心", "高兴", "快乐", "哈哈", "棒")):
            return "开心"
        if any(k in user_message for k in LOW_KEYWORDS):
            return "关心"
        if turn_count >= 8:
            return "陪伴中"
        return "温柔"

    def get_summary(self, memory_summary: str = "") -> dict[str, str]:
        state = self.load_state()
        remembered = memory_summary[:200] if memory_summary else "还在慢慢了解你……"
        return {
            "remembered": remembered,
            "relationship": state.relationship_stage,
            "recent": state.last_important_interaction or "你们的故事才刚刚开始。",
            "mood": state.mood,
            "intimacy": str(state.intimacy_score),
        }
