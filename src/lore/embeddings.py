"""Optional local semantic embedding adapters for the lore retrieval seam."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence


DEFAULT_CHINESE_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"


class EmbeddingBackendUnavailable(RuntimeError):
    """Raised when an optional local embedding backend cannot be used."""


class EmbeddingBackend(Protocol):
    name: str
    model_name: str

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


def normalized_vector(vector: Sequence[float]) -> list[float]:
    """Return a finite unit vector for backend-independent cosine scoring."""

    values = [float(value) for value in vector]
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("semantic embedding contains no finite vector")
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        raise ValueError("semantic embedding vector has zero norm")
    return [value / norm for value in values]


class SentenceTransformerEmbeddingBackend:
    """Lazy, local-first adapter for real sentence-transformers embeddings.

    The adapter never downloads by default.  Callers must explicitly set
    ``local_files_only=False`` when a model download has been approved.
    """

    name = "sentence-transformers"

    def __init__(
        self,
        model_name: str = DEFAULT_CHINESE_EMBEDDING_MODEL,
        *,
        device: str = "cpu",
        cache_dir: Path | None = None,
        local_files_only: bool = True,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.cache_dir = cache_dir
        self.local_files_only = local_files_only
        self._model_factory = model_factory
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        factory = self._model_factory
        if factory is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingBackendUnavailable(
                    "sentence_transformers_package_missing"
                ) from exc
            factory = SentenceTransformer
        kwargs: dict[str, Any] = {
            "device": self.device,
            "local_files_only": self.local_files_only,
        }
        if self.cache_dir is not None:
            kwargs["cache_folder"] = str(self.cache_dir)
        try:
            self._model = factory(self.model_name, **kwargs)
        except Exception as exc:
            reason = type(exc).__name__
            raise EmbeddingBackendUnavailable(
                f"local_semantic_model_unavailable:{reason}"
            ) from exc
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        try:
            encoded = model.encode(
                list(texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            rows = encoded.tolist() if hasattr(encoded, "tolist") else encoded
            output = [normalized_vector(row) for row in rows]
        except EmbeddingBackendUnavailable:
            raise
        except Exception as exc:
            raise EmbeddingBackendUnavailable(
                f"semantic_embedding_failed:{type(exc).__name__}"
            ) from exc
        if len(output) != len(texts) or any(not row for row in output):
            raise EmbeddingBackendUnavailable("semantic_embedding_shape_invalid")
        dimension = len(output[0])
        if any(len(row) != dimension for row in output):
            raise EmbeddingBackendUnavailable("semantic_embedding_dimensions_inconsistent")
        return output
