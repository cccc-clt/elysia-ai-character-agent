"""Sentence-aware chunking and Markdown/JSONL RAG export."""

from __future__ import annotations

import re
from pathlib import Path

from data_pipeline.config import PipelinePaths
from data_pipeline.manual_official import accepted_manual_records
from data_pipeline.normalizer import ENTITY_CATALOG
from data_pipeline.schemas import ChunkMetadata, CleanedDocument, RagChunk
from data_pipeline.utils import read_jsonl, safe_filename, stable_id, utc_now, write_jsonl


SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])")


def _split_long_unit(unit: str, max_chars: int) -> list[str]:
    if len(unit) <= max_chars:
        return [unit]
    parts: list[str] = []
    remaining = unit
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        boundary = max(
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind("；"),
            window.rfind("，"),
        )
        cut = boundary + 1 if boundary >= max_chars // 2 else max_chars
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _text_units(text: str, max_chars: int) -> list[str]:
    units: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "- ", "* ", "• ")):
            line_units = [stripped]
        else:
            line_units = [item.strip() for item in SENTENCE_BOUNDARY.split(stripped) if item.strip()]
        for unit in line_units:
            units.extend(_split_long_unit(unit, max_chars))
    return units


def _overlap_units(units: list[str], overlap_chars: int) -> list[str]:
    selected: list[str] = []
    length = 0
    for unit in reversed(units):
        if selected and length + len(unit) > overlap_chars:
            break
        selected.append(unit)
        length += len(unit)
        if length >= overlap_chars:
            break
    return list(reversed(selected))


def split_text(
    text: str,
    *,
    target_chars: int = 700,
    min_chars: int = 500,
    max_chars: int = 900,
    overlap_chars: int = 100,
) -> list[str]:
    if not (0 < overlap_chars < min_chars <= target_chars <= max_chars):
        raise ValueError("Invalid chunk size configuration")
    units = _text_units(text, max_chars)
    if not units:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for unit in units:
        projected = current_length + len(unit) + (1 if current else 0)
        if current and projected > max_chars:
            chunk = "\n".join(current).strip()
            chunks.append(chunk)
            current = _overlap_units(current, overlap_chars)
            current_length = sum(len(item) for item in current) + max(0, len(current) - 1)
        current.append(unit)
        current_length += len(unit) + (1 if len(current) > 1 else 0)
        if current_length >= target_chars:
            chunk = "\n".join(current).strip()
            chunks.append(chunk)
            current = _overlap_units(current, overlap_chars)
            current_length = sum(len(item) for item in current) + max(0, len(current) - 1)
    final = "\n".join(current).strip()
    if final:
        if chunks and len(final) < min_chars:
            candidate = chunks[-1] + "\n" + final
            if len(candidate) <= max_chars:
                chunks[-1] = candidate
            elif final not in chunks[-1]:
                chunks.append(final)
        elif not chunks or final != chunks[-1]:
            chunks.append(final)
    return list(dict.fromkeys(chunk for chunk in chunks if chunk))


def _metadata_values(content: str) -> tuple[list[str], list[str], list[str]]:
    entities: list[str] = []
    for name in ENTITY_CATALOG:
        if len(name) == 1:
            pattern = rf"(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(name)}(?![\u4e00-\u9fffA-Za-z0-9])"
            if re.search(pattern, content):
                entities.append(name)
        elif name in content:
            entities.append(name)
    era = [value for value in ("前文明", "现文明") if value in content]
    universe = [value for value in ("本征世界", "世界泡") if value in content]
    return entities, era, universe


def build_rag(paths: PipelinePaths | None = None) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    all_documents = [
        CleanedDocument.model_validate(row)
        for row in read_jsonl(paths.cleaned_documents)
    ]
    documents = [
        document
        for document in all_documents
        if document.quality_status == "accepted"
    ]
    chunks: list[RagChunk] = []
    for document in documents:
        for index, content in enumerate(split_text(document.content), 1):
            chunk_id = stable_id(
                "chunk", f"{document.document_id}:{index}:{content}"
            )
            entities, era, universe = _metadata_values(content)
            metadata = ChunkMetadata(
                title=document.title,
                source_url=document.canonical_url,
                source_type=document.source_type,
                source_tier="A",
                entity_names=entities,
                era=era,
                universe=universe,
                retrieved_at=document.retrieved_at,
                document_id=document.document_id,
                chunk_id=chunk_id,
            )
            chunk = RagChunk(chunk_id=chunk_id, content=content, metadata=metadata)
            chunks.append(chunk)

    manual_records = accepted_manual_records(paths)
    for record in manual_records:
        manual_content = (
            f"{record.title}\n"
            f"## 人工摘要\n{record.summary}\n"
            f"## 原文证据\n{record.evidence}"
        )
        document_id = stable_id("manual-doc", record.record_id)
        for index, content in enumerate(split_text(manual_content), 1):
            chunk_id = stable_id(
                "chunk", f"official_game_manual:{record.record_id}:{index}:{content}"
            )
            entities = list(dict.fromkeys([
                *record.character_names,
                *_metadata_values(content)[0],
            ]))
            metadata = ChunkMetadata(
                title=record.title,
                source_url=f"manual-official://{record.record_id}",
                source_type=record.source_type,
                source_tier="A-manual",
                source_note=record.source_note,
                entity_names=entities,
                era=[record.era] if record.era else [],
                universe=[record.universe] if record.universe else [],
                retrieved_at=utc_now(),
                document_id=document_id,
                chunk_id=chunk_id,
            )
            chunks.append(RagChunk(chunk_id=chunk_id, content=content, metadata=metadata))

    write_jsonl(paths.chunks, [chunk.model_dump(mode="json") for chunk in chunks])
    paths.markdown_dir.mkdir(parents=True, exist_ok=True)
    for existing in paths.markdown_dir.glob("*.md"):
        existing.unlink()
    for chunk in chunks:
        title = safe_filename(chunk.metadata.title)
        output = paths.markdown_dir / f"{title}-{chunk.chunk_id}.md"
        header = (
            f"# {chunk.metadata.title}\n\n"
            f"- Source: {chunk.metadata.source_url}\n"
            f"- Source type: {chunk.metadata.source_type}\n"
            f"- Source tier: {chunk.metadata.source_tier}\n"
            f"- Source note: {chunk.metadata.source_note}\n"
            f"- Document ID: {chunk.metadata.document_id}\n"
            f"- Chunk ID: {chunk.chunk_id}\n"
            f"- Retrieved at: {chunk.metadata.retrieved_at.isoformat()}\n\n"
        )
        output.write_text(header + chunk.content + "\n", encoding="utf-8")
    return {
        "cleaned_documents": len(all_documents),
        "accepted_documents": len(documents),
        "manual_accepted_documents": len(manual_records),
        "chunks": len(chunks),
    }
