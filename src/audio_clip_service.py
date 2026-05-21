"""Local official audio clips — user-provided files only, not bundled in repo."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.config import AudioClipConfig, PROJECT_ROOT

SCENES = (
    "greeting",
    "thinking",
    "comfort",
    "happy",
    "farewell",
    "relationship_up",
)


class AudioClipService:
    def __init__(self, config: AudioClipConfig) -> None:
        self._config = config
        self._clips_path = config.official_clips_dir / "official_clips.json"
        self._clips: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._clips_path.exists():
            self._clips = {s: [] for s in SCENES}
            return
        try:
            data = json.loads(self._clips_path.read_text(encoding="utf-8"))
            self._clips = {s: list(data.get(s, [])) for s in SCENES}
        except (json.JSONDecodeError, OSError):
            self._clips = {s: [] for s in SCENES}

    @property
    def is_enabled(self) -> bool:
        return self._config.enabled

    def _resolve_path(self, entry: str) -> Path | None:
        p = Path(entry)
        if not p.is_absolute():
            p = PROJECT_ROOT / entry
        if p.is_file():
            return p
        alt = self._config.official_clips_dir / entry
        if alt.is_file():
            return alt
        return None

    def pick_clip(self, scene: str) -> Path | None:
        if not self.is_enabled or scene not in self._clips:
            return None
        candidates: list[Path] = []
        for entry in self._clips.get(scene, []):
            resolved = self._resolve_path(str(entry))
            if resolved:
                candidates.append(resolved)
        if not candidates:
            return None
        return random.choice(candidates)

    def count_clips(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for scene in SCENES:
            n = 0
            for entry in self._clips.get(scene, []):
                if self._resolve_path(str(entry)):
                    n += 1
            counts[scene] = n
        return counts

    def total_clips(self) -> int:
        return sum(self.count_clips().values())
