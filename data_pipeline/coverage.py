"""Evidence-calibrated topic coverage and manual-source gap reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from data_pipeline.config import PipelinePaths
from data_pipeline.manual_official import accepted_manual_records
from data_pipeline.review_workbench import build_review_workbench
from data_pipeline.schemas import (
    BH3TextChunk,
    BH3TextDocument,
    BilibiliVideoMetadata,
    CleanedDocument,
    CoverageEvidenceLayer,
    CoverageRecord,
    LoreEntity,
    LoreRelation,
    PotentialVideoSource,
    RagChunk,
)
from data_pipeline.utils import read_json, read_jsonl, utc_now, write_json


TOPICS: tuple[tuple[str, str, str], ...] = (
    ("elysia", "爱莉希雅", "character"),
    ("kevin", "凯文", "character"),
    ("aponia", "阿波尼亚", "character"),
    ("eden", "伊甸", "character"),
    ("vill_v", "维尔薇", "character"),
    ("kalpas", "千劫", "character"),
    ("su", "苏", "character"),
    ("sakura", "樱", "character"),
    ("kosma", "科斯魔", "character"),
    ("mobius", "梅比乌斯", "character"),
    ("griseo", "格蕾修", "character"),
    ("hua", "华", "character"),
    ("pardofelis", "帕朵菲莉丝", "character"),
    ("dr_mei", "梅博士", "character"),
    ("raiden_mei", "雷电芽衣", "character"),
    ("moth", "逐火之蛾", "organization"),
    ("thirteen_flame_chasers", "逐火十三英桀", "organization"),
    ("elysian_realm", "往世乐土", "concept"),
    ("everlasting_elysium", "永世乐土", "concept"),
    ("previous_era", "前文明", "concept"),
    ("mantis", "融合战士", "concept"),
    ("memory_simulacrum", "记忆体", "concept"),
    ("herrscher_of_human", "人之律者", "concept"),
    ("herrscher_of_origin", "始源之律者", "concept"),
    ("herrscher_of_corruption", "侵蚀之律者", "concept"),
    ("tragedy_of_binding", "约束惨剧", "concept"),
    ("finality", "终焉", "concept"),
)

TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "爱莉希雅": ("爱莉希雅", "真我·人之律者", "粉色妖精小姐", "粉色妖精小姐♪"),
    "帕朵菲莉丝": ("帕朵菲莉丝", "菲莉丝", "帕朵"),
    "雷电芽衣": ("雷电芽衣", "芽衣"),
    "华": ("华", "符华"),
    "樱": ("樱",),
    "逐火十三英桀": ("逐火十三英桀", "逐火十三英杰", "十三英桀", "十三英杰"),
    "约束惨剧": ("约束惨剧", "约束的惨剧"),
}

SUBSTANTIVE_MARKERS = (
    "身份",
    "经历",
    "所属",
    "组织",
    "成员",
    "加入",
    "担任",
    "创建",
    "诞生",
    "出生",
    "来自",
    "成为",
    "曾经",
    "过去",
    "故事",
    "设定",
    "档案",
    "文明",
    "时代",
    "律者",
    "融合战士",
    "记忆",
    "使命",
    "牺牲",
    "领导",
    "领袖",
    "目的",
    "职责",
    "关系",
    "参与",
)

MENTION_ONLY_MARKERS = (
    "在宿舍",
    "不在宿舍",
    "宿舍对话",
    "技能",
    "配队",
    "阵容",
    "关卡",
    "玩法",
    "完成补给",
    "MVP",
    "好感度",
    "角色标签",
    "导航",
)

EvidenceKind = Literal["direct_evidence", "substantial_evidence", "mention_only"]


@dataclass(frozen=True)
class EvidenceAssessment:
    kind: EvidenceKind
    reason: str


def _aliases(topic: str) -> tuple[str, ...]:
    return TOPIC_ALIASES.get(topic, (topic,))


def _term_present(text: str, term: str) -> bool:
    if len(term) == 1:
        return bool(
            re.search(
                rf"(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(term)}"
                rf"(?![\u4e00-\u9fffA-Za-z0-9])",
                text,
            )
        )
    return term in text


def _topic_present(text: str, topic: str) -> bool:
    return any(_term_present(text, alias) for alias in _aliases(topic))


def _topic_occurrences(text: str, topic: str) -> int:
    total = 0
    for alias in _aliases(topic):
        if len(alias) == 1:
            total += len(
                re.findall(
                    rf"(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(alias)}"
                    rf"(?![\u4e00-\u9fffA-Za-z0-9])",
                    text,
                )
            )
        else:
            total += text.count(alias)
    return total


def _title_centered(title: str, topic: str) -> bool:
    title_core = re.split(r"[-—_|【]", title, maxsplit=1)[0].strip()
    return _topic_present(title_core, topic)


def _topic_count(text: str) -> int:
    return sum(_topic_present(text, topic_name) for _, topic_name, _ in TOPICS)


def _looks_like_list_or_navigation(text: str) -> bool:
    if any(marker in text for marker in MENTION_ONLY_MARKERS):
        return True
    if _topic_count(text) >= 4:
        return True
    compact = re.sub(r"\s+", "", text)
    separators = sum(compact.count(value) for value in ("|", "、", "/", "，"))
    return separators >= 4 and len(compact) < 180


def _substantial_segments(content: str, topic: str) -> list[str]:
    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[。！？!?；;])|\n+", content)
        if segment.strip()
    ]
    output: list[str] = []
    for segment in segments:
        if not _topic_present(segment, topic):
            continue
        if _looks_like_list_or_navigation(segment):
            continue
        chinese = len(re.findall(r"[\u4e00-\u9fff]", segment))
        has_marker = any(marker in segment for marker in SUBSTANTIVE_MARKERS)
        if chinese >= 45 or (chinese >= 28 and has_marker):
            output.append(segment)
    return output


def _section_heading_centered(content: str, topic: str) -> bool:
    for line in [value.strip() for value in content.splitlines() if value.strip()][:8]:
        normalized = line.strip("# -*：:")
        if any(
            normalized == alias
            or normalized.startswith(f"{alias}-")
            or normalized.startswith(f"{alias}—")
            or normalized.startswith(f"{alias}：")
            for alias in _aliases(topic)
        ):
            return True
    return False


def classify_chunk_evidence(
    chunk: RagChunk,
    topic: str,
    *,
    manual_direct: bool = False,
) -> EvidenceAssessment | None:
    """Classify a main-RAG chunk without treating co-occurrence as coverage."""

    title_direct = _topic_present(chunk.metadata.title, topic)
    content_present = _topic_present(chunk.content, topic)
    metadata_present = any(
        entity == topic or entity in _aliases(topic)
        for entity in chunk.metadata.entity_names
    )
    if not (title_direct or content_present or metadata_present or manual_direct):
        return None
    if manual_direct:
        return EvidenceAssessment(
            "direct_evidence",
            "人工 accepted 记录明确把该主题标为直接资料。",
        )
    if title_direct:
        return EvidenceAssessment(
            "direct_evidence",
            "页面标题直接以该主题或其明确别名为中心。",
        )
    if _section_heading_centered(chunk.content, topic):
        return EvidenceAssessment(
            "direct_evidence",
            "当前章节/段落标题直接以该主题为中心。",
        )
    substantial = _substantial_segments(chunk.content, topic)
    occurrences = _topic_occurrences(chunk.content, topic)
    if occurrences >= 3 and substantial and any(
        marker in chunk.content for marker in SUBSTANTIVE_MARKERS
    ):
        return EvidenceAssessment(
            "direct_evidence",
            "chunk 中该主题至少出现3次，并包含身份、经历、组织或设定描述。",
        )
    if len(substantial) >= 2 or sum(len(value) for value in substantial) >= 120:
        return EvidenceAssessment(
            "direct_evidence",
            "连续正文主要介绍该主题。",
        )
    if substantial:
        return EvidenceAssessment(
            "substantial_evidence",
            "非专属页面中存在至少一个完整的实质介绍段落。",
        )
    return EvidenceAssessment(
        "mention_only",
        "仅有名字、标签、名单、同页共现或一句非实质描述。",
    )


def calculate_coverage_status(
    *,
    direct_evidence_chunks: int,
    substantial_evidence_chunks: int,
    distinct_documents: int,
    distinct_official_documents: int,
    dedicated_page_available: bool,
    confirmed_entities: int,
    confirmed_relations: int,
) -> str:
    confirmed = confirmed_entities + confirmed_relations
    if (
        distinct_official_documents >= 3
        and direct_evidence_chunks >= 5
        and confirmed >= 1
    ):
        return "strong"
    if (
        direct_evidence_chunks >= 2
        and distinct_documents >= 2
    ) or (
        dedicated_page_available
        and direct_evidence_chunks >= 3
    ):
        return "usable"
    if direct_evidence_chunks == 0 and substantial_evidence_chunks == 0:
        return "missing"
    return "thin"


def _coverage_reason(
    status: str,
    *,
    direct: int,
    substantial: int,
    mentions: int,
    documents: int,
    official_documents: int,
    dedicated: bool,
    confirmed: int,
) -> str:
    if status == "strong":
        return (
            f"有{official_documents}个独立官方文档、{direct}个direct chunks，"
            f"且有{confirmed}项人工确认实体/关系，满足strong门槛。"
        )
    if status == "usable":
        if direct >= 2 and documents >= 2:
            return (
                f"有{direct}个direct chunks且来自{documents}个独立文档，"
                "满足usable的多文档门槛。"
            )
        return (
            f"存在专属官方页面并有{direct}个direct chunks，"
            "满足usable的专属页门槛。"
        )
    if status == "thin":
        if direct:
            return (
                f"只有{direct}个direct chunks、{documents}个独立文档；"
                "尚未满足usable所需的多文档或专属页证据数量。"
            )
        return (
            f"没有direct evidence，但有{substantial}个substantial chunks；"
            "因此只能判定为thin。"
        )
    return (
        f"direct和substantial均为0；{mentions}个mention-only chunks"
        "不参与覆盖状态提升。"
    )


def _missing_information(
    *,
    direct: int,
    substantial: int,
    documents: int,
    dedicated: bool,
    confirmed: int,
    manual_documents: int,
) -> list[str]:
    output: list[str] = []
    if direct == 0:
        output.append("直接介绍该主题的证据")
    if direct < 2 or documents < 2:
        output.append("至少2个direct chunks且来自2个独立文档")
    if not dedicated and direct < 3:
        output.append("角色/主题专属官方页面或更多直接证据")
    if substantial == 0:
        output.append("非专属页面中的完整实质段落")
    if manual_documents == 0:
        output.append("游戏内官方资料人工摘录")
    if confirmed == 0:
        output.append("人工确认实体或关系")
    return list(dict.fromkeys(output))


def _recommended_action(topic_name: str, topic_type: str, status: str) -> str:
    if status in {"usable", "strong"}:
        return "继续人工核对证据与关系，不把名单或同页共现计为新覆盖。"
    if topic_type == "character":
        return (
            f"从游戏内角色档案、英桀档案或往世乐土追忆人工补充{topic_name}的"
            "身份、经历、时代、关系和逐字证据。"
        )
    return (
        f"从主线剧情、往世乐土追忆或组织档案人工补充{topic_name}的定义、"
        "时间范围、参与者、影响和逐字证据。"
    )


def _validated_rows(path: Path, model: Any) -> list[Any]:
    output: list[Any] = []
    for row in read_jsonl(path):
        try:
            output.append(model.model_validate(row))
        except ValueError:
            continue
    return output


def _potential_video_sources(
    paths: PipelinePaths,
    topic_name: str,
) -> list[PotentialVideoSource]:
    output: list[PotentialVideoSource] = []
    rows = _validated_rows(paths.video_audit_jsonl, BilibiliVideoMetadata)
    for row in rows:
        text = "\n".join(
            [
                row.title,
                row.description,
                *(part.title for part in row.parts),
            ]
        )
        matched = (
            topic_name in row.observed_characters
            or topic_name in row.observed_topics
            or _topic_present(text, topic_name)
        )
        if not matched:
            continue
        subtitle_note = (
            "页面元数据未提供公开字幕"
            if not row.subtitle_available
            else "公开字幕尚未进行内容人工核验"
        )
        output.append(
            PotentialVideoSource(
                video_id=row.video_id,
                reason=(
                    f"元数据可能涉及{topic_name}；分类为"
                    f"{row.content_type}/{row.source_tier}，{subtitle_note}，"
                    "不能计入direct或substantial evidence。"
                ),
            )
        )
    return sorted(output, key=lambda item: item.video_id)


def _write_gap_report(
    paths: PipelinePaths,
    records: list[CoverageRecord],
    metrics: dict[str, Any],
) -> None:
    helper_navigation = read_jsonl(paths.bh3helper_navigation)
    helper_archives = read_jsonl(paths.bh3helper_archive_candidates)
    helper_links = read_jsonl(paths.bh3helper_official_links)

    def helper_matches(row: dict[str, Any], topic: str) -> bool:
        values = [
            str(row.get("title", "")),
            str(row.get("story_arc", "")),
            str(row.get("chapter_number", "")),
            *[str(value) for value in row.get("character_names", [])],
            *[str(value) for value in row.get("topic_names", [])],
        ]
        return any(_topic_present(value, topic) for value in values)

    unmet = [
        record for record in records if record.coverage_status in {"missing", "thin"}
    ]
    lines = [
        "# 人工官方资料缺口",
        "",
        "> 官方网页公开资料不足。mention-only与未审核视频不提升覆盖状态；清单不包含模型补写内容。",
        "",
        "## 阶段最低目标检查",
        "",
        f"- 爱莉希雅 usable：{metrics['elysia_usable']}",
        f"- 逐火十三英桀 usable：{metrics['thirteen_usable']}",
        f"- 往世乐土 usable：{metrics['realm_usable']}",
        f"- 非 missing 英桀人数：{metrics['covered_flame_chasers']} / 8（最低目标）",
        f"- 有效官方详情文档：{metrics['accepted_official_documents']} / 10",
        f"- accepted chunks：{metrics['accepted_chunks']} / 30",
        "",
        "## 需要人工补充的主题与字段",
        "",
        "| 主题 | 状态 | D/S/M | 独立文档 | 剧情助手页面 | 角色档案 | 英桀档案 | 追忆 | 官方PV候选 | BH3Text正文 | 推荐下一步 | 人工审核 |",
        "|---|---|---|---:|---|---|---|---|---|---|---|---|",
    ]
    for record in unmet:
        navigation_matches = [
            row for row in helper_navigation if helper_matches(row, record.topic_name)
        ]
        archive_matches = [
            row for row in helper_archives if helper_matches(row, record.topic_name)
        ]
        source_urls = {str(row.get("source_url", "")) for row in navigation_matches}
        pv_candidates = [
            row
            for row in helper_links
            if str(row.get("discovered_from", "")) in source_urls
            and row.get("material_type") == "official_pv"
        ]
        archive_types = {str(row.get("archive_type", "")) for row in archive_matches}
        helper_page = "是" if navigation_matches else "否"
        bh3text_available = (
            record.bh3text_transcript_coverage.direct_evidence_chunks > 0
            or record.bh3text_transcript_coverage.substantial_evidence_chunks > 0
        )
        if pv_candidates:
            next_step = "先核验官方PV目标账号/域名，再交由官方采集器处理"
        elif archive_matches:
            next_step = "人工核验剧情助手档案来源与文本边界"
        elif navigation_matches:
            next_step = "沿剧情助手入口核验BH3Text场景或原始官方物料"
        else:
            next_step = "游戏内档案/追忆人工补录并保留章节证据"
        lines.append(
            f"| {record.topic_name} | {record.coverage_status} | "
            f"{record.direct_evidence_chunks}/{record.substantial_evidence_chunks}/"
            f"{record.mention_only_chunks} | {record.distinct_documents} | "
            f"{helper_page} | "
            f"{'是' if 'character_archive' in archive_types else '否'} | "
            f"{'是' if 'flame_chaser_archive' in archive_types else '否'} | "
            f"{'是' if 'recollection' in archive_types else '否'} | "
            f"{'有（未核验）' if pv_candidates else '无'} | "
            f"{'有' if bh3text_available else '无'} | {next_step} | 是 |"
        )
    if not unmet:
        lines.append("| - | 无缺口 | - | 0 | - | - | - | - | - | - | - | - |")
    paths.manual_source_gap.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_calibration_report(
    path: Path,
    records: list[CoverageRecord],
    previous_statuses: dict[str, str],
) -> None:
    lines = [
        "# 知识覆盖度校准报告",
        "",
        "> 本报告按direct/substantial/mention-only重新计算；同一document_id只算一个独立文档，未审核视频仅列为潜在线索。",
        "",
        f"- 校准后 usable：{sum(row.coverage_status == 'usable' for row in records)}",
        f"- 校准后 strong：{sum(row.coverage_status == 'strong' for row in records)}",
        f"- 状态发生变化：{sum(previous_statuses.get(row.topic_name) not in {None, row.coverage_status} for row in records)}",
        "",
        "| 主题 | 校准前 | 校准后 | D/S/M | 独立文档/官方文档 | 专属页 | confirmed实体/关系 | 证据URL | 缺失资料 | 潜在视频 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in records:
        previous = previous_statuses.get(row.topic_name, "not_available")
        urls = "<br>".join(row.evidence_urls) or "-"
        videos = "、".join(item.video_id for item in row.potential_video_sources) or "-"
        lines.append(
            f"| {row.topic_name} | {previous} | {row.coverage_status} | "
            f"{row.direct_evidence_chunks}/{row.substantial_evidence_chunks}/"
            f"{row.mention_only_chunks} | {row.distinct_documents}/"
            f"{row.distinct_official_documents} | "
            f"{'是' if row.dedicated_page_available else '否'} | "
            f"{row.confirmed_entities}/{row.confirmed_relations} | {urls} | "
            f"{'、'.join(row.missing_information)} | {videos} |"
        )
        lines.extend(
            [
                "",
                f"- **{row.topic_name}**：{row.coverage_reason}",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _calibration_baseline(
    previous: dict[str, Any],
    report_path: Path,
    current_statuses: dict[str, str],
) -> dict[str, str]:
    stored = previous.get("calibration_baseline_statuses")
    if isinstance(stored, dict):
        return {str(key): str(value) for key, value in stored.items()}
    if report_path.exists():
        recovered: dict[str, str] = {}
        valid = {"missing", "thin", "usable", "strong"}
        for line in report_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 3 and cells[1] in valid:
                recovered[cells[0]] = cells[1]
        if recovered:
            return recovered
    return current_statuses


def _evidence_layer(
    *,
    direct: int,
    substantial: int,
    mentions: int,
    documents: int,
    official_documents: int,
    dedicated: bool,
    confirmed_entities: int,
    confirmed_relations: int,
    evidence_urls: list[str],
) -> CoverageEvidenceLayer:
    status = calculate_coverage_status(
        direct_evidence_chunks=direct,
        substantial_evidence_chunks=substantial,
        distinct_documents=documents,
        distinct_official_documents=official_documents,
        dedicated_page_available=dedicated,
        confirmed_entities=confirmed_entities,
        confirmed_relations=confirmed_relations,
    )
    return CoverageEvidenceLayer(
        direct_evidence_chunks=direct,
        substantial_evidence_chunks=substantial,
        mention_only_chunks=mentions,
        distinct_documents=documents,
        distinct_official_documents=official_documents,
        dedicated_page_available=dedicated,
        confirmed_entities=confirmed_entities,
        confirmed_relations=confirmed_relations,
        coverage_status=status,  # type: ignore[arg-type]
        coverage_reason=_coverage_reason(
            status,
            direct=direct,
            substantial=substantial,
            mentions=mentions,
            documents=documents,
            official_documents=official_documents,
            dedicated=dedicated,
            confirmed=confirmed_entities + confirmed_relations,
        ),
        evidence_urls=evidence_urls,
    )


def build_coverage(paths: PipelinePaths | None = None) -> dict[str, Any]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    previous = read_json(paths.coverage_json, {"topics": []})
    previous_statuses = {
        str(row.get("topic_name", "")): str(row.get("coverage_status", ""))
        for row in previous.get("topics", [])
        if isinstance(row, dict)
    }
    calibration_report = (
        paths.coverage_markdown.parent / "coverage_calibration_report.md"
    )
    baseline_statuses = _calibration_baseline(
        previous,
        calibration_report,
        previous_statuses,
    )
    documents = [
        row
        for row in _validated_rows(paths.cleaned_documents, CleanedDocument)
        if row.quality_status == "accepted"
    ]
    manual = accepted_manual_records(paths)
    chunks = _validated_rows(paths.chunks, RagChunk)
    entities = [
        row
        for row in _validated_rows(paths.entities, LoreEntity)
        if row.review_status == "confirmed"
    ]
    confirmed_relations = [
        row
        for row in _validated_rows(paths.relations_confirmed, LoreRelation)
        if row.review_status == "confirmed"
    ]
    bh3text_documents = {
        row.document_id: row
        for row in _validated_rows(paths.bh3text_documents, BH3TextDocument)
    }
    bh3text_chunks = _validated_rows(paths.bh3text_chunks, BH3TextChunk)
    transcript_rag_chunks: list[RagChunk] = []
    for chunk in bh3text_chunks:
        document = bh3text_documents.get(chunk.document_id)
        if document is None:
            continue
        transcript_rag_chunks.append(
            RagChunk.model_validate(
                {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "metadata": {
                        "title": chunk.title,
                        "source_url": chunk.source_url,
                        "source_type": chunk.source_type,
                        "source_tier": chunk.source_tier,
                        "entity_names": [
                            *chunk.character_names,
                            *chunk.topic_names,
                        ],
                        "retrieved_at": document.retrieved_at,
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.chunk_id,
                    },
                }
            )
        )
    manual_topics_by_document: dict[str, set[str]] = {}
    for record in manual:
        document_id = next(
            (
                chunk.metadata.document_id
                for chunk in chunks
                if chunk.metadata.source_url == f"manual-official://{record.record_id}"
            ),
            "",
        )
        if not document_id:
            continue
        explicit = set(record.character_names)
        explicit.update(
            topic_name
            for _, topic_name, _ in TOPICS
            if _title_centered(record.title, topic_name)
        )
        manual_topics_by_document[document_id] = explicit

    records: list[CoverageRecord] = []
    for topic_id, topic_name, topic_type in TOPICS:
        classified: list[tuple[RagChunk, EvidenceAssessment]] = []
        for chunk in chunks:
            assessment = classify_chunk_evidence(
                chunk,
                topic_name,
                manual_direct=(
                    topic_name
                    in manual_topics_by_document.get(chunk.metadata.document_id, set())
                ),
            )
            if assessment is not None:
                classified.append((chunk, assessment))
        direct = [
            chunk for chunk, result in classified if result.kind == "direct_evidence"
        ]
        substantial = [
            chunk
            for chunk, result in classified
            if result.kind == "substantial_evidence"
        ]
        mentions = [
            chunk for chunk, result in classified if result.kind == "mention_only"
        ]
        evidence_chunks = [*direct, *substantial]
        distinct_documents = {
            chunk.metadata.document_id for chunk in evidence_chunks
        }
        official_documents = {
            chunk.metadata.document_id
            for chunk in evidence_chunks
            if chunk.metadata.source_tier == "A"
            and chunk.metadata.source_type != "official_game_manual"
        }
        manual_documents = {
            chunk.metadata.document_id
            for chunk in evidence_chunks
            if chunk.metadata.source_type == "official_game_manual"
        }
        dedicated = any(
            chunk.metadata.source_tier == "A"
            and _title_centered(chunk.metadata.title, topic_name)
            for chunk in direct
        )
        confirmed_entity_matches = [
            entity
            for entity in entities
            if entity.name == topic_name or entity.name in _aliases(topic_name)
        ]
        relation_matches = [
            relation
            for relation in confirmed_relations
            if topic_name in {relation.source_entity, relation.target_entity}
            or relation.source_entity in _aliases(topic_name)
            or relation.target_entity in _aliases(topic_name)
        ]
        status = calculate_coverage_status(
            direct_evidence_chunks=len(direct),
            substantial_evidence_chunks=len(substantial),
            distinct_documents=len(distinct_documents),
            distinct_official_documents=len(official_documents),
            dedicated_page_available=dedicated,
            confirmed_entities=len(confirmed_entity_matches),
            confirmed_relations=len(relation_matches),
        )
        confirmed_total = len(confirmed_entity_matches) + len(relation_matches)
        transcript_classified = [
            (chunk, assessment)
            for chunk in transcript_rag_chunks
            if (
                assessment := classify_chunk_evidence(chunk, topic_name)
            ) is not None
        ]
        transcript_direct = [
            chunk
            for chunk, result in transcript_classified
            if result.kind == "direct_evidence"
        ]
        transcript_substantial = [
            chunk
            for chunk, result in transcript_classified
            if result.kind == "substantial_evidence"
        ]
        transcript_mentions = [
            chunk
            for chunk, result in transcript_classified
            if result.kind == "mention_only"
        ]
        transcript_evidence = [*transcript_direct, *transcript_substantial]
        transcript_documents = {
            chunk.metadata.document_id for chunk in transcript_evidence
        }
        official_layer = _evidence_layer(
            direct=len(direct),
            substantial=len(substantial),
            mentions=len(mentions),
            documents=len(distinct_documents),
            official_documents=len(official_documents),
            dedicated=dedicated,
            confirmed_entities=len(confirmed_entity_matches),
            confirmed_relations=len(relation_matches),
            evidence_urls=sorted(
                {chunk.metadata.source_url for chunk in evidence_chunks}
            ),
        )
        transcript_layer = _evidence_layer(
            direct=len(transcript_direct),
            substantial=len(transcript_substantial),
            mentions=len(transcript_mentions),
            documents=len(transcript_documents),
            official_documents=0,
            dedicated=False,
            confirmed_entities=0,
            confirmed_relations=0,
            evidence_urls=sorted(
                {chunk.metadata.source_url for chunk in transcript_evidence}
            ),
        )
        combined_layer = _evidence_layer(
            direct=len(direct) + len(transcript_direct),
            substantial=len(substantial) + len(transcript_substantial),
            mentions=len(mentions) + len(transcript_mentions),
            documents=len(distinct_documents | transcript_documents),
            official_documents=len(official_documents),
            dedicated=dedicated,
            confirmed_entities=len(confirmed_entity_matches),
            confirmed_relations=len(relation_matches),
            evidence_urls=sorted(
                {
                    *(chunk.metadata.source_url for chunk in evidence_chunks),
                    *(chunk.metadata.source_url for chunk in transcript_evidence),
                }
            ),
        )
        records.append(
            CoverageRecord(
                topic_id=topic_id,
                topic_name=topic_name,
                topic_type=topic_type,  # type: ignore[arg-type]
                official_documents=len(official_documents),
                manual_official_documents=len(manual_documents),
                accepted_chunks=len(evidence_chunks),
                direct_evidence_chunks=len(direct),
                substantial_evidence_chunks=len(substantial),
                mention_only_chunks=len(mentions),
                distinct_documents=len(distinct_documents),
                distinct_official_documents=len(official_documents),
                dedicated_page_available=dedicated,
                confirmed_entities=len(confirmed_entity_matches),
                confirmed_relations=len(relation_matches),
                coverage_status=status,  # type: ignore[arg-type]
                coverage_reason=_coverage_reason(
                    status,
                    direct=len(direct),
                    substantial=len(substantial),
                    mentions=len(mentions),
                    documents=len(distinct_documents),
                    official_documents=len(official_documents),
                    dedicated=dedicated,
                    confirmed=confirmed_total,
                ),
                evidence_urls=sorted(
                    {chunk.metadata.source_url for chunk in evidence_chunks}
                ),
                potential_video_sources=_potential_video_sources(paths, topic_name),
                missing_information=_missing_information(
                    direct=len(direct),
                    substantial=len(substantial),
                    documents=len(distinct_documents),
                    dedicated=dedicated,
                    confirmed=confirmed_total,
                    manual_documents=len(manual_documents),
                ),
                recommended_source_action=_recommended_action(
                    topic_name, topic_type, status
                ),
                official_coverage=official_layer,
                bh3text_transcript_coverage=transcript_layer,
                combined_coverage=combined_layer,
            )
        )

    write_json(
        paths.coverage_json,
        {
            "generated_at": utc_now(),
            "calibration_version": 2,
            "evidence_policy": (
                "mention_only does not raise coverage; distinct documents are "
                "deduplicated by document_id; unverified video metadata is potential only"
            ),
            "calibration_baseline_statuses": baseline_statuses,
            "topics": [record.model_dump(mode="json") for record in records],
        },
    )
    lines = [
        "# 设定主题覆盖矩阵（校准后，分层显示）",
        "",
        "> D=direct evidence，S=substantial evidence，M=mention only。官方、BH3Text转录与组合覆盖分别计算；BH3Text不增加官方文档或confirmed关系。",
        "",
        "| 主题 | 官方 D/S/M·文档·状态 | BH3Text D/S/M·文档·状态 | 组合 D/S/M·文档·状态 | 独立官方文档 | confirmed实体/关系 | 官方证据URL | BH3Text证据URL | 潜在视频 |",
        "|---|---|---|---|---:|---|---|---|---|",
    ]
    for record in records:
        official = record.official_coverage
        transcript = record.bh3text_transcript_coverage
        combined = record.combined_coverage
        urls = "<br>".join(official.evidence_urls) or "-"
        transcript_urls = "<br>".join(transcript.evidence_urls) or "-"
        videos = "、".join(
            item.video_id for item in record.potential_video_sources
        ) or "-"
        lines.append(
            f"| {record.topic_name} | "
            f"{official.direct_evidence_chunks}/{official.substantial_evidence_chunks}/"
            f"{official.mention_only_chunks} · {official.distinct_documents} · "
            f"{official.coverage_status} | "
            f"{transcript.direct_evidence_chunks}/{transcript.substantial_evidence_chunks}/"
            f"{transcript.mention_only_chunks} · {transcript.distinct_documents} · "
            f"{transcript.coverage_status} | "
            f"{combined.direct_evidence_chunks}/{combined.substantial_evidence_chunks}/"
            f"{combined.mention_only_chunks} · {combined.distinct_documents} · "
            f"{combined.coverage_status} | {official.distinct_official_documents} | "
            f"{record.confirmed_entities}/{record.confirmed_relations} | "
            f"{urls} | {transcript_urls} | {videos} |"
        )
    paths.coverage_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_calibration_report(
        calibration_report,
        records,
        baseline_statuses,
    )

    by_name = {record.topic_name: record for record in records}
    flame_chasers = (
        "爱莉希雅",
        "凯文",
        "阿波尼亚",
        "伊甸",
        "维尔薇",
        "千劫",
        "苏",
        "樱",
        "科斯魔",
        "梅比乌斯",
        "格蕾修",
        "华",
        "帕朵菲莉丝",
    )
    metrics = {
        "elysia_usable": by_name["爱莉希雅"].coverage_status in {"usable", "strong"},
        "thirteen_usable": by_name["逐火十三英桀"].coverage_status in {"usable", "strong"},
        "realm_usable": by_name["往世乐土"].coverage_status in {"usable", "strong"},
        "covered_flame_chasers": sum(
            by_name[name].coverage_status != "missing" for name in flame_chasers
        ),
        "accepted_official_documents": len(documents),
        "accepted_manual_documents": len(manual),
        "accepted_chunks": len(chunks),
        "missing_topics": sum(record.coverage_status == "missing" for record in records),
        "thin_topics": sum(record.coverage_status == "thin" for record in records),
        "usable_topics": sum(record.coverage_status == "usable" for record in records),
        "strong_topics": sum(record.coverage_status == "strong" for record in records),
        "bh3text_documents": len(bh3text_documents),
        "bh3text_chunks": len(bh3text_chunks),
        "bh3text_usable_topics": sum(
            record.bh3text_transcript_coverage.coverage_status in {"usable", "strong"}
            for record in records
        ),
        "combined_usable_topics": sum(
            record.combined_coverage.coverage_status in {"usable", "strong"}
            for record in records
        ),
    }
    metrics["true_usable_topics"] = metrics["usable_topics"] + metrics["strong_topics"]
    minimum_met = (
        metrics["elysia_usable"]
        and metrics["thirteen_usable"]
        and metrics["realm_usable"]
        and metrics["covered_flame_chasers"] >= 8
        and metrics["accepted_official_documents"] >= 10
        and metrics["accepted_chunks"] >= 30
    )
    metrics["minimum_target_met"] = minimum_met
    if not minimum_met:
        _write_gap_report(paths, records, metrics)
    build_review_workbench(paths)
    return metrics
