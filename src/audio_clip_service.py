"""Local official audio clips — user-provided files only, not bundled in repo."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.config import PROJECT_ROOT

CLIP_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a"}

SCENES = (
    "greeting",
    "thinking",
    "comfort",
    "happy",
    "farewell",
    "relationship_up",
)

DEFAULT_CLIPS_DIR = PROJECT_ROOT / "assets" / "audio" / "clips"


class AudioClipService:
    """Manage local official voice clips under assets/audio/clips by default."""

    def __init__(self, config=None, *, clips_dir: Path | str | None = None) -> None:
        if config is not None:
            self._enabled = getattr(config, "enabled", True)
            base = getattr(config, "official_clips_dir", None) or getattr(
                config, "clips_dir", None
            )
            self._clips_dir = Path(base) if base else DEFAULT_CLIPS_DIR
        else:
            self._enabled = True
            self._clips_dir = Path(clips_dir) if clips_dir else DEFAULT_CLIPS_DIR

        if not self._clips_dir.is_absolute():
            self._clips_dir = PROJECT_ROOT / self._clips_dir

        self._clips_path = self._clips_dir / "official_clips.json"
        self._scene_index: dict[str, list[str]] = {}
        self._load_scene_index()

    def _load_scene_index(self) -> None:
        if not self._clips_path.is_file():
            self._scene_index = {s: [] for s in SCENES}
            return
        try:
            data = json.loads(self._clips_path.read_text(encoding="utf-8"))
            self._scene_index = {s: list(data.get(s, [])) for s in SCENES}
        except (json.JSONDecodeError, OSError):
            self._scene_index = {s: [] for s in SCENES}

    @property
    def clips_dir(self) -> Path:
        return self._clips_dir

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _iter_audio_files(self, directory: Path) -> list[Path]:
        if not directory.is_dir():
            return []
        found: list[Path] = []
        try:
            for item in directory.rglob("*"):
                if item.is_file() and item.suffix.lower() in CLIP_EXTENSIONS:
                    found.append(item.resolve())
        except OSError:
            return []
        return sorted(found)

    def list_clips(self) -> list[str]:
        """Return paths of all available clip files (empty list if none)."""
        files = self._iter_audio_files(self._clips_dir)
        return [str(p) for p in files]

    def get_random_clip(self) -> str | None:
        """Return a random clip file path, or None if none available."""
        files = self.list_clips()
        if not files:
            return None
        return random.choice(files)

    def _resolve_entry(self, entry: str) -> Path | None:
        p = Path(entry)
        if not p.is_absolute():
            p = PROJECT_ROOT / entry
        if p.is_file() and p.suffix.lower() in CLIP_EXTENSIONS:
            return p.resolve()
        alt = self._clips_dir / entry
        if alt.is_file() and alt.suffix.lower() in CLIP_EXTENSIONS:
            return alt.resolve()
        return None

    def pick_clip(self, scene: str) -> Path | None:
        """Pick a clip for a scene (subdir or JSON index), else random from clips dir."""
        if not self._enabled:
            return None

        scene_dir = self._clips_dir / scene
        scene_files = self._iter_audio_files(scene_dir)
        if scene_files:
            return random.choice(scene_files)

        if scene in self._scene_index:
            candidates: list[Path] = []
            for entry in self._scene_index.get(scene, []):
                resolved = self._resolve_entry(str(entry))
                if resolved:
                    candidates.append(resolved)
            if candidates:
                return random.choice(candidates)

        path = self.get_random_clip()
        return Path(path) if path else None

    def count_clips(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for scene in SCENES:
            n = len(self._iter_audio_files(self._clips_dir / scene))
            if n == 0:
                for entry in self._scene_index.get(scene, []):
                    if self._resolve_entry(str(entry)):
                        n += 1
            counts[scene] = n
        return counts

    def total_clips(self) -> int:
        return len(self.list_clips())
