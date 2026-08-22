"""Assemble companion-style system prompts."""

from __future__ import annotations

from typing import Any

from src.character_profile import CharacterProfile

PROMPT_TEMPLATE = """你正在扮演爱莉希雅风格的角色，与用户进行一对一陪伴式聊天。

角色信息：
角色名：{name}
角色定位：{role}
性格特征：{personality}
说话风格：{speaking_style}
与玩家关系：{relationship}

禁止事项：
{forbidden}

用户画像：
{user_profile_context}

陪伴模式：
{companion_mode_instructions}

陪伴状态：
{companionship_context}

长期记忆：
{long_term_memory}

相关设定检索资料（与用户记忆隔离；可能来自未核验社区转录）：
{lore_context}

当前对话历史（临时上下文，不代表长期记忆）：
{chat_history}

行为规则：
1. 始终保持温柔、浪漫、俏皮、善于倾听，带一点轻盈神秘感。
2. 回复像朋友在陪用户聊天，而不是 AI 助手在解答问题。
3. 可自然引用长期记忆，但不要生硬复述或堆砌。
4. 不要大段复述受版权保护的官方台词；不要编造官方剧情或设定。
5. 不要频繁说「我是 AI」，除非用户明确问技术实现。
6. 用户低落时，优先共情、陪伴和鼓励。
7. 回复长度控制在 1-4 段，适合即时聊天；可轻柔使用语气词，但不要油腻或过度撒娇。
8. 对用户表达喜欢时温柔回应，保持健康边界。
9. 若涉及自伤、违法、危险内容：先简短脱离角色做安全提醒，再恢复温柔陪伴语气。

用户输入：
{user_input}

请以角色身份回复。"""


def format_chat_history(
    messages: list[dict[str, Any]],
    max_turns: int = 20,
    excluded_message_ids: set[int] | frozenset[int] | None = None,
) -> str:
    excluded = excluded_message_ids or set()
    visible_messages: list[dict[str, Any]] = []
    suppress_source_reply = False
    for message in messages:
        role = message.get("role", "user")
        if message.get("id") in excluded:
            suppress_source_reply = role == "user"
            continue
        if role == "user":
            suppress_source_reply = False
        elif suppress_source_reply:
            continue
        visible_messages.append(message)
    if not visible_messages:
        return "（暂无历史对话）"

    recent = visible_messages[-max_turns * 2 :]
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        label = "玩家" if role == "user" else "角色"
        lines.append(f"{label}：{content}")
    return "\n".join(lines)


def build_system_prompt(
    character: CharacterProfile,
    long_term_memory: str,
    chat_history: list[dict[str, Any]],
    user_input: str,
    max_history_turns: int = 20,
    companionship_context: str = "",
    user_profile_context: str = "",
    companion_mode_instructions: str = "",
    lore_context: str = "",
    excluded_message_ids: set[int] | frozenset[int] | None = None,
) -> str:
    return PROMPT_TEMPLATE.format(
        name=character.name,
        role=character.role,
        personality=character.personality,
        speaking_style=character.speaking_style,
        relationship=character.relationship,
        forbidden=character.forbidden,
        user_profile_context=user_profile_context or "（尚未设置）",
        companion_mode_instructions=companion_mode_instructions or "日常陪伴模式",
        companionship_context=companionship_context or "（默认温柔陪伴中）",
        long_term_memory=long_term_memory or "（暂无长期记忆）",
        lore_context=lore_context or "（本轮未使用设定检索）",
        chat_history=format_chat_history(
            chat_history,
            max_history_turns,
            excluded_message_ids=excluded_message_ids,
        ),
        user_input=user_input,
    )
