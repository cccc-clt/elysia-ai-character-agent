"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
ASSETS_DIR = PROJECT_ROOT / "assets"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model_name: str
    chat_model: str
    eval_model: str
    summary_model: str
    temperature: float = 0.9
    max_tokens: int = 1500


@dataclass(frozen=True)
class StorageConfig:
    backend: str
    database_path: Path
    memory_store_path: Path
    chat_logs_path: Path


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool
    stt_provider: str
    tts_provider: str
    tts_fallback_provider: str
    voice_name: str
    audio_cache_dir: Path
    # OpenAI-compatible audio API
    audio_api_key: str
    audio_base_url: str
    whisper_api_model: str
    tts_model: str
    tts_voice: str
    # Local Whisper
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    # Baidu
    baidu_api_key: str
    baidu_secret_key: str
    # GPT-SoVITS
    gpt_sovits_url: str
    gpt_sovits_ref_audio: Path
    gpt_sovits_prompt_text: str
    gpt_sovits_prompt_lang: str
    gpt_sovits_text_lang: str
    gpt_sovits_speed: float
    # Custom TTS
    custom_tts_endpoint: str


@dataclass(frozen=True)
class AudioClipConfig:
    enabled: bool
    official_clips_dir: Path


@dataclass(frozen=True)
class AssetConfig:
    portrait: Path
    background: Path
    avatar: Path


@dataclass(frozen=True)
class LoreRAGConfig:
    enabled: bool
    prototype_mode: bool
    allow_unverified_transcripts: bool
    require_citations: bool
    top_k: int
    max_context_chars: int
    backend: str
    index_path: Path
    timeout_seconds: float


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig
    storage: StorageConfig
    voice: VoiceConfig
    audio_clips: AudioClipConfig
    assets: AssetConfig
    lore_rag: LoreRAGConfig
    memory_summarize_interval: int = 6
    max_history_turns: int = 20
    default_character_path: Path = CHARACTERS_DIR / "elysia_character.json"
    session_id: str = "default"


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def get_config() -> AppConfig:
    api_key = os.getenv("API_KEY", "").strip()
    base_url = os.getenv("BASE_URL", "https://api.openai.com/v1").strip()
    model_name = os.getenv("MODEL_NAME", "gpt-4o-mini").strip()
    chat_model = os.getenv("CHAT_MODEL_NAME", "").strip() or model_name
    eval_model = os.getenv("EVAL_MODEL_NAME", "").strip() or model_name
    summary_model = os.getenv("SUMMARY_MODEL_NAME", "").strip() or model_name
    temperature = float(os.getenv("TEMPERATURE", "0.9"))
    max_tokens = int(os.getenv("MAX_TOKENS", "1500"))
    summarize_interval = int(os.getenv("MEMORY_SUMMARIZE_INTERVAL", "6"))

    db_path = PROJECT_ROOT / os.getenv("DATABASE_PATH", "data/elysia_companion.db")
    storage_backend = os.getenv("STORAGE_BACKEND", "sqlite").strip().lower()

    audio_api_key = os.getenv("AUDIO_API_KEY", "").strip() or api_key
    audio_cache = PROJECT_ROOT / os.getenv("AUDIO_CACHE_DIR", "data/audio_cache")
    lore_backend = os.getenv("LORE_RAG_BACKEND", "hybrid").strip().lower()
    if lore_backend not in {"bm25", "vector", "hybrid"}:
        lore_backend = "hybrid"

    return AppConfig(
        llm=LLMConfig(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            chat_model=chat_model,
            eval_model=eval_model,
            summary_model=summary_model,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        storage=StorageConfig(
            backend=storage_backend,
            database_path=db_path,
            memory_store_path=DATA_DIR / "memory_store.json",
            chat_logs_path=DATA_DIR / "chat_logs.json",
        ),
        voice=VoiceConfig(
            enabled=_env_bool("ENABLE_VOICE", "false"),
            stt_provider=os.getenv("STT_PROVIDER", "local_whisper").strip().lower(),
            tts_provider=os.getenv("TTS_PROVIDER", "gpt_sovits").strip().lower(),
            tts_fallback_provider=os.getenv("TTS_FALLBACK_PROVIDER", "edge").strip().lower(),
            voice_name=os.getenv("VOICE_NAME", "zh-CN-XiaoxiaoNeural").strip(),
            audio_cache_dir=audio_cache,
            audio_api_key=audio_api_key,
            audio_base_url=os.getenv("AUDIO_BASE_URL", "https://api.openai.com/v1").strip(),
            whisper_api_model=os.getenv("WHISPER_API_MODEL", "whisper-1").strip(),
            tts_model=os.getenv("TTS_MODEL", "gpt-4o-mini-tts").strip(),
            tts_voice=os.getenv("TTS_VOICE", "alloy").strip(),
            whisper_model=os.getenv("WHISPER_MODEL", "small").strip(),
            whisper_device=os.getenv("WHISPER_DEVICE", "cpu").strip(),
            whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip(),
            baidu_api_key=os.getenv("BAIDU_API_KEY", "").strip(),
            baidu_secret_key=os.getenv("BAIDU_SECRET_KEY", "").strip(),
            gpt_sovits_url=os.getenv("GPT_SOVITS_URL", "http://localhost:9872").strip().rstrip("/"),
            gpt_sovits_ref_audio=PROJECT_ROOT / os.getenv(
                "GPT_SOVITS_REF_AUDIO", "assets/audio/ref/elysia_ref.wav"
            ),
            gpt_sovits_prompt_text=os.getenv("GPT_SOVITS_PROMPT_TEXT", "").strip(),
            gpt_sovits_prompt_lang=os.getenv("GPT_SOVITS_PROMPT_LANG", "zh").strip(),
            gpt_sovits_text_lang=os.getenv("GPT_SOVITS_TEXT_LANG", "zh").strip(),
            gpt_sovits_speed=float(os.getenv("GPT_SOVITS_SPEED", "1.0")),
            custom_tts_endpoint=os.getenv(
                "CUSTOM_TTS_ENDPOINT", "http://localhost:5000/tts"
            ).strip(),
        ),
        audio_clips=AudioClipConfig(
            enabled=_env_bool("ENABLE_OFFICIAL_CLIPS", "true"),
            official_clips_dir=PROJECT_ROOT / os.getenv(
                "OFFICIAL_CLIPS_DIR", "assets/audio/official_lines"
            ),
        ),
        assets=AssetConfig(
            portrait=PROJECT_ROOT / os.getenv("PORTRAIT_PATH", "assets/images/elysia_portrait.png"),
            background=PROJECT_ROOT / os.getenv(
                "BACKGROUND_PATH", "assets/images/elysia_background.png"
            ),
            avatar=PROJECT_ROOT / os.getenv("AVATAR_PATH", "assets/images/avatar.png"),
        ),
        lore_rag=LoreRAGConfig(
            enabled=_env_bool("LORE_RAG_ENABLED", "false"),
            prototype_mode=_env_bool("LORE_RAG_PROTOTYPE_MODE", "true"),
            allow_unverified_transcripts=_env_bool(
                "LORE_RAG_ALLOW_UNVERIFIED_TRANSCRIPTS", "false"
            ),
            require_citations=_env_bool("LORE_RAG_REQUIRE_CITATIONS", "true"),
            top_k=max(1, min(10, int(os.getenv("LORE_RAG_TOP_K", "5")))),
            max_context_chars=max(
                1000, min(12000, int(os.getenv("LORE_RAG_MAX_CONTEXT_CHARS", "6000")))
            ),
            backend=lore_backend,
            index_path=PROJECT_ROOT
            / os.getenv(
                "LORE_RAG_INDEX_PATH", "data/lore_index/hashed_vectors.json"
            ),
            timeout_seconds=max(
                0.05, min(10.0, float(os.getenv("LORE_RAG_TIMEOUT_SECONDS", "2.0")))
            ),
        ),
        memory_summarize_interval=summarize_interval,
    )


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "images").mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "audio").mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "audio" / "ref").mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "audio" / "clips").mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "audio" / "official_lines").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "audio_cache").mkdir(parents=True, exist_ok=True)
