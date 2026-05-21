"""Character profile loading, validation, and import/export."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "name",
    "role",
    "personality",
    "speaking_style",
    "relationship",
    "forbidden",
    "opening_message",
)


@dataclass
class CharacterProfile:
    name: str
    role: str
    personality: str
    speaking_style: str
    relationship: str
    forbidden: str
    opening_message: str
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterProfile:
        missing = [f for f in REQUIRED_FIELDS if f not in data or not str(data[f]).strip()]
        if missing:
            raise ValueError(f"Character card missing required fields: {', '.join(missing)}")

        known = {f: str(data[f]).strip() for f in REQUIRED_FIELDS}
        extra = {k: v for k, v in data.items() if k not in REQUIRED_FIELDS}
        return cls(**known, meta=extra)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        meta = result.pop("meta", {})
        if meta:
            result.update(meta)
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def load_character(path: Path) -> CharacterProfile:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return CharacterProfile.from_dict(data)


def save_character(profile: CharacterProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)


def parse_character_json(raw: str) -> CharacterProfile:
    return CharacterProfile.from_dict(json.loads(raw))
