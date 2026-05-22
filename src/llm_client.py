"""OpenAI-compatible LLM client."""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from src.config import LLMConfig


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = (
            OpenAI(api_key=config.api_key, base_url=config.base_url)
            if config.api_key
            else None
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self._config.api_key and self._client)

    def _require_client(self) -> OpenAI:
        if not self._client:
            raise ValueError(
                "API_KEY is not set. Copy .env.example to .env and configure your API key."
            )
        return self._client

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        client = self._require_client()
        response = client.chat.completions.create(
            model=model or self._config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature if temperature is not None else self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        content = response.choices[0].message.content
        return (content or "").strip()

    def chat_json(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        client = self._require_client()
        response = client.chat.completions.create(
            model=model or self._config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=self._config.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return (content or "").strip()

    def transcribe_audio(
        self,
        audio_path: Path,
        model: str = "whisper-1",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> str:
        key = api_key or self._config.api_key
        if not key:
            raise ValueError("API_KEY is not set.")
        client = OpenAI(
            api_key=key,
            base_url=base_url or self._config.base_url,
        )
        with audio_path.open("rb") as f:
            result = client.audio.transcriptions.create(model=model, file=f)
        return (result.text or "").strip()

    def synthesize_speech_openai(
        self,
        text: str,
        out_path: Path,
        voice: str = "alloy",
        *,
        model: str = "tts-1",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> Path:
        key = api_key or self._config.api_key
        if not key:
            raise ValueError("API_KEY is not set.")
        client = OpenAI(
            api_key=key,
            base_url=base_url or self._config.base_url,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text[:4096],
        )
        response.stream_to_file(str(out_path))
        return out_path
