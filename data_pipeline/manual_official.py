"""Strict manual-official import and review without model completion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from data_pipeline.config import PipelinePaths
from data_pipeline.schemas import ManualOfficialRecord
from data_pipeline.utils import write_jsonl


class ManualRecordValidationError(ValueError):
    """Raised when manual source material is missing required provenance."""


def _record_payloads(path: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not path.exists():
        return []
    files = [path] if path.is_file() else sorted(
        candidate
        for candidate in path.iterdir()
        if candidate.suffix.lower() in {".yaml", ".yml", ".json"}
    )
    output: list[tuple[Path, dict[str, Any]]] = []
    for file_path in files:
        if file_path.suffix.lower() == ".json":
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict):
                raise ManualRecordValidationError(
                    f"Manual record must be an object: {file_path.name}"
                )
            output.append((file_path, value))
    return output


def load_manual_records(
    path: Path,
    *,
    expected_status: str | None = None,
) -> list[ManualOfficialRecord]:
    records: list[ManualOfficialRecord] = []
    errors: list[str] = []
    for file_path, payload in _record_payloads(path):
        try:
            record = ManualOfficialRecord.model_validate(payload)
        except ValueError as exc:
            errors.append(f"{file_path.name}: {exc}")
            continue
        if expected_status and record.review_status != expected_status:
            errors.append(
                f"{file_path.name}: review_status must be {expected_status}, "
                f"got {record.review_status}"
            )
            continue
        records.append(record)
    ids = [record.record_id for record in records]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate manual record_id values are not allowed")
    if errors:
        raise ManualRecordValidationError("; ".join(errors))
    return records


def import_manual_records(
    input_path: Path,
    paths: PipelinePaths | None = None,
) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    records = load_manual_records(input_path, expected_status="pending")
    write_jsonl(
        paths.manual_pending_index,
        [record.model_dump(mode="json") for record in records],
    )
    return {
        "validated_pending_records": len(records),
        "accepted_records": 0,
        "rag_eligible_records": 0,
    }


def accepted_manual_records(
    paths: PipelinePaths | None = None,
) -> list[ManualOfficialRecord]:
    paths = paths or PipelinePaths()
    # Valid pending files placed in accepted are ignored safely; invalid records
    # still raise because their provenance cannot be audited.
    records = load_manual_records(paths.manual_accepted_dir)
    return [record for record in records if record.review_status == "accepted"]


def review_manual_records(paths: PipelinePaths | None = None) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    pending = load_manual_records(paths.manual_inbox_dir, expected_status="pending")
    accepted_all = load_manual_records(paths.manual_accepted_dir)
    accepted = [row for row in accepted_all if row.review_status == "accepted"]
    misplaced_pending = [row for row in accepted_all if row.review_status == "pending"]
    lines = [
        "# 人工官方资料审核",
        "",
        "> 本命令只生成审核清单，不自动确认、移动或补写任何字段。",
        "",
        "## Inbox pending",
        "",
        "| record_id | 标题 | 游戏位置 | 章节 | 角色 | 来源说明 | 人工决定 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in pending:
        lines.append(
            f"| {row.record_id} | {row.title} | {row.game_section} | "
            f"{row.chapter} | {'、'.join(row.character_names)} | "
            f"{row.source_note[:80]} | accept/reject（待填写） |"
        )
    if not pending:
        lines.append("| - | 无 | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## Accepted directory",
            "",
            f"- 已审核 accepted：{len(accepted)}",
            f"- 错放在 accepted 但仍为 pending：{len(misplaced_pending)}（不会进入RAG）",
            "",
            "审核流程：人工核对游戏位置与原文证据，将文件的 `review_status` 改为 "
            "`accepted` 后，再由人工移动到 accepted 目录。",
        ]
    )
    paths.manual_review.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "pending_records": len(pending),
        "accepted_records": len(accepted),
        "misplaced_pending_records": len(misplaced_pending),
    }
