"""Public result models for the isolated lore retrieval module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


CorpusName = Literal["official_lore", "bh3text_dialogue", "story_navigation"]
QueryRoute = Literal["official_fact", "dialogue", "navigation", "mixed", "none"]


@dataclass(frozen=True)
class LoreChunk:
    chunk_id: str
    document_id: str
    corpus: CorpusName
    content: str
    title: str
    source_url: str
    source_type: str
    source_tier: str
    review_status: str
    chapter: str = ""
    scene: str = ""
    character_names: tuple[str, ...] = ()
    topic_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoreSearchResult:
    chunk_id: str
    content: str
    score: float
    source_url: str
    source_type: str
    source_tier: str
    title: str
    corpus: CorpusName
    chapter: str = ""
    scene: str = ""
    review_status: str = ""


@dataclass(frozen=True)
class LoreCitation:
    title: str
    source_url: str
    source_tier: str
    corpus: CorpusName
    chapter: str = ""
    scene: str = ""
    review_status: str = ""


@dataclass(frozen=True)
class LoreAugmentation:
    query: str
    route: QueryRoute
    backend: str
    context: str
    results: tuple[LoreSearchResult, ...] = ()
    citations: tuple[LoreCitation, ...] = ()
    elapsed_ms: float = 0.0
    degraded_reason: str = ""
    enabled: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def used(self) -> bool:
        return bool(self.enabled and self.results and self.context)

    def append_sources(self, answer: str) -> str:
        """Append a short, deduplicated source list without reproducing corpus text."""

        if not self.used or not self.citations:
            return answer
        seen: set[str] = set()
        lines: list[str] = []
        for citation in self.citations:
            if citation.source_url in seen:
                continue
            seen.add(citation.source_url)
            label = citation.title.replace("[", "［").replace("]", "］")
            qualifier = citation.source_tier
            if citation.corpus == "bh3text_dialogue":
                qualifier += "，剧情文本存档/非官方托管"
            lines.append(f"- [{label}]({citation.source_url})（{qualifier}）")
        return f"{answer.rstrip()}\n\n资料来源：\n" + "\n".join(lines)
