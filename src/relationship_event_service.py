"""Relationship milestones and timeline."""

from __future__ import annotations

from src.database import Database

INTIMACY_MILESTONES = [
    (25, "familiar_25", "开始熟悉", "你们已经聊过不少心事，我开始更了解你了。"),
    (50, "trust_50", "信赖建立", "你愿意分享更多，我也更想守护这份信赖。"),
    (75, "friend_75", "重要的朋友", "你对我来说，已经是特别重要的人了。"),
    (90, "precious_90", "珍贵回忆", "和你在一起的点滴，都被我小心收进回忆里。"),
]


class RelationshipEventService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record_event(
        self,
        event_key: str,
        title: str,
        description: str,
        intimacy_at_unlock: int = 0,
    ) -> bool:
        return self.db.insert_relationship_event(
            event_key, title, description, intimacy_at_unlock
        )

    def on_first_user_message(self) -> None:
        if not self.db.has_relationship_event("first_chat"):
            self.record_event(
                "first_chat",
                "第一次聊天",
                "你们开始了第一段对话。",
            )

    def on_first_preference_saved(self) -> None:
        if not self.db.has_relationship_event("first_preference"):
            self.record_event(
                "first_preference",
                "第一次记录偏好",
                "爱莉希雅记住了你在意的小事。",
            )

    def on_first_comfort(self) -> None:
        if not self.db.has_relationship_event("first_comfort"):
            self.record_event(
                "first_comfort",
                "第一次情绪安慰",
                "在你低落时，她选择了陪伴与倾听。",
            )

    def check_intimacy_milestones(self, intimacy: int, stage: str) -> None:
        for threshold, key, title, desc in INTIMACY_MILESTONES:
            if intimacy >= threshold and not self.db.has_relationship_event(key):
                self.record_event(key, title, desc, threshold)

        stage_key = f"stage_{stage}"
        if not self.db.has_relationship_event(stage_key):
            self.record_event(
                stage_key,
                f"关系阶段：{stage}",
                f"你们的关系进入了「{stage}」阶段。",
                intimacy,
            )

    def get_timeline(self) -> list[dict[str, str]]:
        events = self.db.list_relationship_events()
        return [
            {
                "title": e["title"],
                "description": e["description"],
                "time": e["unlocked_at"][:10] if e.get("unlocked_at") else "",
            }
            for e in events
        ]
