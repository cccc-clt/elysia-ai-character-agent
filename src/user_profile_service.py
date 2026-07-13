"""User profile and onboarding."""

from __future__ import annotations

from dataclasses import dataclass

from src.database import Database


@dataclass
class UserProfile:
    display_name: str
    preferred_mode: str
    reply_style: str
    remember_prefs: bool
    onboarding_completed: bool

    def to_prompt_context(
        self, excluded_fields: set[str] | frozenset[str] | None = None
    ) -> str:
        excluded = excluded_fields or set()
        lines = []
        if self.display_name and "display_name" not in excluded:
            lines.append(f"用户希望被称呼为：{self.display_name}")
        if "preferred_mode" not in excluded:
            lines.append(f"用户偏好的陪伴模式：{self.preferred_mode}")
        if "reply_style" not in excluded:
            if self.reply_style == "简短":
                lines.append("用户偏好简短回复（1-2段即可）。")
            else:
                lines.append("用户偏好细腻回复（可稍丰富，但仍适合聊天）。")
        return "\n".join(lines) if lines else "（尚未设置用户画像）"


class UserProfileService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_profile(self) -> UserProfile:
        raw = self.db.get_user_profile()
        return UserProfile(
            display_name=str(raw.get("display_name", "")),
            preferred_mode=str(raw.get("preferred_mode", "日常聊天")),
            reply_style=str(raw.get("reply_style", "细腻")),
            remember_prefs=bool(int(raw.get("remember_prefs", 1))),
            onboarding_completed=bool(int(raw.get("onboarding_completed", 0))),
        )

    def is_onboarding_done(self) -> bool:
        return self.get_profile().onboarding_completed

    def save_onboarding(
        self,
        display_name: str,
        preferred_mode: str,
        reply_style: str,
        remember_prefs: bool,
    ) -> UserProfile:
        self.db.save_user_profile(
            display_name=display_name.strip(),
            preferred_mode=preferred_mode,
            reply_style=reply_style,
            remember_prefs=remember_prefs,
            onboarding_completed=True,
        )
        from src.companion_mode import set_mode

        set_mode(self.db, preferred_mode)

        profile = self.get_profile()
        if remember_prefs and display_name.strip():
            self.db.insert_pending_memory(
                "nickname",
                f"希望被称呼为：{display_name.strip()}",
                importance=4,
                source="onboarding",
                source_profile_fields=["display_name"],
            )
        if remember_prefs:
            self.db.insert_pending_memory(
                "preference",
                f"偏好{reply_style}回复",
                importance=3,
                source="onboarding",
                source_profile_fields=["reply_style"],
            )
            self.db.insert_pending_memory(
                "preference",
                f"偏好{preferred_mode}陪伴模式",
                importance=3,
                source="onboarding",
                source_profile_fields=["preferred_mode"],
            )
        return profile
