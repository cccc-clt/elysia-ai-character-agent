"""Character consistency evaluation with SQLite persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.character_profile import CharacterProfile
from src.database import Database
from src.llm_client import LLMClient


@dataclass
class ConsistencyEvaluation:
    personality_score: int
    tone_score: int
    memory_usage_score: int
    emotional_response_score: int
    immersion_score: int
    comment: str
    overall_score: float = 0.0
    verdict: str = "基本稳定"

    def __post_init__(self) -> None:
        if not self.overall_score:
            self.overall_score = round(
                (
                    self.personality_score
                    + self.tone_score
                    + self.memory_usage_score
                    + self.emotional_response_score
                    + self.immersion_score
                )
                / 5,
                1,
            )
        if self.verdict == "基本稳定":
            self.verdict = _verdict_from_score(self.overall_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "personality_score": self.personality_score,
            "tone_score": self.tone_score,
            "memory_usage_score": self.memory_usage_score,
            "emotional_response_score": self.emotional_response_score,
            "immersion_score": self.immersion_score,
            "overall_score": self.overall_score,
            "verdict": self.verdict,
            "comment": self.comment,
        }


def _verdict_from_score(overall: float) -> str:
    if overall >= 88:
        return "表现优秀"
    if overall >= 72:
        return "基本稳定"
    if overall >= 55:
        return "需要优化"
    return "明显偏离"


EVAL_SYSTEM_PROMPT = """你是游戏角色 AI 的一致性评估专家。
根据角色设定、长期记忆、玩家输入和角色回复打分。
必须输出 JSON（0-100 整数）：
personality_score, tone_score, memory_usage_score, emotional_response_score, immersion_score, comment(50字内中文)。
评分要客观，不要全部给满分。
若长期记忆为空或标注暂无，memory_usage_score 应基于「无记忆可引用」给中性分(70-80)，不应因此给极低分。"""


def evaluate_reply(
    llm: LLMClient,
    character: CharacterProfile,
    user_input: str,
    assistant_reply: str,
    long_term_memory: str,
    *,
    db: Database | None = None,
    has_long_term_memory: bool = False,
    model: str | None = None,
) -> ConsistencyEvaluation:
    payload = {
        "character": character.to_dict(),
        "long_term_memory": long_term_memory,
        "has_long_term_memory": has_long_term_memory,
        "user_input": user_input,
        "assistant_reply": assistant_reply,
    }

    try:
        raw = llm.chat_json(EVAL_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), model=model)
        data = json.loads(raw)
    except Exception:
        return _fallback_evaluation()

    ev = ConsistencyEvaluation(
        personality_score=_clamp_score(data.get("personality_score", 70)),
        tone_score=_clamp_score(data.get("tone_score", 70)),
        memory_usage_score=_clamp_score(data.get("memory_usage_score", 75)),
        emotional_response_score=_clamp_score(data.get("emotional_response_score", 70)),
        immersion_score=_clamp_score(data.get("immersion_score", 70)),
        comment=str(data.get("comment", "评估完成。"))[:120],
    )

    if db is not None:
        try:
            db.insert_evaluation(
                user_input=user_input,
                assistant_reply=assistant_reply,
                personality_score=ev.personality_score,
                tone_score=ev.tone_score,
                memory_usage_score=ev.memory_usage_score,
                emotional_response_score=ev.emotional_response_score,
                immersion_score=ev.immersion_score,
                comment=ev.comment,
            )
        except Exception:
            pass

    return ev


def get_evaluation_summary(db: Database | None) -> dict[str, Any]:
    if db is None:
        return {}
    latest = db.get_latest_evaluation()
    averages = db.get_evaluation_averages()
    result: dict[str, Any] = {"averages": averages, "count": db.count_evaluations()}
    if latest:
        scores = [
            latest["personality_score"],
            latest["tone_score"],
            latest["memory_usage_score"],
            latest["emotional_response_score"],
            latest["immersion_score"],
        ]
        overall = round(sum(scores) / len(scores), 1)
        result["latest"] = {
            **latest,
            "overall_score": overall,
            "verdict": _verdict_from_score(overall),
        }
    return result


def _clamp_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = 70
    return max(0, min(100, score))


def _fallback_evaluation() -> ConsistencyEvaluation:
    return ConsistencyEvaluation(
        personality_score=70,
        tone_score=70,
        memory_usage_score=75,
        emotional_response_score=70,
        immersion_score=68,
        comment="评估服务暂不可用，已返回默认分数。",
    )
