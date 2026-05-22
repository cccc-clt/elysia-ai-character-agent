"""Streamlit UI — 爱莉希雅风格角色陪伴界面."""

from __future__ import annotations

import html
import json
from typing import Any

import streamlit as st

from pathlib import Path

from src.analytics_service import PlayerExperienceReport
from src.character_profile import CharacterProfile, parse_character_json
from src.companion_mode import MODES, get_current_mode
from src.companionship_service import CompanionshipState
from src.config import AppConfig, AssetConfig
from src.daily_companion_service import DailyCompanionView
from src.evaluator import ConsistencyEvaluation
from src.memory_service import MemoryStore
from src.user_profile_service import UserProfileService
from src.audio_clip_service import AudioClipService
from src.voice_service import VoiceService

# ---------------------------------------------------------------------------
# Theme & copy
# ---------------------------------------------------------------------------

WELCOME_CARD_TEXT = (
    "嗨，亲爱的朋友，今天也想和我聊聊吗？"
    "无论是开心的事，还是藏在心里的小情绪，我都会认真听着哦。"
)

PERSONALITY_TAGS = ["温柔", "浪漫", "俏皮", "陪伴感"]

DEFAULT_INTRO = (
    "逐火之蛾时代的英桀，以粉色为标志的「人之律者」——"
    "本 demo 为风格化 fan-made 角色 Agent，非官方产品。"
)

DISCLAIMER_FOOTER = (
    "本页面为 fan-made、非商业技术演示，与游戏官方无任何关联。"
    "生成内容仅供 AI 角色互动技术展示，请勿用于商业用途。"
)


def inject_theme() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Noto Sans SC', 'Segoe UI', sans-serif;
}

.stApp {
    background: linear-gradient(165deg, #fff5f8 0%, #fff9f5 35%, #fdf8ff 70%, #fff5fa 100%);
}

.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 920px;
}

/* Hide default header chrome */
header[data-testid="stHeader"] {
    background: transparent;
}

/* Sidebar — 角色名片 */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ffe8f0 0%, #fff5f8 45%, #fffaf7 100%);
    border-right: 1px solid rgba(255, 182, 193, 0.35);
}

section[data-testid="stSidebar"] .block-container {
    padding-top: 1.5rem;
}

/* Main nav radio as soft tabs */
div[data-testid="stRadio"] > div {
    gap: 0.35rem;
    background: rgba(255, 255, 255, 0.65);
    padding: 0.45rem;
    border-radius: 18px;
    border: 1px solid rgba(255, 192, 203, 0.45);
    box-shadow: 0 4px 18px rgba(255, 182, 193, 0.12);
}

div[data-testid="stRadio"] label {
    background: transparent !important;
    border-radius: 14px !important;
    padding: 0.45rem 1rem !important;
    font-weight: 500;
    color: #9a6b7a !important;
}

div[data-testid="stRadio"] label[data-baseweb="radio"] div:first-child {
    display: none;
}

div[data-testid="stRadio"] label:has(input:checked) {
    background: linear-gradient(135deg, #ffb7c5 0%, #ffc8dd 100%) !important;
    color: #5c3d4a !important;
    box-shadow: 0 2px 10px rgba(255, 150, 170, 0.35);
}

/* Buttons */
.stButton > button {
    border-radius: 14px;
    border: 1px solid rgba(255, 182, 193, 0.5);
    background: linear-gradient(135deg, #fff 0%, #ffe8f0 100%);
    color: #7d4a5c;
    font-weight: 500;
    transition: all 0.2s ease;
}

.stButton > button:hover {
    border-color: #ffb7c5;
    box-shadow: 0 4px 14px rgba(255, 150, 170, 0.25);
    color: #5c3d4a;
}

.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #ff9eb5 0%, #ffb8d0 50%, #ffc9a8 100%);
    color: #fff;
    border: none;
}

/* Chat input */
[data-testid="stChatInput"] textarea {
    border-radius: 20px !important;
    border: 1px solid rgba(255, 182, 193, 0.55) !important;
    background: rgba(255, 255, 255, 0.9) !important;
    padding: 0.75rem 1rem !important;
}

[data-testid="stChatInput"] {
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.5);
    padding: 0.25rem;
}

/* Metrics in lab */
[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.75);
    padding: 0.75rem;
    border-radius: 14px;
    border: 1px solid rgba(255, 192, 203, 0.35);
}

/* Expander */
.streamlit-expanderHeader {
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.5);
}

/* Download / file uploader in lab */
.stDownloadButton > button {
    border-radius: 14px;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _esc(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def _card(html_content: str, extra_class: str = "") -> None:
    st.markdown(
        f'<div class="ely-card {extra_class}">{html_content}</div>',
        unsafe_allow_html=True,
    )


def inject_card_styles() -> None:
    st.markdown(
        """
<style>
.ely-card {
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid rgba(255, 192, 203, 0.4);
    border-radius: 20px;
    padding: 1.1rem 1.25rem;
    margin-bottom: 1rem;
    box-shadow: 0 8px 28px rgba(255, 160, 180, 0.12);
    line-height: 1.65;
    color: #5c4a52;
}
.ely-card--welcome {
    background: linear-gradient(135deg, rgba(255,240,245,0.95) 0%, rgba(255,250,240,0.92) 100%);
    border-color: rgba(255, 200, 180, 0.5);
}
.ely-card--memory-snippet {
    font-size: 0.92rem;
    color: #7a5c68;
}
.ely-hero-title {
    font-size: 2.1rem;
    font-weight: 600;
    color: #c45c7a;
    margin: 0 0 0.15rem 0;
    letter-spacing: 0.06em;
}
.ely-hero-sub {
    font-size: 1.05rem;
    color: #b07a8a;
    margin: 0 0 0.5rem 0;
    font-weight: 400;
}
.ely-hero-desc {
    font-size: 0.88rem;
    color: #9a7a86;
    margin: 0;
}
.ely-footer {
    text-align: center;
    font-size: 0.78rem;
    color: #b8a0aa;
    padding: 1.5rem 1rem 0.5rem;
    margin-top: 2rem;
    border-top: 1px solid rgba(255, 192, 203, 0.25);
}
.ely-avatar-ring {
    width: 88px;
    height: 88px;
    border-radius: 50%;
    background: linear-gradient(145deg, #ffb7c5, #ffe4ec, #ffd4a8);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2.4rem;
    margin: 0 auto 0.75rem;
    box-shadow: 0 6px 20px rgba(255, 150, 170, 0.35);
    border: 3px solid rgba(255, 255, 255, 0.9);
}
.ely-sidebar-name {
    text-align: center;
    font-size: 1.35rem;
    font-weight: 600;
    color: #c45c7a;
    margin: 0 0 0.35rem 0;
}
.ely-sidebar-intro {
    text-align: center;
    font-size: 0.8rem;
    color: #8a6b76;
    line-height: 1.5;
    margin-bottom: 0.75rem;
}
.ely-tag {
    display: inline-block;
    padding: 0.2rem 0.65rem;
    margin: 0.15rem 0.2rem;
    border-radius: 999px;
    font-size: 0.75rem;
    background: rgba(255, 255, 255, 0.85);
    border: 1px solid rgba(255, 182, 193, 0.55);
    color: #a65d72;
}
.ely-status {
    text-align: center;
    font-size: 0.82rem;
    color: #b8869a;
    font-style: italic;
    margin: 0.75rem 0 1rem;
    padding: 0.5rem;
    background: rgba(255,255,255,0.5);
    border-radius: 12px;
}
.ely-bubble-row {
    display: flex;
    margin-bottom: 0.85rem;
    align-items: flex-start;
    gap: 0.5rem;
}
.ely-bubble-row.user {
    flex-direction: row-reverse;
}
.ely-bubble-avatar {
    flex-shrink: 0;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.1rem;
}
.ely-bubble-avatar.assistant {
    background: linear-gradient(135deg, #ffe0ec, #ffd4e8);
}
.ely-bubble-avatar.user {
    background: linear-gradient(135deg, #e8f0ff, #f0e8ff);
}
.ely-bubble {
    max-width: 78%;
    padding: 0.75rem 1rem;
    border-radius: 18px;
    font-size: 0.95rem;
    line-height: 1.6;
    word-wrap: break-word;
}
.ely-bubble.assistant {
    background: linear-gradient(135deg, #fff5f8 0%, #ffeef5 100%);
    border: 1px solid rgba(255, 192, 203, 0.45);
    color: #5c4a52;
    border-bottom-left-radius: 6px;
}
.ely-bubble.user {
    background: linear-gradient(135deg, #f8f0ff 0%, #f0f4ff 100%);
    border: 1px solid rgba(200, 180, 255, 0.35);
    color: #4a4558;
    border-bottom-right-radius: 6px;
}
.ely-section-title {
    font-size: 1rem;
    font-weight: 600;
    color: #c45c7a;
    margin: 1rem 0 0.5rem;
}
.ely-lab-header {
    font-size: 1.15rem;
    color: #9a5d72;
    margin-bottom: 0.25rem;
}
.ely-metric-label {
    font-size: 0.8rem;
    color: #9a7a86;
}
</style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Session & layout
# ---------------------------------------------------------------------------


def resolve_asset(path: Path) -> Path | None:
    if path and path.exists() and path.is_file():
        return path
    return None


def render_asset_image(path: Path | None, width: int | None = None, caption: str = "") -> bool:
    if path:
        st.image(str(path), width=width, caption=caption or None)
        return True
    return False


def render_hero_visual(assets: AssetConfig) -> None:
    portrait = resolve_asset(assets.portrait)
    background = resolve_asset(assets.background)
    if background:
        st.image(str(background), use_container_width=True)
    elif portrait:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(str(portrait), use_container_width=True)
    else:
        st.markdown(
            """
<div style="height:120px;border-radius:20px;margin-bottom:1rem;
background:linear-gradient(135deg,#ffe8f0,#fff5e8,#f3e8ff);
display:flex;align-items:center;justify-content:center;font-size:3rem;">
🌸
</div>
            """,
            unsafe_allow_html=True,
        )


def init_session_state(character: CharacterProfile) -> None:
    defaults: dict[str, Any] = {
        "messages": [],
        "last_evaluation": None,
        "last_analytics": None,
        "character": character,
        "main_nav": "聊天",
        "last_assistant_reply": "",
        "greeting_marked": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_page_header() -> None:
    st.markdown(
        """
<div style="margin-bottom: 0.5rem;">
  <p class="ely-hero-title">爱莉希雅</p>
  <p class="ely-hero-sub">今天也想和我聊聊吗？</p>
  <p class="ely-hero-desc">一个 fan-made non-commercial 的角色陪伴互动 Demo，用于展示 AI 角色对话、长期记忆和互动体验分析能力。</p>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_main_nav() -> str:
    options = ["聊天", "记忆", "我们的回忆", "角色档案", "语音", "实验室"]
    current = st.session_state.get("main_nav", "聊天")
    if current not in options:
        current = "聊天"

    choice = st.radio(
        "主导航",
        options,
        index=options.index(current),
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav_radio",
    )
    st.session_state["main_nav"] = choice
    return choice


def render_sidebar(
    character: CharacterProfile,
    *,
    assets: AssetConfig,
    companionship: CompanionshipState | None = None,
    db=None,
    on_clear_chat,
    on_go_profile,
    on_go_lab,
    on_mode_change=None,
) -> None:
    with st.sidebar:
        avatar_path = resolve_asset(assets.avatar) or resolve_asset(assets.portrait)
        if avatar_path:
            st.image(str(avatar_path), width=88)
        else:
            st.markdown('<div class="ely-avatar-ring">🌸</div>', unsafe_allow_html=True)

        mood = companionship.mood if companionship else "温柔"
        intimacy = companionship.intimacy_score if companionship else 20
        stage = companionship.relationship_stage if companionship else "初识"

        st.markdown(
            f"""
<p class="ely-sidebar-name">{_esc(character.name)}</p>
<p class="ely-sidebar-intro">{_esc(character.role if len(character.role) < 120 else DEFAULT_INTRO)}</p>
<div style="text-align:center;">
  {''.join(f'<span class="ely-tag">{_esc(t)}</span>' for t in PERSONALITY_TAGS)}
</div>
<p class="ely-status">心情：{_esc(mood)} · {_esc(stage)}</p>
            """,
            unsafe_allow_html=True,
        )
        st.progress(intimacy / 100, text=f"亲密度 {intimacy}/100")

        if db is not None:
            current_mode = get_current_mode(db)
            new_mode = st.selectbox(
                "此刻的陪伴方式",
                MODES,
                index=MODES.index(current_mode) if current_mode in MODES else 0,
                key="companion_mode_select",
            )
            if new_mode != current_mode and on_mode_change:
                on_mode_change(new_mode)

        if character.role and len(character.role) >= 120:
            with st.expander("角色简介", expanded=False):
                st.caption(character.role)

        st.divider()

        if st.button("清空当前对话", use_container_width=True, key="sb_clear_chat"):
            on_clear_chat()

        if st.button("查看角色档案", use_container_width=True, key="sb_profile"):
            on_go_profile()

        if st.button("打开实验室", use_container_width=True, key="sb_lab"):
            on_go_lab()

        st.divider()

        with st.expander("性格与风格", expanded=False):
            st.markdown(f"**性格**  \n{character.personality}")
            st.markdown(f"**说话风格**  \n{character.speaking_style}")
            st.markdown(f"**与玩家关系**  \n{character.relationship}")

        with st.expander("禁止事项", expanded=False):
            st.caption(character.forbidden)

        with st.expander("关于项目", expanded=False):
            st.caption(DISCLAIMER_FOOTER)


def render_footer() -> None:
    st.markdown(f'<p class="ely-footer">{_esc(DISCLAIMER_FOOTER)}</p>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Chat experience
# ---------------------------------------------------------------------------


def render_welcome_card() -> None:
    _card(
        f'<p style="margin:0;color:#7d5a68;font-size:0.98rem;">🌸 {_esc(WELCOME_CARD_TEXT)}</p>',
        extra_class="ely-card--welcome",
    )


def render_memory_snippet(memory: MemoryStore) -> None:
    if memory.summary:
        text = memory.summary
    elif memory.preferences or memory.nicknames:
        parts = []
        if memory.nicknames:
            parts.append(f"我会记得叫你：{'、'.join(memory.nicknames[:2])}")
        if memory.preferences:
            parts.append(f"你提到过：{memory.preferences[0]}")
        text = " · ".join(parts)
    else:
        return

    _card(
        f'<p style="margin:0;"><span style="color:#c45c7a;font-weight:500;">💭 她记得的事</span><br>'
        f'<span style="font-size:0.9rem;">{_esc(text[:200])}</span></p>',
        extra_class="ely-card--memory-snippet",
    )


def render_chat_messages(
    messages: list[dict[str, Any]],
    *,
    show_feedback: bool = False,
    last_user_snippet: str = "",
    voice: VoiceService | None = None,
) -> dict[str, Any] | None:
    """Returns action dict if a button was clicked (feedback or TTS)."""
    action: dict[str, Any] | None = None
    prev_user = last_user_snippet
    voice_on = voice is not None and voice.is_enabled

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            prev_user = content
            row_class = "user"
            avatar = "🧑"
            bubble_class = "user"
        else:
            row_class = "assistant"
            avatar = "🌸"
            bubble_class = "assistant"

        st.markdown(
            f"""
<div class="ely-bubble-row {row_class}">
  <div class="ely-bubble-avatar {bubble_class}">{avatar}</div>
  <div class="ely-bubble {bubble_class}">{_esc(content)}</div>
</div>
            """,
            unsafe_allow_html=True,
        )

        if role == "assistant":
            conv_id = msg.get("id")
            out_audio = (msg.get("output_audio_path") or "").strip()
            if voice_on and conv_id is not None:
                if out_audio and Path(out_audio).is_file():
                    st.audio(out_audio)
                else:
                    if st.button("生成语音", key=f"tts_gen_{conv_id}"):
                        action = {
                            "type": "generate_tts",
                            "conv_id": conv_id,
                            "content": content,
                        }
                played = st.session_state.get(f"tts_play_{conv_id}")
                if played and Path(played).is_file():
                    st.audio(played)

            if show_feedback and conv_id is not None:
                c1, c2, c3, c4 = st.columns(4)
                if c1.button("喜欢", key=f"fb_like_{conv_id}"):
                    action = {
                        "type": "like",
                        "conv_id": conv_id,
                        "user": prev_user,
                        "reply": content,
                    }
                if c2.button("不像她", key=f"fb_ooc_{conv_id}"):
                    action = {
                        "type": "out_of_character",
                        "conv_id": conv_id,
                        "user": prev_user,
                        "reply": content,
                    }
                if c3.button("重新生成", key=f"fb_regen_{conv_id}"):
                    action = {"type": "regenerate", "conv_id": conv_id}
                if c4.button("记住这段", key=f"fb_remember_{conv_id}"):
                    action = {"type": "remember", "reply": content}
    return action


def render_status_card(
    comp: CompanionshipState,
    summary: dict[str, str],
    daily: DailyCompanionView | None = None,
) -> None:
    streak = daily.streak_days if daily else "—"
    greeting = daily.greeting if daily else (comp.daily_greeting if comp.show_greeting else "")
    note = daily.little_note if daily else ""

    _card(
        f"""
<p style="margin:0;color:#c45c7a;font-weight:600;">角色状态</p>
<p style="margin:0.35rem 0 0;font-size:0.88rem;color:#7d5a68;">
心情 <strong>{_esc(comp.mood)}</strong> · 关系 <strong>{_esc(comp.relationship_stage)}</strong> · 亲密度 <strong>{comp.intimacy_score}</strong>/100 · 已连续陪伴 <strong>{streak}</strong> 天
</p>
<p style="margin:0.35rem 0 0;color:#b07a8a;font-size:0.88rem;">今日问候：{_esc(greeting)}</p>
<p style="margin:0.25rem 0 0;color:#b07a8a;font-size:0.85rem;">今日小纸条：{_esc(note)}</p>
<p style="margin:0.5rem 0 0;font-size:0.85rem;color:#9a7a86;">她记得：{_esc(summary.get('remembered', '')[:80])}</p>
        """,
        extra_class="ely-card--welcome",
    )


def render_chat_page(
    messages: list[dict[str, Any]],
    memory: MemoryStore,
    character_name: str,
    *,
    assets: AssetConfig | None = None,
    companionship: CompanionshipState | None = None,
    comp_summary: dict[str, str] | None = None,
    daily: DailyCompanionView | None = None,
    show_feedback: bool = False,
    voice: VoiceService | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Returns (chat_input, action)."""
    if assets:
        render_hero_visual(assets)
    render_welcome_card()
    if companionship and comp_summary:
        render_status_card(companionship, comp_summary, daily)
    render_memory_snippet(memory)
    last_user = ""
    for m in messages:
        if m.get("role") == "user":
            last_user = m.get("content", "")
    action = render_chat_messages(
        messages,
        show_feedback=show_feedback,
        last_user_snippet=last_user,
        voice=voice,
    )

    user_input = st.chat_input(
        "发送给爱莉希雅…",
        key="chat_input_main",
    )
    return user_input, action


# ---------------------------------------------------------------------------
# Memory tab
# ---------------------------------------------------------------------------


def render_memory_page(
    memory: MemoryStore,
    memory_text: str,
    relationship_stage: str = "",
    pending_list: list[dict[str, Any]] | None = None,
    confirmed_list: list[dict[str, Any]] | None = None,
    using_sqlite: bool = True,
) -> dict[str, Any]:
    """Returns action dict: summarize, clear_mem, pending_confirm/reject/edit, delete_id."""
    result: dict[str, Any] = {}
    st.markdown('<p class="ely-section-title">💭 她对你的记忆</p>', unsafe_allow_html=True)

    pending_list = pending_list or []
    if pending_list:
        st.markdown("**爱莉希雅想记住这些事情**")
        for p in pending_list:
            pid = p["id"]
            _card(
                f"<p style='margin:0;color:#7d5a68;'><strong>{_esc(p.get('memory_type',''))}</strong> · "
                f"{_esc(p.get('content',''))}</p>"
            )
            e1, e2, e3 = st.columns([1, 1, 2])
            if e1.button("记住", key=f"p_ok_{pid}"):
                result["pending_confirm"] = pid
            if e2.button("不记住", key=f"p_no_{pid}"):
                result["pending_reject"] = pid
            edited = e3.text_input("编辑后记住", value=p.get("content", ""), key=f"p_edit_{pid}")
            if e3.button("保存并记住", key=f"p_save_{pid}"):
                result["pending_edit"] = (pid, edited)
    elif not using_sqlite:
        st.caption("记忆确认功能需要 SQLite 存储。当前为 JSON 模式。")

    st.markdown("**她已记住的事**")
    if memory.summary:
        _card(f"<p style='margin:0;'>{_esc(memory.summary)}</p>")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**用户偏好**")
        if memory.preferences:
            for p in memory.preferences:
                st.markdown(f"- {p}")
        else:
            st.caption("还没有记录偏好")

    with col2:
        st.markdown("**你的称呼**")
        if memory.nicknames:
            for n in memory.nicknames:
                st.markdown(f"- {n}")
        else:
            st.caption("还没有记录称呼")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**重要的事**")
        if memory.important_events:
            for e in memory.important_events:
                st.markdown(f"- {e}")
        else:
            st.caption("还没有重要事件")

    with col4:
        st.markdown("**情绪印记**")
        if memory.emotional_states:
            for s in memory.emotional_states:
                st.markdown(f"- {s}")
        else:
            st.caption("还没有情绪记录")

    if memory.relationships:
        st.markdown("**关系变化**")
        for r in memory.relationships:
            st.markdown(f"- {r}")

    if relationship_stage:
        st.markdown(f"**你们的关系阶段（陪伴系统）**：{relationship_stage}")

    if memory.turn_count:
        st.caption(f"已共同对话 {memory.turn_count} 轮 · 上次整理：{memory.last_summarized_at or '尚未'}")

    with st.expander("查看完整记忆文本", expanded=False):
        st.text_area("完整记忆", value=memory_text, height=160, disabled=True, label_visibility="collapsed")

    if confirmed_list:
        with st.expander("管理已确认记忆", expanded=False):
            for m in confirmed_list:
                mid = m.get("id")
                st.caption(f"[{m.get('memory_type')}] {m.get('content')}")
                if mid and st.button("删除", key=f"del_mem_{mid}"):
                    result["delete_id"] = mid

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("请她整理记忆", use_container_width=True, key="mem_summarize"):
        result["summarize"] = True
    if c2.button("清空长期记忆", use_container_width=True, key="mem_clear"):
        result["clear_mem"] = True
    return result


# ---------------------------------------------------------------------------
# Profile tab
# ---------------------------------------------------------------------------


def render_profile_page(character: CharacterProfile) -> None:
    st.markdown('<p class="ely-section-title">📖 角色档案</p>', unsafe_allow_html=True)

    _card(
        f"""
<p style="margin:0 0 0.5rem 0;"><strong style="color:#c45c7a;">{ _esc(character.name) }</strong></p>
<p style="margin:0;font-size:0.9rem;color:#8a6b76;">{ _esc(character.role) }</p>
        """
    )

    st.markdown("**性格特征**")
    st.info(character.personality)

    st.markdown("**说话风格**")
    st.info(character.speaking_style)

    st.markdown("**与玩家的关系**")
    st.info(character.relationship)

    with st.expander("开场白", expanded=False):
        st.write(character.opening_message)

    with st.expander("创作边界（禁止事项）", expanded=False):
        st.caption(character.forbidden)


# ---------------------------------------------------------------------------
# Laboratory
# ---------------------------------------------------------------------------


def render_character_card_io(character: CharacterProfile) -> CharacterProfile | None:
    st.markdown('<p class="ely-lab-header">角色卡管理</p>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        st.download_button(
            label="导出角色卡 JSON",
            data=character.to_json(),
            file_name=f"{character.name}_character.json",
            mime="application/json",
            use_container_width=True,
        )

    with col2:
        if st.button("重置为默认角色卡", use_container_width=True, key="reset_char"):
            st.session_state["reload_default_character"] = True

    uploaded = st.file_uploader("导入角色卡 JSON", type=["json"], key="char_upload")
    if uploaded is not None:
        try:
            raw = uploaded.read().decode("utf-8")
            return parse_character_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            st.error(f"导入失败：{exc}")

    return None


def render_evaluation(evaluation: ConsistencyEvaluation | None) -> None:
    st.markdown('<p class="ely-lab-header">角色一致性评估</p>', unsafe_allow_html=True)
    if evaluation is None:
        st.info("在「聊天」中发送消息后，将在此自动评估最近一轮角色回复。")
        return

    cols = st.columns(5)
    labels = [
        ("人格一致性", evaluation.personality_score),
        ("语气一致性", evaluation.tone_score),
        ("记忆使用", evaluation.memory_usage_score),
        ("情绪回应", evaluation.emotional_response_score),
        ("沉浸感", evaluation.immersion_score),
    ]
    for col, (label, score) in zip(cols, labels):
        col.metric(label, f"{score}")

    _card(
        f"<p style='margin:0;'><strong>综合 {evaluation.overall_score}</strong> · "
        f"<span style='color:#c45c7a;'>{_esc(evaluation.verdict)}</span> · "
        f"{_esc(evaluation.comment)}</p>"
    )


def render_evaluation_history(eval_summary: dict[str, Any]) -> None:
    if not eval_summary:
        return
    averages = eval_summary.get("averages") or {}
    if averages:
        st.caption(
            "历史平均 — "
            + " · ".join(f"{k}: {v}" for k, v in averages.items())
        )
    latest = eval_summary.get("latest")
    if latest:
        st.caption(
            f"最近一次综合 {latest.get('overall_score', '—')} · {latest.get('verdict', '')}"
        )


def render_analytics(report: PlayerExperienceReport | None) -> bool:
    """Returns True if user clicked generate."""
    st.markdown('<p class="ely-lab-header">玩家体验分析</p>', unsafe_allow_html=True)

    generate = st.button("生成体验分析报告", type="primary", key="run_analytics")

    if report is None:
        if not generate:
            st.caption("完成几轮对话后，可在此生成互动体验分析。")
        return generate

    items = [
        ("用户互动类型", report.interaction_type),
        ("偏好的角色回应风格", report.preferred_response_style),
        ("用户关注内容", report.content_focus),
        ("情绪倾向", report.emotional_tendency),
        ("亲密度变化原因", report.intimacy_change_reason),
        ("潜在留存价值", report.retention_value),
        ("下一步互动建议", report.next_interaction_advice),
        ("当前体验总结", report.experience_summary),
    ]
    for title, body in items:
        _card(f"<p style='margin:0 0 0.35rem 0;color:#c45c7a;font-weight:600;'>{_esc(title)}</p><p style='margin:0;font-size:0.92rem;'>{_esc(body)}</p>")

    return generate


def render_lab_config(config: AppConfig) -> None:
    st.markdown('<p class="ely-lab-header">模型与配置</p>', unsafe_allow_html=True)

    api_ok = bool(config.llm.api_key)
    status = "已配置 ✓" if api_ok else "未配置 — 请在 .env 或 Secrets 中设置 API_KEY"
    status_color = "#6b9e7a" if api_ok else "#c45c7a"

    _card(
        f"""
<p style="margin:0 0 0.5rem 0;"><span style="color:#9a7a86;">API 状态</span> ·
<span style="color:{status_color};font-weight:500;">{_esc(status)}</span></p>
<p style="margin:0;font-size:0.88rem;color:#8a6b76;">
模型：<strong>{_esc(config.llm.model_name)}</strong><br>
接口：<strong>{_esc(config.llm.base_url)}</strong><br>
temperature：<strong>{config.llm.temperature}</strong> ·
max_tokens：<strong>{config.llm.max_tokens}</strong><br>
记忆自动整理：每 <strong>{config.memory_summarize_interval}</strong> 轮
</p>
        """
    )

    if not api_ok:
        st.warning("未检测到 API_KEY。配置后重启应用即可与角色对话。")

    st.caption(f"语音：{'已开启' if config.voice.enabled else '未开启'} · 存储：{config.storage.backend}")


def render_lab_db_status(db_stats: dict[str, Any], memory_backend: str) -> None:
    st.markdown('<p class="ely-lab-header">数据库状态</p>', unsafe_allow_html=True)
    _card(
        f"""
<p style="margin:0;font-size:0.88rem;color:#8a6b76;">
路径：<code>{_esc(str(db_stats.get('database_path', '—')))}</code><br>
存储模式：<strong>{_esc(memory_backend)}</strong><br>
聊天记录：<strong>{db_stats.get('conversations', 0)}</strong> 条<br>
记忆条目：<strong>{db_stats.get('memories', 0)}</strong> 条<br>
评估记录：<strong>{db_stats.get('evaluations', 0)}</strong> 条<br>
语音日志：<strong>{db_stats.get('voice_logs', 0)}</strong> 条<br>
当前亲密度：<strong>{db_stats.get('intimacy_score', 20)}</strong> · { _esc(str(db_stats.get('relationship_stage', ''))) }
</p>
        """
    )


def _has_audio_input() -> bool:
    return hasattr(st, "audio_input")


def render_voice_page(
    voice: VoiceService,
    last_reply: str,
    clip_svc: AudioClipService,
    config: AppConfig,
) -> dict[str, Any] | None:
    st.markdown('<p class="ely-section-title">语音陪伴</p>', unsafe_allow_html=True)

    if not voice.is_enabled:
        st.info(
            "语音功能未开启。在 `.env` 设置 `ENABLE_VOICE=true` 后可使用语音转写与回复朗读。"
            "语音为通用 TTS 风格，不代表官方配音。"
        )
        return None

    # --- 1. 语音输入 ---
    st.markdown("**语音输入**")
    st.caption("录制或上传 wav / mp3 / m4a，转写后可确认发送给爱莉希雅。")

    audio_bytes: bytes | None = None
    suffix = ".wav"

    if _has_audio_input():
        recorded = st.audio_input("录制语音", key="voice_audio_input")
        if recorded is not None:
            audio_bytes = recorded.getvalue()
            suffix = ".wav"
    else:
        st.caption("当前 Streamlit 版本不支持内置录音，请使用上传音频。")

    uploaded = st.file_uploader(
        "上传音频文件",
        type=["wav", "mp3", "m4a", "ogg", "webm"],
        key="voice_file_upload",
    )
    if uploaded is not None:
        audio_bytes = uploaded.getvalue()
        suffix = Path(uploaded.name).suffix or ".wav"

    pending = st.session_state.get("voice_pending_transcript")
    if audio_bytes and st.button("开始转写", key="voice_do_stt"):
        with st.spinner("正在转写语音…"):
            text, err, in_path = voice.transcribe_audio(audio_bytes, suffix)
        if err:
            st.warning(err)
            st.session_state.pop("voice_pending_transcript", None)
        elif text:
            st.session_state["voice_pending_transcript"] = {
                "text": text,
                "input_audio_path": str(in_path) if in_path else "",
            }
            pending = st.session_state["voice_pending_transcript"]

    if pending:
        st.success(f"转写结果：{pending.get('text', '')}")
        if st.button("发送给爱莉希雅", type="primary", key="voice_confirm_send"):
            result = {
                "text": pending["text"],
                "input_audio_path": pending.get("input_audio_path", ""),
            }
            st.session_state.pop("voice_pending_transcript", None)
            return result

    st.divider()

    # --- 2. TTS / STT 状态 ---
    st.markdown("**语音服务状态**")
    status = voice.check_tts_status()
    st.markdown(
        f"""
| 项目 | 值 |
|------|-----|
| STT | `{status.get('stt_provider', '')}` |
| TTS | `{status.get('tts_provider', '')}` |
| Fallback TTS | `{status.get('tts_fallback_provider', '')}` |
| GPT-SoVITS URL | `{status.get('gpt_sovits_url', '')}` |
| GPT-SoVITS 在线 | {'是' if status.get('gpt_sovits_online') else '否'} |
| edge-tts | {'可用' if status.get('edge_tts_available') else '未安装'} |
        """
    )
    if status.get("gpt_sovits_message") and not status.get("gpt_sovits_online"):
        st.warning(status["gpt_sovits_message"])

    st.divider()

    # --- 3. GPT-SoVITS 测试 ---
    st.markdown("**GPT-SoVITS 测试**")
    test_text = "嗨，亲爱的朋友，今天也想和我聊聊吗？"
    c1, c2 = st.columns(2)
    if c1.button("检测 GPT-SoVITS 服务", key="voice_check_sovits"):
        s = voice.check_tts_status()
        if s.get("gpt_sovits_online"):
            st.success(s.get("gpt_sovits_message", "服务在线"))
        else:
            st.warning(s.get("gpt_sovits_message", "未检测到服务"))
    if c2.button("测试生成一句语音", key="voice_test_sovits"):
        with st.spinner("正在生成测试语音…"):
            path, err, _ = voice.text_to_speech(test_text)
        if err:
            st.warning(err)
        elif path:
            st.audio(str(path))

    st.divider()

    # --- 4. 官方语音片段 ---
    st.markdown("**官方语音片段（本地）**")
    if clip_svc.is_enabled:
        counts = clip_svc.count_clips()
        total = clip_svc.total_clips()
        st.caption(f"本地已登记片段：共 {total} 条")
        if total == 0:
            st.info(
                "尚未配置本地片段。请将 wav/mp3/ogg/m4a 放入 assets/audio/clips/ "
                "或编辑该目录下的 official_clips.json。仓库不包含官方语音素材。"
            )
        else:
            for scene in ("greeting", "comfort", "happy"):
                n = counts.get(scene, 0)
                col_a, col_b = st.columns([2, 1])
                col_a.caption(f"{scene}：{n} 条")
                if col_b.button(f"试听 {scene}", key=f"clip_test_{scene}") and n > 0:
                    clip = clip_svc.pick_clip(scene)
                    if clip:
                        st.audio(str(clip))
    else:
        st.caption("官方片段功能已关闭（ENABLE_OFFICIAL_CLIPS=false）")

    st.divider()

    # --- 5. 缓存管理 ---
    st.markdown("**语音缓存**")
    cache_dir = config.voice.audio_cache_dir
    n_files = voice.count_cache_files()
    st.caption(f"目录：`{cache_dir}` · 文件数：{n_files}")
    if st.button("一键清理缓存", key="voice_clear_cache"):
        removed, path = voice.clear_audio_cache()
        st.success(f"已清理 {removed} 个文件（{path}）")

    st.divider()
    if last_reply:
        if st.button("朗读最新回复", type="secondary", key="tts_last"):
            path, err = voice.synthesize_reply(last_reply)
            if err:
                st.warning(err)
            elif path:
                st.audio(str(path))
    else:
        st.caption("先在「聊天」中收到回复后，可在此朗读最新回复。")

    return None


def render_lab_page(
    character: CharacterProfile,
    config: AppConfig,
    evaluation: ConsistencyEvaluation | None,
    report: PlayerExperienceReport | None,
    *,
    db_stats: dict[str, Any] | None = None,
    eval_summary: dict[str, Any] | None = None,
    memory_backend: str = "sqlite",
) -> CharacterProfile | None:
    st.markdown(
        '<p style="color:#9a7a86;font-size:0.9rem;margin-bottom:1rem;">'
        "🔬 实验室 — 开发者与调试功能集中在此，不影响日常聊天体验。</p>",
        unsafe_allow_html=True,
    )

    imported = render_character_card_io(character)

    st.divider()
    render_evaluation(evaluation)
    render_evaluation_history(eval_summary or {})

    st.divider()
    run_analytics = render_analytics(report)

    st.divider()
    if db_stats:
        render_lab_db_status(db_stats, memory_backend)
        fb = db_stats.get("feedback")
        if fb:
            render_feedback_stats(fb)

    st.divider()
    render_lab_config(config)

    with st.expander("调试信息", expanded=False):
        st.json(
            {
                "storage_backend": config.storage.backend,
                "voice_enabled": config.voice.enabled,
                "sqlite_path": str(config.storage.database_path),
            }
        )

    if run_analytics:
        st.session_state["_lab_run_analytics"] = True

    return imported


def render_onboarding(profile_svc: UserProfileService) -> bool:
    """Returns True when onboarding submitted."""
    st.markdown('<p class="ely-hero-title">欢迎来到爱莉希雅的世界</p>', unsafe_allow_html=True)
    st.caption("先让我认识一下你，这样陪伴会更贴心哦。")

    with st.form("onboarding_form"):
        name = st.text_input("你希望我怎么称呼你？", placeholder="例如：旅行者、朋友")
        mode = st.selectbox("今天想要哪种陪伴？", MODES, index=0)
        style = st.radio("你喜欢怎样的回复？", ["细腻", "简短"], horizontal=True)
        remember = st.checkbox("记住这些偏好（可在记忆页确认）", value=True)
        submitted = st.form_submit_button("开始陪伴之旅", type="primary")

    if submitted:
        profile_svc.save_onboarding(name, mode, style, remember)
        return True
    return False


def render_recalls_page(
    timeline: list[dict[str, str]],
    reflections: list[dict[str, Any]],
    today_reflection: dict | None,
    *,
    can_generate: bool,
    generate_clicked: bool = False,
) -> bool:
    st.markdown('<p class="ely-section-title">我们的回忆</p>', unsafe_allow_html=True)

    if timeline:
        st.markdown("**关系时间线**")
        for item in timeline:
            _card(
                f"<p style='margin:0;'><strong>{_esc(item.get('title',''))}</strong> "
                f"<span style='color:#b8a0aa;font-size:0.8rem;'>{_esc(item.get('time',''))}</span></p>"
                f"<p style='margin:0.35rem 0 0;font-size:0.9rem;'>{_esc(item.get('description',''))}</p>"
            )
    else:
        st.caption("随着你们的互动，这里会慢慢留下足迹。")

    st.divider()
    st.markdown("**今日回忆**")
    if today_reflection:
        _card(f"<p style='margin:0;'>{_esc(today_reflection.get('content',''))}</p>")

    if can_generate:
        return st.button("生成今日回忆", type="primary", key="gen_reflection")
    st.caption("配置 API_KEY 后，可根据今日真实对话生成温柔回忆总结。")
    return generate_clicked


def render_feedback_stats(stats: dict[str, Any]) -> None:
    st.markdown('<p class="ely-lab-header">回复反馈统计</p>', unsafe_allow_html=True)
    if not stats or stats.get("total_count", 0) == 0:
        st.caption("暂无反馈数据。在聊天中对回复点赞或标记「不像她」后可见统计。")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("喜欢", stats.get("like_count", 0))
    c2.metric("不像她", stats.get("out_of_character_count", 0))
    c3.metric("满意度", f"{stats.get('satisfaction_pct', 0)}%")
    samples = stats.get("ooc_samples") or []
    if samples:
        with st.expander("「不像她」样本（供 Prompt 优化参考）"):
            for s in samples:
                st.caption(s)


def render_api_banner(config: AppConfig) -> None:
    if not config.llm.api_key:
        st.markdown(
            """
<div style="background:rgba(255,230,240,0.9);border:1px solid rgba(255,150,170,0.4);
border-radius:14px;padding:0.75rem 1rem;margin-bottom:1rem;color:#8a4a5a;font-size:0.9rem;">
  🌸 还差一点点哦：请配置 <code>API_KEY</code> 后重启，爱莉希雅才能回应你。
</div>
            """,
            unsafe_allow_html=True,
        )
