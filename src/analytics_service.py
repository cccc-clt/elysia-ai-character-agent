"""Player experience analytics — game AI product style report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.llm_client import LLMClient


@dataclass
class PlayerExperienceReport:
    interaction_type: str
    preferred_response_style: str
    content_focus: str
    emotional_tendency: str
    intimacy_change_reason: str
    retention_value: str
    next_interaction_advice: str
    experience_summary: str

    def to_dict(self) -> dict[str, str]:
        return {
            "interaction_type": self.interaction_type,
            "preferred_response_style": self.preferred_response_style,
            "content_focus": self.content_focus,
            "emotional_tendency": self.emotional_tendency,
            "intimacy_change_reason": self.intimacy_change_reason,
            "retention_value": self.retention_value,
            "next_interaction_advice": self.next_interaction_advice,
            "experience_summary": self.experience_summary,
        }


ANALYTICS_SYSTEM_PROMPT = """你是游戏 AI 角色陪伴产品的体验分析专家。
根据聊天记录、亲密度与关系阶段，输出 JSON（每项 80-200 字中文）：
interaction_type: 用户互动类型
preferred_response_style: 用户偏好的角色回应风格
content_focus: 用户关注内容
emotional_tendency: 情绪倾向
intimacy_change_reason: 亲密度变化原因（结合数据推测）
retention_value: 潜在留存/陪伴价值
next_interaction_advice: 下一步互动建议（分点）
experience_summary: 当前体验总结
分析须基于实际对话，不要编造。"""


def analyze_player_experience(
    llm: LLMClient,
    messages: list[dict[str, str]],
    character_name: str = "",
    *,
    companionship_context: str = "",
    evaluation_averages: dict[str, float] | None = None,
    feedback_stats: dict | None = None,
    model: str | None = None,
) -> PlayerExperienceReport:
    if len(messages) < 2:
        return _empty_report()

    history = "\n".join(
        f"{'玩家' if m['role'] == 'user' else character_name or '角色'}：{m['content']}"
        for m in messages[-40:]
    )

    payload = {
        "character": character_name,
        "chat_history": history,
        "companionship": companionship_context,
        "evaluation_averages": evaluation_averages or {},
        "feedback_stats": feedback_stats or {},
    }

    try:
        raw = llm.chat_json(
            ANALYTICS_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False),
            model=model,
        )
        data = json.loads(raw)
    except Exception:
        return _fallback_report()

    return PlayerExperienceReport(
        interaction_type=_field(data, "interaction_type", 500),
        preferred_response_style=_field(data, "preferred_response_style", 500),
        content_focus=_field(data, "content_focus", 500),
        emotional_tendency=_field(data, "emotional_tendency", 500),
        intimacy_change_reason=_field(data, "intimacy_change_reason", 500),
        retention_value=_field(data, "retention_value", 500),
        next_interaction_advice=_field(data, "next_interaction_advice", 800),
        experience_summary=_field(data, "experience_summary", 600),
    )


def _field(data: dict[str, Any], key: str, limit: int) -> str:
    return str(data.get(key, "暂无分析"))[:limit]


def _empty_report() -> PlayerExperienceReport:
    return PlayerExperienceReport(
        interaction_type="对话数量不足，暂无法分析。",
        preferred_response_style="请先与角色进行几轮对话。",
        content_focus="数据不足。",
        emotional_tendency="数据不足。",
        intimacy_change_reason="数据不足。",
        retention_value="数据不足。",
        next_interaction_advice="建议完成至少 4 轮对话后再进行分析。",
        experience_summary="等待更多互动数据。",
    )


def _fallback_report() -> PlayerExperienceReport:
    return PlayerExperienceReport(
        interaction_type="分析服务暂不可用。",
        preferred_response_style="请稍后重试。",
        content_focus="—",
        emotional_tendency="—",
        intimacy_change_reason="—",
        retention_value="—",
        next_interaction_advice="检查 API 配置与网络连接后重试。",
        experience_summary="—",
    )
