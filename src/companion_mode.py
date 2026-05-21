"""Companion mode definitions and prompt instructions."""

from __future__ import annotations

from src.database import Database

MODES = [
    "日常聊天",
    "情绪安慰",
    "学习陪伴",
    "睡前陪伴",
    "剧情互动",
]

MODE_PROMPT_SUFFIX: dict[str, str] = {
    "日常聊天": "当前为日常陪伴模式：自然、轻松，像朋友一样陪用户聊天。",
    "情绪安慰": "当前为情绪安慰模式：更共情、更温柔、多倾听少说教，不急于给解决方案。",
    "学习陪伴": "当前为学习陪伴模式：像学习搭子，鼓励用户完成小目标，可温柔提醒休息，但不要变成严厉教官。",
    "睡前陪伴": "当前为睡前陪伴模式：回复更短、更轻、更安静，避免兴奋话题，营造安心入睡氛围。",
    "剧情互动": "当前为剧情互动模式：更有角色扮演感与画面感，但仍不要编造官方剧情。",
}

SETTING_KEY = "current_companion_mode"


def get_current_mode(db: Database) -> str:
    mode = db.get_setting(SETTING_KEY, "日常聊天")
    return mode if mode in MODES else "日常聊天"


def set_mode(db: Database, mode: str) -> None:
    if mode not in MODES:
        mode = "日常聊天"
    db.set_setting(SETTING_KEY, mode)


def get_mode_instructions(db: Database) -> str:
    mode = get_current_mode(db)
    return MODE_PROMPT_SUFFIX.get(mode, MODE_PROMPT_SUFFIX["日常聊天"])
