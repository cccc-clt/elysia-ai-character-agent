"""Optional voice STT/TTS with pluggable providers — failures do not block text chat."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests

from src.config import AppConfig, VoiceConfig

_whisper_model_cache: dict[str, Any] = {}

_CONVERT_SUFFIXES = {".mp3", ".m4a", ".ogg", ".webm"}


def _md5_key(text: str, n: int = 16) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:n]


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _convert_to_wav(src: Path, cache_dir: Path) -> Path | None:
    """Convert compressed audio to wav via ffmpeg when available."""
    if not _ffmpeg_available():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"stt_{src.stem}_{_md5_key(str(src), 8)}.wav"
    if out.exists():
        return out
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-ar",
                "16000",
                "-ac",
                "1",
                str(out),
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )
        return out if out.is_file() else None
    except (subprocess.SubprocessError, OSError):
        return None


def _prepare_stt_path(audio_path: Path, cache_dir: Path) -> tuple[Path, str | None]:
    """Return path suitable for STT; convert via ffmpeg when needed."""
    if audio_path.suffix.lower() not in _CONVERT_SUFFIXES:
        return audio_path, None
    converted = _convert_to_wav(audio_path, cache_dir)
    if converted:
        return converted, None
    return audio_path, (
        "mp3/m4a 转写建议安装 ffmpeg 并加入 PATH，或改用 wav 上传 / STT_PROVIDER=openai"
    )


# ---------------------------------------------------------------------------
# STT Providers
# ---------------------------------------------------------------------------


class BaseSTTProvider(ABC):
    name: str = "base"

    @abstractmethod
    def transcribe(self, audio_path: Path) -> tuple[str | None, str | None]:
        """Returns (text, error_message)."""


class LocalWhisperSTT(BaseSTTProvider):
    name = "local_whisper"

    def __init__(self, cfg: VoiceConfig) -> None:
        self._cfg = cfg

    def _get_model(self):
        cache_key = f"{self._cfg.whisper_model}:{self._cfg.whisper_device}:{self._cfg.whisper_compute_type}"
        if cache_key in _whisper_model_cache:
            return _whisper_model_cache[cache_key]
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError(
                "未安装 faster-whisper。请运行: pip install faster-whisper"
            ) from exc
        model = WhisperModel(
            self._cfg.whisper_model,
            device=self._cfg.whisper_device,
            compute_type=self._cfg.whisper_compute_type,
        )
        _whisper_model_cache[cache_key] = model
        return model

    def transcribe(self, audio_path: Path) -> tuple[str | None, str | None]:
        try:
            model = self._get_model()
            segments, _ = model.transcribe(str(audio_path), language="zh")
            text = "".join(seg.text for seg in segments).strip()
            return text or None, None if text else "未识别到语音内容"
        except ImportError as exc:
            return None, str(exc)
        except Exception as exc:
            return None, f"本地 Whisper 转写失败：{exc}"


class OpenAISTT(BaseSTTProvider):
    name = "openai"

    def __init__(self, cfg: VoiceConfig) -> None:
        self._cfg = cfg

    def transcribe(self, audio_path: Path) -> tuple[str | None, str | None]:
        if not self._cfg.audio_api_key:
            return None, "需要配置 AUDIO_API_KEY 或 API_KEY 才能使用 OpenAI Whisper 转写"
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self._cfg.audio_api_key,
                base_url=self._cfg.audio_base_url,
            )
            with audio_path.open("rb") as f:
                result = client.audio.transcriptions.create(
                    model=self._cfg.whisper_api_model,
                    file=f,
                )
            text = (result.text or "").strip()
            return text or None, None if text else "未识别到语音内容"
        except Exception as exc:
            return None, f"语音转写失败：{exc}"


class BaiduSTT(BaseSTTProvider):
    name = "baidu"

    def __init__(self, cfg: VoiceConfig) -> None:
        self._cfg = cfg
        self._token: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._cfg.baidu_api_key and self._cfg.baidu_secret_key)

    def _get_token(self) -> str | None:
        if self._token:
            return self._token
        if not self.is_configured:
            return None
        try:
            resp = requests.get(
                "https://aip.baidubce.com/oauth/2.0/token",
                params={
                    "grant_type": "client_credentials",
                    "client_id": self._cfg.baidu_api_key,
                    "client_secret": self._cfg.baidu_secret_key,
                },
                timeout=10,
            )
            data = resp.json()
            self._token = data.get("access_token")
            return self._token
        except Exception:
            return None

    def transcribe(self, audio_path: Path) -> tuple[str | None, str | None]:
        if not self.is_configured:
            return None, "百度语音识别未配置（BAIDU_API_KEY / BAIDU_SECRET_KEY）"
        token = self._get_token()
        if not token:
            return None, "百度语音识别 Token 获取失败"
        try:
            raw = audio_path.read_bytes()
            audio_b64 = base64.b64encode(raw).decode("utf-8")
            suffix = audio_path.suffix.lower()
            fmt_map = {".wav": "wav", ".mp3": "mp3", ".m4a": "m4a", ".ogg": "ogg", ".webm": "webm"}
            fmt = fmt_map.get(suffix, "wav")
            resp = requests.post(
                "https://vop.baidu.com/server_api",
                json={
                    "format": fmt,
                    "rate": 16000,
                    "channel": 1,
                    "cuid": "elysia_companion",
                    "token": token,
                    "speech": audio_b64,
                    "len": len(raw),
                },
                timeout=30,
            )
            data = resp.json()
            if data.get("err_no") == 0:
                results = data.get("result") or []
                text = "".join(results).strip()
                return text or None, None if text else "未识别到语音内容"
            return None, f"百度语音识别失败：{data.get('err_msg', data)}"
        except Exception as exc:
            return None, f"百度语音识别失败：{exc}"


# ---------------------------------------------------------------------------
# TTS Providers
# ---------------------------------------------------------------------------


class BaseTTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def synthesize(self, text: str, out_path: Path) -> tuple[Path | None, str | None]:
        """Returns (audio_path, error_message)."""


class EdgeTTSProvider(BaseTTSProvider):
    name = "edge"

    def __init__(self, cfg: VoiceConfig) -> None:
        self._cfg = cfg

    def synthesize(self, text: str, out_path: Path) -> tuple[Path | None, str | None]:
        try:
            import edge_tts
        except ImportError:
            return None, "未安装 edge-tts。请运行: pip install edge-tts"

        async def _run() -> None:
            communicate = edge_tts.Communicate(text[:4096], self._cfg.voice_name)
            await communicate.save(str(out_path))

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            asyncio.run(_run())
            return out_path, None
        except Exception as exc:
            return None, f"edge-tts 合成失败：{exc}"


class OpenAITTSProvider(BaseTTSProvider):
    name = "openai"

    def __init__(self, cfg: VoiceConfig) -> None:
        self._cfg = cfg

    def synthesize(self, text: str, out_path: Path) -> tuple[Path | None, str | None]:
        if not self._cfg.audio_api_key:
            return None, "需要配置 AUDIO_API_KEY 或 API_KEY 才能使用 OpenAI TTS"
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self._cfg.audio_api_key,
                base_url=self._cfg.audio_base_url,
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            response = client.audio.speech.create(
                model=self._cfg.tts_model,
                voice=self._cfg.tts_voice,
                input=text[:4096],
            )
            response.stream_to_file(str(out_path))
            return out_path, None
        except Exception as exc:
            return None, f"OpenAI TTS 合成失败：{exc}"


class GPTSoVITSProvider(BaseTTSProvider):
    name = "gpt_sovits"

    GPT_SOVITS_OFFLINE_MSG = (
        "未检测到本地 GPT-SoVITS 服务，请确认服务已启动，或切换到 edge-tts 兜底语音。"
    )

    def __init__(self, cfg: VoiceConfig) -> None:
        self._cfg = cfg

    def check_online(self) -> tuple[bool, str]:
        base = self._cfg.gpt_sovits_url
        for path in ("", "/docs", "/health"):
            try:
                resp = requests.get(f"{base}{path}", timeout=3)
                if resp.status_code < 500:
                    return True, f"已连接 {base}"
            except requests.RequestException:
                continue
        return False, self.GPT_SOVITS_OFFLINE_MSG

    def _resolved_ref_path(self) -> str:
        ref = self._cfg.gpt_sovits_ref_audio
        if not ref.is_absolute():
            from src.config import PROJECT_ROOT

            ref = PROJECT_ROOT / ref
        return str(ref.resolve()) if ref.exists() else str(ref.resolve())

    def _gradio_inference_payload(self, text: str) -> dict[str, Any]:
        ref_path = self._resolved_ref_path()
        prompt = self._cfg.gpt_sovits_prompt_text
        prompt_lang = self._cfg.gpt_sovits_prompt_lang
        text_lang = self._cfg.gpt_sovits_text_lang
        speed = self._cfg.gpt_sovits_speed
        return {
            "data": [
                text[:4096],
                text_lang,
                ref_path if Path(ref_path).exists() else None,
                [],
                prompt,
                prompt_lang,
                5,
                1,
                1,
                "凑四句一切",
                20,
                speed,
                False,
                True,
                0.3,
                -1,
                True,
                True,
                1.35,
                32,
                False,
            ]
        }

    def _save_audio_response(self, resp: requests.Response, out_path: Path) -> Path | None:
        content_type = resp.headers.get("content-type", "")
        if "audio" in content_type or (len(resp.content) >= 4 and resp.content[:4] == b"RIFF"):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            target = out_path if out_path.suffix.lower() == ".wav" else out_path.with_suffix(".wav")
            target.write_bytes(resp.content)
            return target
        try:
            data = resp.json()
            if "data" in data and isinstance(data["data"], list) and data["data"]:
                item = data["data"][0]
                audio_url = item.get("url") or item.get("name")
                if audio_url:
                    if str(audio_url).startswith("http"):
                        ar = requests.get(audio_url, timeout=60)
                        if ar.status_code == 200:
                            out_path.parent.mkdir(parents=True, exist_ok=True)
                            out_path.write_bytes(ar.content)
                            return out_path
                    elif Path(audio_url).exists():
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_bytes(Path(audio_url).read_bytes())
                        return out_path
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        return None

    def synthesize(self, text: str, out_path: Path) -> tuple[Path | None, str | None]:
        online, msg = self.check_online()
        if not online:
            return None, msg

        ref_path = self._resolved_ref_path()
        payload = {
            "refer_wav_path": ref_path,
            "prompt_text": self._cfg.gpt_sovits_prompt_text,
            "prompt_language": self._cfg.gpt_sovits_prompt_lang,
            "text": text[:4096],
            "text_language": self._cfg.gpt_sovits_text_lang,
            "speed": self._cfg.gpt_sovits_speed,
        }
        base = self._cfg.gpt_sovits_url.rstrip("/")
        attempts: list[tuple[str, dict | None]] = [
            (f"{base}/api/inference", self._gradio_inference_payload(text)),
            (base, payload),
            (f"{base}/tts", {"text": text[:4096]}),
        ]

        for url, body in attempts:
            try:
                resp = requests.post(url, json=body, timeout=120)
                if resp.status_code == 200:
                    saved = self._save_audio_response(resp, out_path)
                    if saved:
                        return saved, None
            except requests.RequestException:
                continue

        return None, self.GPT_SOVITS_OFFLINE_MSG


class CustomTTSProvider(BaseTTSProvider):
    name = "custom"

    def __init__(self, cfg: VoiceConfig) -> None:
        self._cfg = cfg

    def synthesize(self, text: str, out_path: Path) -> tuple[Path | None, str | None]:
        endpoint = self._cfg.custom_tts_endpoint
        if not endpoint:
            return None, "未配置 CUSTOM_TTS_ENDPOINT"
        try:
            resp = requests.post(
                endpoint,
                json={"text": text[:4096]},
                timeout=120,
            )
            if resp.status_code != 200:
                return None, f"自定义 TTS 返回 {resp.status_code}"

            content_type = resp.headers.get("content-type", "")
            if "audio" in content_type or len(resp.content) > 1000:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(resp.content)
                return out_path, None

            data = resp.json()
            if "audio_path" in data:
                src = Path(data["audio_path"])
                if src.exists():
                    out_path.write_bytes(src.read_bytes())
                    return out_path, None
            if "audio_url" in data:
                ar = requests.get(data["audio_url"], timeout=60)
                if ar.status_code == 200:
                    out_path.write_bytes(ar.content)
                    return out_path, None
            return None, "自定义 TTS 响应中未找到音频"
        except Exception as exc:
            return None, f"自定义 TTS 调用失败：{exc}"


class OfficialClipsTTSProvider(BaseTTSProvider):
    name = "official_clips"

    def synthesize(self, text: str, out_path: Path) -> tuple[Path | None, str | None]:
        return (
            None,
            "official_clips 仅用于播放本地预置片段，不支持动态合成。请使用 edge 或 gpt_sovits。",
        )


# ---------------------------------------------------------------------------
# VoiceService facade
# ---------------------------------------------------------------------------


class VoiceService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.voice_config: VoiceConfig = config.voice
        self._stt = self._build_stt()
        self._tts = self._build_tts()
        self._fallback_tts = self._build_tts(self.voice_config.tts_fallback_provider)

    def _build_stt(self) -> BaseSTTProvider:
        provider = self.voice_config.stt_provider
        if provider == "local_whisper":
            return LocalWhisperSTT(self.voice_config)
        if provider == "openai":
            return OpenAISTT(self.voice_config)
        if provider == "baidu":
            return BaiduSTT(self.voice_config)
        return OpenAISTT(self.voice_config)

    def _build_tts(self, provider_name: str | None = None) -> BaseTTSProvider:
        provider = provider_name or self.voice_config.tts_provider
        if provider == "edge":
            return EdgeTTSProvider(self.voice_config)
        if provider == "openai":
            return OpenAITTSProvider(self.voice_config)
        if provider == "gpt_sovits":
            return GPTSoVITSProvider(self.voice_config)
        if provider == "custom":
            return CustomTTSProvider(self.voice_config)
        if provider == "official_clips":
            return OfficialClipsTTSProvider()
        return EdgeTTSProvider(self.voice_config)

    @property
    def is_enabled(self) -> bool:
        return self.voice_config.enabled

    def _save_input_audio(self, audio_bytes: bytes, suffix: str) -> Path:
        cache_dir = self.voice_config.audio_cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.md5(audio_bytes[:4096]).hexdigest()[:12]
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        path = cache_dir / f"input_{key}{suffix}"
        path.write_bytes(audio_bytes)
        return path

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        suffix: str = ".wav",
        *,
        save_path: Path | None = None,
    ) -> tuple[str | None, str | None, Path | None]:
        """Returns (text, error_message, input_audio_path)."""
        if not self.is_enabled:
            return None, "语音功能未开启，请在 .env 中设置 ENABLE_VOICE=true", None

        try:
            audio_path = save_path or self._save_input_audio(audio_bytes, suffix)
            if save_path is None and not audio_path.exists():
                audio_path.write_bytes(audio_bytes)
            stt_path, hint = _prepare_stt_path(
                audio_path, self.voice_config.audio_cache_dir
            )
            text, err = self._stt.transcribe(stt_path)
            if err and hint and audio_path.suffix.lower() in _CONVERT_SUFFIXES:
                return None, f"{err}（{hint}）", audio_path
            if err and hint and not text:
                return None, hint, audio_path
            return text, err, audio_path
        except Exception as exc:
            return None, f"语音转写失败：{exc}", None

    def transcribe_upload(
        self, audio_bytes: bytes, suffix: str = ".wav"
    ) -> tuple[str | None, str | None]:
        """Legacy API: (text, error)."""
        text, err, _ = self.transcribe_audio(audio_bytes, suffix)
        return text, err

    def text_to_speech(
        self,
        text: str,
        out_path: Path | None = None,
        *,
        use_fallback: bool = True,
    ) -> tuple[Path | None, str | None, str]:
        """
        Returns (audio_path, error_message, provider_used).
        provider_used is the TTS provider name that succeeded.
        """
        if not self.is_enabled:
            return None, "语音功能未开启", ""
        if not text.strip():
            return None, "没有可合成的文本", ""

        cache_dir = self.voice_config.audio_cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = _md5_key(text)
        provider_name = self.voice_config.tts_provider

        if out_path is None:
            ext = ".wav" if provider_name == "gpt_sovits" else ".mp3"
            out_path = cache_dir / f"tts_{provider_name}_{key}{ext}"

        if out_path.exists():
            return out_path, None, provider_name

        path, err = self._tts.synthesize(text, out_path)
        if path:
            return path, None, self._tts.name

        if use_fallback and provider_name != self.voice_config.tts_fallback_provider:
            fb = self.voice_config.tts_fallback_provider
            fb_path = cache_dir / f"tts_{fb}_{key}.mp3"
            if not fb_path.exists():
                path, fb_err = self._fallback_tts.synthesize(text, fb_path)
                if path:
                    return path, None, fb
                return None, fb_err or err, ""
            return fb_path, None, fb

        return None, err, ""

    def generate_reply_audio(
        self,
        text: str,
        conversation_id: int | None = None,
    ) -> tuple[Path | None, str | None, str]:
        """TTS for assistant reply with optional conv-specific cache key."""
        cache_dir = self.voice_config.audio_cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = _md5_key(f"{conversation_id or 0}:{text}")
        provider_name = self.voice_config.tts_provider
        ext = ".wav" if provider_name == "gpt_sovits" else ".mp3"
        out_path = cache_dir / f"reply_{conversation_id or 0}_{key}{ext}"
        if out_path.exists():
            return out_path, None, provider_name
        return self.text_to_speech(text, out_path)

    def synthesize_reply(self, text: str) -> tuple[Path | None, str | None]:
        """Legacy API: (path, error)."""
        path, err, _ = self.generate_reply_audio(text)
        return path, err

    def check_tts_status(self) -> dict[str, Any]:
        ref = self.voice_config.gpt_sovits_ref_audio
        if not ref.is_absolute():
            from src.config import PROJECT_ROOT

            ref = PROJECT_ROOT / ref
        status: dict[str, Any] = {
            "stt_provider": self.voice_config.stt_provider,
            "tts_provider": self.voice_config.tts_provider,
            "tts_fallback_provider": self.voice_config.tts_fallback_provider,
            "gpt_sovits_url": self.voice_config.gpt_sovits_url,
            "gpt_sovits_online": False,
            "gpt_sovits_message": "",
            "ref_audio_path": str(ref),
            "ref_audio_exists": ref.is_file(),
            "ffmpeg_available": _ffmpeg_available(),
            "edge_tts_available": False,
        }
        try:
            import edge_tts  # noqa: F401

            status["edge_tts_available"] = True
        except ImportError:
            status["edge_tts_available"] = False

        if isinstance(self._tts, GPTSoVITSProvider):
            online, msg = self._tts.check_online()
            status["gpt_sovits_online"] = online
            status["gpt_sovits_message"] = msg
        elif self.voice_config.tts_provider == "gpt_sovits":
            prov = GPTSoVITSProvider(self.voice_config)
            online, msg = prov.check_online()
            status["gpt_sovits_online"] = online
            status["gpt_sovits_message"] = msg

        return status

    def clear_audio_cache(self) -> tuple[int, str]:
        cache_dir = self.voice_config.audio_cache_dir
        if not cache_dir.exists():
            return 0, str(cache_dir)
        count = 0
        for f in cache_dir.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                try:
                    f.unlink()
                    count += 1
                except OSError:
                    pass
        return count, str(cache_dir)

    def count_cache_files(self) -> int:
        cache_dir = self.voice_config.audio_cache_dir
        if not cache_dir.exists():
            return 0
        return sum(1 for f in cache_dir.iterdir() if f.is_file() and f.name != ".gitkeep")
