"""Deterministic BM25, hashed-vector, and RRF retrieval implementations."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Protocol
from datetime import datetime, timezone

from src.lore.corpus import LoreCorpus
from src.lore.models import LoreChunk, QueryRoute


HASHED_VECTOR_MODEL = "hashed-char-ngram-v1"
HASHED_VECTOR_DIMENSIONS = 2048
HASHED_VECTOR_DISTANCE = "cosine"

QUERY_ALIASES = {
    "粉色妖精小姐": "爱莉希雅",
    "真我·人之律者": "爱莉希雅 人之律者",
    "逐火十三英桀": "英桀 逐火之蛾",
    "十三英桀": "英桀 逐火之蛾",
    "黄金庭园": "黄金庭院",
}


def tokenize(value: str) -> list[str]:
    expansions = " ".join(
        replacement for alias, replacement in QUERY_ALIASES.items() if alias in value
    )
    if expansions:
        value = f"{value} {expansions}"
    compact = re.sub(r"\s+", "", value.lower())
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", compact)
    tokens: list[str] = re.findall(r"[a-z0-9_]+", compact)
    for run in chinese_runs:
        tokens.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
        tokens.extend(run[index : index + 3] for index in range(max(0, len(run) - 2)))
    return tokens


@dataclass(frozen=True)
class RankedChunk:
    chunk: LoreChunk
    score: float


class RetrieverAdapter(Protocol):
    name: str

    def rank(
        self, query: str, chunks: list[LoreChunk], *, top_k: int
    ) -> list[RankedChunk]: ...


class BM25Retriever:
    name = "bm25-char-ngram"

    def rank(
        self, query: str, chunks: list[LoreChunk], *, top_k: int
    ) -> list[RankedChunk]:
        if not chunks:
            return []
        query_terms = tokenize(query)
        if not query_terms:
            return []
        documents = [tokenize(_searchable_text(row)) for row in chunks]
        average_length = sum(len(row) for row in documents) / max(1, len(documents))
        document_frequency = Counter(
            term for document in documents for term in set(document)
        )
        scores: list[RankedChunk] = []
        k1 = 1.5
        b = 0.75
        for chunk, document in zip(chunks, documents):
            frequencies = Counter(document)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency[term]
                inverse = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
                denominator = frequency + k1 * (
                    1 - b + b * len(document) / max(1.0, average_length)
                )
                score += inverse * frequency * (k1 + 1) / denominator
            if score > 0:
                scores.append(RankedChunk(chunk=chunk, score=score))
        return sorted(scores, key=lambda row: (-row.score, row.chunk.chunk_id))[:top_k]


def _searchable_text(chunk: LoreChunk) -> str:
    return "\n".join(
        (
            chunk.title,
            chunk.chapter,
            chunk.scene,
            " ".join(chunk.character_names),
            " ".join(chunk.topic_names),
            chunk.content,
        )
    )


def _hashed_vector(value: str, dimensions: int = HASHED_VECTOR_DIMENSIONS) -> dict[int, float]:
    counts: Counter[int] = Counter()
    for token in tokenize(value):
        index = int.from_bytes(sha256(token.encode("utf-8")).digest()[:4], "big") % dimensions
        counts[index] += 1
    norm = math.sqrt(sum(weight * weight for weight in counts.values()))
    if not norm:
        return {}
    return {index: weight / norm for index, weight in counts.items()}


def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(index, 0.0) for index, weight in left.items())


class HashedVectorIndex:
    """Local sparse vector index with no model download or external credentials."""

    def __init__(
        self,
        signature: str,
        vectors: dict[str, dict[int, float]],
        chunk_hashes: dict[str, str],
    ) -> None:
        self.signature = signature
        self.vectors = vectors
        self.chunk_hashes = chunk_hashes

    @classmethod
    def build(cls, chunks: list[LoreChunk]) -> "HashedVectorIndex":
        return cls(
            signature=LoreCorpus.signature(chunks),
            vectors={row.chunk_id: _hashed_vector(_searchable_text(row)) for row in chunks},
            chunk_hashes={
                row.chunk_id: sha256(row.content.encode("utf-8")).hexdigest()
                for row in chunks
            },
        )

    @classmethod
    def load(cls, path: Path) -> "HashedVectorIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("model_name") != HASHED_VECTOR_MODEL:
            raise ValueError("unsupported lore vector model")
        vectors = {
            str(chunk_id): {int(index): float(weight) for index, weight in value.items()}
            for chunk_id, value in payload.get("vectors", {}).items()
        }
        return cls(
            signature=str(payload.get("corpus_signature", "")),
            vectors=vectors,
            chunk_hashes={
                str(chunk_id): str(digest)
                for chunk_id, digest in payload.get("chunk_hashes", {}).items()
            },
        )

    def write(
        self,
        path: Path,
        *,
        prototype_only: bool,
        build_time_ms: float = 0.0,
    ) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "model_name": HASHED_VECTOR_MODEL,
            "dimensions": HASHED_VECTOR_DIMENSIONS,
            "distance": HASHED_VECTOR_DISTANCE,
            "corpus_signature": self.signature,
            "vector_count": len(self.vectors),
            "prototype_only": prototype_only,
            "production_enabled": False,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "build_time_ms": round(build_time_ms, 3),
            "chunk_hashes": dict(sorted(self.chunk_hashes.items())),
            "vectors": {
                chunk_id: {str(index): weight for index, weight in sorted(vector.items())}
                for chunk_id, vector in sorted(self.vectors.items())
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {
            key: value
            for key, value in payload.items()
            if key not in {"vectors", "chunk_hashes"}
        }


class HashedVectorRetriever:
    name = HASHED_VECTOR_MODEL

    def __init__(self, index: HashedVectorIndex) -> None:
        self._index = index

    def rank(
        self, query: str, chunks: list[LoreChunk], *, top_k: int
    ) -> list[RankedChunk]:
        if any(
            self._index.chunk_hashes.get(row.chunk_id)
            != sha256(row.content.encode("utf-8")).hexdigest()
            for row in chunks
        ):
            raise ValueError("lore vector index is stale for the selected corpus")
        query_vector = _hashed_vector(query)
        query_terms = set(tokenize(query))
        scores: list[RankedChunk] = []
        for chunk in chunks:
            # The prototype vector is lexical, so require an actual token overlap
            # to prevent hash collisions from becoming false semantic matches.
            if not query_terms.intersection(tokenize(_searchable_text(chunk))):
                continue
            score = _cosine(query_vector, self._index.vectors.get(chunk.chunk_id, {}))
            if score > 0:
                scores.append(RankedChunk(chunk=chunk, score=score))
        return sorted(scores, key=lambda row: (-row.score, row.chunk.chunk_id))[:top_k]


def reciprocal_rank_fusion(
    rankings: Iterable[list[RankedChunk]],
    *,
    route: QueryRoute,
    top_k: int,
    rank_constant: int = 60,
) -> list[RankedChunk]:
    scores: dict[str, float] = defaultdict(float)
    chunks: dict[str, LoreChunk] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, 1):
            scores[row.chunk.chunk_id] += 1.0 / (rank_constant + rank)
            chunks[row.chunk.chunk_id] = row.chunk
    preferred = {
        "official_fact": "official_lore",
        "dialogue": "bh3text_dialogue",
        "navigation": "story_navigation",
    }.get(route)
    if preferred:
        for chunk_id, chunk in chunks.items():
            if chunk.corpus == preferred:
                scores[chunk_id] += 0.002
    ranked_ids = sorted(
        scores,
        key=lambda chunk_id: (
            0 if preferred and chunks[chunk_id].corpus == preferred else 1,
            -scores[chunk_id],
            chunk_id,
        ),
    )[:top_k]
    return [RankedChunk(chunks[chunk_id], scores[chunk_id]) for chunk_id in ranked_ids]
