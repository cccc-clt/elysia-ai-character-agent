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
from src.lore.embeddings import EmbeddingBackend, normalized_vector
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
    "约束的惨剧": "约束惨剧",
    "帕朵": "帕朵菲莉丝",
}
SINGLE_CHARACTER_ENTITIES = ("华", "苏", "樱")


def _single_character_entity_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    left = r"(?:^|[\s\n：:、，。！？「」『』【】/\\\-]|关于)"
    right = r"(?:$|[\s\n：:、，。！？「」『』【】/\\\-]|如何|怎么|怎样|的|与|和|说|评价|谈)"
    for name in SINGLE_CHARACTER_ENTITIES:
        if re.search(left + re.escape(name) + right, value):
            tokens.append(f"entity:{name}")
    return tokens


def tokenize(value: str) -> list[str]:
    entity_tokens = _single_character_entity_tokens(value)
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
    return [*tokens, *entity_tokens]


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
    explicit_entity_tokens = set(
        _single_character_entity_tokens(f"{chunk.title}\n{chunk.content}")
    )
    searchable_characters = (
        name
        for name in chunk.character_names
        if len(name) > 1 or f"entity:{name}" in explicit_entity_tokens
    )
    return "\n".join(
        (
            chunk.title,
            chunk.title,
            chunk.chapter,
            chunk.scene,
            " ".join(searchable_characters),
            " ".join(chunk.topic_names),
            chunk.content,
        )
    )


def _chunk_fingerprint(chunk: LoreChunk) -> str:
    return sha256(_searchable_text(chunk).encode("utf-8")).hexdigest()


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
                row.chunk_id: _chunk_fingerprint(row)
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
            self._index.chunk_hashes.get(row.chunk_id) != _chunk_fingerprint(row)
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


class SemanticVectorIndex:
    """Portable dense index created by a configured local embedding adapter."""

    def __init__(
        self,
        *,
        backend_name: str,
        model_name: str,
        dimensions: int,
        signature: str,
        vectors: dict[str, list[float]],
        chunk_hashes: dict[str, str],
    ) -> None:
        self.backend_name = backend_name
        self.model_name = model_name
        self.dimensions = dimensions
        self.signature = signature
        self.vectors = vectors
        self.chunk_hashes = chunk_hashes

    @classmethod
    def build(
        cls,
        chunks: list[LoreChunk],
        backend: EmbeddingBackend,
    ) -> "SemanticVectorIndex":
        vectors = [
            normalized_vector(vector)
            for vector in backend.encode([_searchable_text(row) for row in chunks])
        ]
        if len(vectors) != len(chunks):
            raise ValueError("semantic vector count does not match lore chunks")
        dimensions = len(vectors[0]) if vectors else 0
        if not dimensions or any(len(vector) != dimensions for vector in vectors):
            raise ValueError("invalid semantic vector dimensions")
        return cls(
            backend_name=backend.name,
            model_name=backend.model_name,
            dimensions=dimensions,
            signature=LoreCorpus.signature(chunks),
            vectors={row.chunk_id: vector for row, vector in zip(chunks, vectors)},
            chunk_hashes={row.chunk_id: _chunk_fingerprint(row) for row in chunks},
        )

    @classmethod
    def load(cls, path: Path) -> "SemanticVectorIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("index_type") != "dense_semantic":
            raise ValueError("unsupported lore semantic index")
        vectors = {
            str(chunk_id): [float(value) for value in vector]
            for chunk_id, vector in payload.get("vectors", {}).items()
        }
        dimensions = int(payload.get("dimensions", 0))
        if not dimensions or any(len(vector) != dimensions for vector in vectors.values()):
            raise ValueError("invalid lore semantic index dimensions")
        return cls(
            backend_name=str(payload.get("embedding_backend", "")),
            model_name=str(payload.get("model_name", "")),
            dimensions=dimensions,
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
            "schema_version": 2,
            "index_type": "dense_semantic",
            "embedding_backend": self.backend_name,
            "model_name": self.model_name,
            "dimensions": self.dimensions,
            "distance": "cosine",
            "corpus_signature": self.signature,
            "vector_count": len(self.vectors),
            "prototype_only": prototype_only,
            "production_enabled": False,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "build_time_ms": round(build_time_ms, 3),
            "chunk_hashes": dict(sorted(self.chunk_hashes.items())),
            "vectors": {
                chunk_id: vector
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


class SemanticVectorRetriever:
    name = "semantic-vector"

    def __init__(
        self,
        index: SemanticVectorIndex,
        backend: EmbeddingBackend,
    ) -> None:
        self._index = index
        self._backend = backend

    def rank(
        self, query: str, chunks: list[LoreChunk], *, top_k: int
    ) -> list[RankedChunk]:
        if (
            self._index.backend_name != self._backend.name
            or self._index.model_name != self._backend.model_name
            or any(
                self._index.chunk_hashes.get(row.chunk_id) != _chunk_fingerprint(row)
                for row in chunks
            )
        ):
            raise ValueError("lore semantic index is stale or uses another model")
        encoded = self._backend.encode([query])
        if not encoded or len(encoded[0]) != self._index.dimensions:
            raise ValueError("semantic query vector dimensions do not match index")
        query_vector = normalized_vector(encoded[0])
        scores = [
            RankedChunk(
                chunk=row,
                score=sum(
                    left * right
                    for left, right in zip(
                        query_vector,
                        self._index.vectors.get(row.chunk_id, []),
                    )
                ),
            )
            for row in chunks
            if row.chunk_id in self._index.vectors
        ]
        return sorted(
            (row for row in scores if row.score > 0),
            key=lambda row: (-row.score, row.chunk.chunk_id),
        )[:top_k]


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
