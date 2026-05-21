"""Elysia AI Character Agent V3 — Streamlit entry point."""

from __future__ import annotations

import streamlit as st

from src.analytics_service import analyze_player_experience
from src.character_profile import load_character
from src.companion_mode import get_mode_instructions, set_mode
from src.companionship_service import CompanionshipService, LOW_KEYWORDS
from src.config import ensure_data_dirs, get_config
from src.daily_companion_service import DailyCompanionService
from src.database import Database
from src.evaluator import evaluate_reply, get_evaluation_summary
from src.feedback_service import FeedbackService
from src.llm_client import LLMClient
from src.memory_service import MemoryService
from src.prompt_builder import build_system_prompt
from src.reflection_service import ReflectionService
from src.relationship_event_service import RelationshipEventService
from src.user_profile_service import UserProfileService
from src.voice_service import VoiceService
from src.ui import (
    init_session_state,
    inject_card_styles,
    inject_theme,
    render_api_banner,
    render_chat_page,
    render_footer,
    render_lab_page,
    render_main_nav,
    render_memory_page,
    render_onboarding,
    render_page_header,
    render_profile_page,
    render_recalls_page,
    render_sidebar,
    render_voice_page,
)

st.set_page_config(
    page_title="爱莉希雅 · 角色陪伴",
    page_icon="🌸",
    layout="wide",
    initial_sidebar_state="expanded",
)

ensure_data_dirs()
config = get_config()

inject_theme()
inject_card_styles()


@st.cache_resource
def get_database() -> Database:
    db = Database(config.storage.database_path)
    db.init_schema()
    if config.storage.backend == "sqlite":
        db.migrate_from_json(config.storage.memory_store_path, config.storage.chat_logs_path)
    return db


@st.cache_resource
def get_llm_client() -> LLMClient:
    return LLMClient(config.llm)


@st.cache_resource
def get_memory_service() -> MemoryService:
    db = get_database() if config.storage.backend == "sqlite" else None
    return MemoryService(config, db)


@st.cache_resource
def get_companionship_service() -> CompanionshipService:
    return CompanionshipService(get_database())


@st.cache_resource
def get_profile_service() -> UserProfileService:
    return UserProfileService(get_database())


@st.cache_resource
def get_daily_service() -> DailyCompanionService:
    return DailyCompanionService(get_database())


@st.cache_resource
def get_event_service() -> RelationshipEventService:
    return RelationshipEventService(get_database())


def get_feedback_service() -> FeedbackService:
    return FeedbackService(get_database())


def get_reflection_service() -> ReflectionService:
    return ReflectionService(get_database())


def load_default_character():
    return load_character(config.default_character_path)


def _ensure_messages(memory_service: MemoryService) -> list[dict]:
    if not st.session_state["messages"]:
        restored = memory_service.get_session_messages_with_ids()
        if restored:
            st.session_state["messages"] = restored
        else:
            opening = st.session_state["character"].opening_message
            st.session_state["messages"] = [{"role": "assistant", "content": opening}]
    return st.session_state["messages"]


def _clear_chat(memory_service: MemoryService) -> None:
    st.session_state["messages"] = []
    memory_service.clear_session_chat()
    opening = st.session_state["character"].opening_message
    st.session_state["messages"] = [{"role": "assistant", "content": opening}]
    st.session_state["last_evaluation"] = None
    st.session_state["last_assistant_reply"] = ""
    st.rerun()


def main() -> None:
    if st.session_state.get("reload_default_character"):
        st.session_state.pop("reload_default_character", None)
        st.session_state["character"] = load_default_character()
        st.session_state["messages"] = []
        st.rerun()

    character = st.session_state.get("character") or load_default_character()
    init_session_state(character)

    db = get_database()
    profile_svc = get_profile_service()

    if not profile_svc.is_onboarding_done():
        if render_onboarding(profile_svc):
            st.rerun()
        render_footer()
        return

    memory_service = get_memory_service()
    companionship_svc = get_companionship_service()
    event_svc = get_event_service()
    daily_svc = get_daily_service()
    llm = get_llm_client()

    comp_state = companionship_svc.load_state()
    daily_view = daily_svc.ensure_today(
        comp_state.relationship_stage,
        llm if llm.has_api_key else None,
    )
    comp_summary = companionship_svc.get_summary(memory_service.memory.summary)
    user_profile = profile_svc.get_profile()

    if memory_service.json_fallback:
        st.sidebar.warning("SQLite 不可用，已回退 JSON 存储。")

    def _on_mode_change(mode: str) -> None:
        set_mode(db, mode)
        st.rerun()

    render_sidebar(
        st.session_state["character"],
        assets=config.assets,
        companionship=comp_state,
        db=db,
        on_clear_chat=lambda: _clear_chat(memory_service),
        on_go_profile=lambda: _navigate("角色档案"),
        on_go_lab=lambda: _navigate("实验室"),
        on_mode_change=_on_mode_change,
    )

    render_page_header()
    render_api_banner(config)

    nav = render_main_nav()

    if nav == "聊天":
        messages = _ensure_messages(memory_service)
        user_input, feedback_action = render_chat_page(
            messages,
            memory_service.memory,
            st.session_state["character"].name,
            assets=config.assets,
            companionship=comp_state,
            comp_summary=comp_summary,
            daily=daily_view,
            show_feedback=memory_service.using_sqlite,
        )
        if feedback_action:
            _handle_feedback(feedback_action, memory_service, companionship_svc, event_svc)
        elif user_input:
            _handle_user_message(user_input, memory_service, companionship_svc, event_svc, user_profile)

    elif nav == "记忆":
        mem_action = render_memory_page(
            memory_service.memory,
            memory_service.get_long_term_memory_text(),
            relationship_stage=comp_state.relationship_stage,
            pending_list=memory_service.list_pending(),
            confirmed_list=memory_service.list_confirmed_memories(),
            using_sqlite=memory_service.using_sqlite,
        )
        _handle_memory_actions(mem_action, memory_service, event_svc)

    elif nav == "我们的回忆":
        reflection_svc = get_reflection_service()
        today_refl = reflection_svc.get_today_reflection()
        gen = render_recalls_page(
            event_svc.get_timeline(),
            reflection_svc.list_reflections(),
            today_refl,
            can_generate=llm.has_api_key,
        )
        if gen:
            content, err = reflection_svc.generate_today(llm, config.session_id, config.llm.summary_model)
            if err:
                st.warning(err)
            else:
                st.success("今日回忆已生成")
            st.rerun()

    elif nav == "角色档案":
        render_profile_page(st.session_state["character"])

    elif nav == "语音":
        voice_text = render_voice_page(
            VoiceService(config, llm),
            st.session_state.get("last_assistant_reply", ""),
        )
        if voice_text:
            _handle_user_message(voice_text, memory_service, companionship_svc, event_svc, user_profile)

    elif nav == "实验室":
        eval_summary = get_evaluation_summary(db)
        imported = render_lab_page(
            st.session_state["character"],
            config,
            st.session_state.get("last_evaluation"),
            st.session_state.get("last_analytics"),
            db_stats=db.get_stats(),
            eval_summary=eval_summary,
            memory_backend="sqlite" if memory_service.using_sqlite else "json",
        )
        if imported is not None:
            st.session_state["character"] = imported
            st.session_state["messages"] = []
            st.success(f"已加载角色：{imported.name}")
            st.rerun()

        if st.session_state.pop("_lab_run_analytics", False):
            _run_analytics(memory_service, companionship_svc, db)

    render_footer()


def _navigate(target: str) -> None:
    st.session_state["main_nav"] = target
    st.rerun()


def _handle_memory_actions(action: dict, memory_service: MemoryService, event_svc: RelationshipEventService) -> None:
    if action.get("pending_confirm"):
        memory_service.confirm_pending(action["pending_confirm"])
        event_svc.on_first_preference_saved()
        st.success("已记住")
        st.rerun()
    if action.get("pending_reject"):
        memory_service.reject_pending(action["pending_reject"])
        st.rerun()
    if action.get("pending_edit"):
        pid, text = action["pending_edit"]
        memory_service.edit_and_confirm(pid, text)
        event_svc.on_first_preference_saved()
        st.success("已保存并记住")
        st.rerun()
    if action.get("delete_id"):
        memory_service.delete_memory_by_id(action["delete_id"])
        st.rerun()
    if action.get("summarize"):
        _run_memory_summarize(memory_service)
        st.info("记忆已整理，请到上方「待确认」区域查看")
        st.rerun()
    if action.get("clear_mem"):
        memory_service.clear_memory()
        st.warning("长期记忆已清空")
        st.rerun()


def _handle_feedback(
    action: dict,
    memory_service: MemoryService,
    companionship_svc: CompanionshipService,
    event_svc: RelationshipEventService,
) -> None:
    fb_svc = get_feedback_service()
    ftype = action.get("type")
    if ftype in ("like", "out_of_character"):
        fb_svc.save(
            ftype,
            action.get("conv_id"),
            action.get("user", ""),
            action.get("reply", ""),
        )
        st.toast("感谢你的反馈～" if ftype == "like" else "我会努力更像她")
        st.rerun()
    if ftype == "remember":
        pid = memory_service.add_manual_pending(action.get("reply", ""))
        if pid:
            st.session_state["main_nav"] = "记忆"
            st.toast("已加入待确认记忆，请到「记忆」页确认")
        st.rerun()
    if ftype == "regenerate":
        _regenerate_last_reply(memory_service, companionship_svc, event_svc)


def _regenerate_last_reply(
    memory_service: MemoryService,
    companionship_svc: CompanionshipService,
    event_svc: RelationshipEventService,
) -> None:
    messages = st.session_state["messages"]
    if not messages or messages[-1].get("role") != "assistant":
        return

    if memory_service.using_sqlite and memory_service._db:
        memory_service._db.delete_last_assistant_message(config.session_id)

    messages.pop()
    st.session_state["messages"] = messages

    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        st.rerun()
    last_user = user_msgs[-1]["content"]
    profile_svc = get_profile_service()
    _handle_user_message(
        last_user,
        memory_service,
        companionship_svc,
        event_svc,
        profile_svc.get_profile(),
        skip_append_user=True,
    )


def _handle_user_message(
    user_input: str,
    memory_service: MemoryService,
    companionship_svc: CompanionshipService,
    event_svc: RelationshipEventService,
    user_profile,
    *,
    skip_append_user: bool = False,
) -> None:
    character = st.session_state["character"]
    messages = st.session_state["messages"]

    if not skip_append_user:
        messages.append({"role": "user", "content": user_input})
        memory_service.append_chat("user", user_input, character.name)
        event_svc.on_first_user_message()

    llm = get_llm_client()
    if not llm.has_api_key:
        st.error("请先配置 API_KEY")
        return

    db = get_database()
    comp_state = companionship_svc.load_state()
    daily_svc = get_daily_service()
    daily_view = daily_svc.ensure_today(comp_state.relationship_stage)

    system_prompt = build_system_prompt(
        character=character,
        long_term_memory=memory_service.get_long_term_memory_text(),
        chat_history=messages[:-1] if not skip_append_user else messages,
        user_input=user_input,
        max_history_turns=config.max_history_turns,
        companionship_context=comp_state.to_prompt_context(
            daily_view.greeting, daily_view.little_note
        ),
        user_profile_context=user_profile.to_prompt_context(),
        companion_mode_instructions=get_mode_instructions(db),
    )

    with st.spinner("爱莉希雅正在认真听你说的话……"):
        reply = llm.chat(system_prompt, user_input, model=config.llm.chat_model)

    messages.append({"role": "assistant", "content": reply})
    conv_id = memory_service.append_chat("assistant", reply, character.name)
    if conv_id:
        st.session_state["last_conv_id"] = conv_id

    turn = memory_service.increment_turn()
    st.session_state["last_assistant_reply"] = reply

    new_state = companionship_svc.process_turn(user_input, reply, turn_count=turn)
    event_svc.check_intimacy_milestones(new_state.intimacy_score, new_state.relationship_stage)
    if any(k in user_input for k in LOW_KEYWORDS):
        event_svc.on_first_comfort()

    try:
        evaluation = evaluate_reply(
            llm,
            character,
            user_input,
            reply,
            memory_service.get_long_term_memory_text(),
            db=db if memory_service.using_sqlite else None,
            has_long_term_memory=memory_service.has_substantive_memory(),
            model=config.llm.eval_model,
        )
        st.session_state["last_evaluation"] = evaluation
    except Exception:
        st.session_state["last_evaluation"] = None

    if memory_service.should_summarize(config.memory_summarize_interval):
        msg = _run_memory_summarize(memory_service)
        if msg and "待确认" in msg:
            st.toast(msg)

    st.rerun()


def _run_memory_summarize(memory_service: MemoryService) -> str:
    llm = get_llm_client()
    if not llm.has_api_key:
        return ""
    return memory_service.summarize_memory(
        llm,
        st.session_state["messages"],
        model=config.llm.summary_model,
    )


def _run_analytics(
    memory_service: MemoryService,
    companionship_svc: CompanionshipService,
    db: Database,
) -> None:
    llm = get_llm_client()
    if not llm.has_api_key:
        st.error("请先配置 API_KEY")
        return
    comp = companionship_svc.load_state()
    eval_summary = get_evaluation_summary(db)
    report = analyze_player_experience(
        llm,
        st.session_state["messages"],
        st.session_state["character"].name,
        companionship_context=comp.to_prompt_context(),
        evaluation_averages=eval_summary.get("averages"),
        feedback_stats=db.get_feedback_stats(),
        model=config.llm.eval_model,
    )
    st.session_state["last_analytics"] = report
    st.rerun()


if __name__ == "__main__":
    main()
