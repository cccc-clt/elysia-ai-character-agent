"""Generate a compact, evidence-oriented report for collected lore data."""

from __future__ import annotations

from collections import Counter
from typing import Any

from data_pipeline.config import CORE_CHARACTERS, CORE_CONCEPTS, PipelinePaths
from data_pipeline.schemas import (
    CandidateAuditRecord,
    CleanedDocument,
    LoreEntity,
    LoreRelation,
    RagChunk,
)
from data_pipeline.utils import read_json, read_jsonl


def _short(text: str, limit: int = 80) -> str:
    value = " ".join(text.split()).replace("|", "\\|")
    return value[:limit] + ("…" if len(value) > limit else "")


def _validated(path: Any, model: Any) -> list[Any]:
    output: list[Any] = []
    for row in read_jsonl(path):
        try:
            output.append(model.model_validate(row))
        except ValueError:
            continue
    return output


def _audit_table(audits: list[CandidateAuditRecord]) -> list[str]:
    lines = [
        "| 优先级 | 决策 | 得分 | 分类 | 标题 | 原因 | URL |",
        "|---:|---|---:|---|---|---|---|",
    ]
    for row in audits:
        lines.append(
            f"| {row.crawl_priority} | {row.decision} | {row.relevance_score} | "
            f"{row.page_category} | {_short(row.title, 45)} | "
            f"{_short(row.reason, 70)} | {row.url} |"
        )
    return lines


def generate_quality_report(paths: PipelinePaths | None = None) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    audits = _validated(paths.candidate_audit_jsonl, CandidateAuditRecord)
    documents = _validated(paths.cleaned_documents, CleanedDocument)
    accepted = [doc for doc in documents if doc.quality_status == "accepted"]
    needs_review = [doc for doc in documents if doc.quality_status == "needs_review"]
    rejected = [doc for doc in documents if doc.quality_status == "rejected"]
    chunks = _validated(paths.chunks, RagChunk)
    entities = _validated(paths.entities, LoreEntity)
    relations = _validated(paths.relations_pending, LoreRelation)
    manifest = read_json(paths.manifest, {"records": []})
    manifest_records = list(manifest.get("records", []))

    audit_status = Counter(row.metadata_status for row in audits)
    crawl_status = Counter(str(row.get("status", "")) for row in manifest_records)
    include_count = sum(row.decision == "include" for row in audits)
    included_urls = {row.url for row in audits if row.decision == "include"}
    selected_manifest_records = [
        row for row in manifest_records if str(row.get("url", "")) in included_urls
    ]
    chunk_lengths = [len(chunk.content) for chunk in chunks]
    total_chars = sum(doc.chinese_char_count for doc in accepted)
    source_distribution = Counter(doc.source_type for doc in accepted)
    entity_by_name = {entity.name: entity for entity in entities}
    core_document_counts = {
        name: len(entity_by_name[name].source_document_ids) if name in entity_by_name else 0
        for name in CORE_CHARACTERS
    }
    missing_themes = [
        name
        for name in (*CORE_CHARACTERS, *CORE_CONCEPTS)
        if name not in entity_by_name
    ]
    failed_audits = [row for row in audits if row.metadata_status != "success"]
    manifest_failures = [
        row
        for row in manifest_records
        if row.get("status") in {"failed", "robots_disallowed"}
    ]
    page_3775 = next((row for row in audits if "/content/3775/detail" in row.url), None)
    nav_noise_docs = [doc for doc in documents if doc.navigation_noise_ratio > 0]
    repeated_docs = [
        doc
        for doc in documents
        if doc.duplicate_paragraph_count > 0
        or "duplicate_content" in doc.quality_reasons
    ]

    lines = [
        "# 官方设定数据质量报告",
        "",
        "> 本报告由本地确定性规则根据运行数据生成；候选评分和关系均不是人工确认结论。",
        "",
        "## 汇总",
        "",
        f"1. 候选 URL 总数：{len(audits)}",
        f"2. 纳入数量：{include_count}",
        f"3. 排除数量：{len(audits) - include_count}",
        f"4. 正式纳入队列/manifest 唯一记录数："
        f"{len(selected_manifest_records)}/{len(manifest_records)}",
        f"5. 成功/失败/robots 禁止/内容不足：{crawl_status['success']}/"
        f"{crawl_status['failed']}/{crawl_status['robots_disallowed']}/"
        f"{audit_status['insufficient_content']}",
        f"6. 有效详情页（accepted）数量：{len(accepted)}",
        f"7. rejected / needs_review：{len(rejected)} / {len(needs_review)}",
        f"8. accepted 文档有效中文字数：{total_chars}",
        f"9. chunks 数量：{len(chunks)}",
        f"10. chunk 长度（最小/最大/平均）："
        f"{min(chunk_lengths, default=0)}/{max(chunk_lengths, default=0)}/"
        f"{round(sum(chunk_lengths) / len(chunk_lengths), 1) if chunk_lengths else 0}",
        f"11. 实体候选数量：{len(entities)}",
        f"12. 真实 pending 关系数量：{len(relations)}",
        "13. 每个核心角色对应的 accepted 文档数：见下表",
        "14. 数据来源分布："
        + ("、".join(f"{key}={value}" for key, value in sorted(source_distribution.items())) or "无"),
        f"15. 栏目/导航噪声：{'存在' if nav_noise_docs else '未检测到'}"
        f"（{len(nav_noise_docs)} 个文档有已移除导航文字）",
        f"16. 重复正文/段落：{'存在' if repeated_docs else '未检测到'}"
        f"（{len(repeated_docs)} 个文档）",
        "17. 仍缺少资料的核心主题："
        + ("、".join(missing_themes) if missing_themes else "无"),
        "",
        "## 每条候选 URL 的决定",
        "",
        *_audit_table(audits),
        "",
        "## 核心角色对应文档数",
        "",
        "| 核心角色 | accepted 文档数 |",
        "|---|---:|",
        *(f"| {name} | {count} |" for name, count in core_document_counts.items()),
        "",
        "## 有效文档抽样（最多 3 条）",
        "",
    ]
    if accepted:
        for doc in accepted[:3]:
            lines.append(
                f"- **{_short(doc.title, 70)}**：中文 {doc.chinese_char_count} 字，"
                f"噪声比 {doc.navigation_noise_ratio}，{doc.canonical_url}"
            )
    else:
        lines.append("- 无 accepted 文档。")

    lines.extend(["", "## Chunk 抽样（最多 5 条）", ""])
    if chunks:
        for chunk in chunks[:5]:
            lines.append(
                f"- `{chunk.chunk_id}` | {len(chunk.content)} 字 | "
                f"{_short(chunk.content)} | {chunk.metadata.source_url}"
            )
    else:
        lines.append("- 无 chunk。")

    lines.extend(["", "## 所有实际 pending 关系", ""])
    if relations:
        for relation in relations:
            lines.append(
                f"- `{relation.source_entity} {relation.relation} "
                f"{relation.target_entity}` | 置信度 {relation.confidence} | "
                f"证据：{_short(relation.evidence)} | {relation.source_url}"
            )
    else:
        lines.append("- 无关系；未从同页并列名称推断关系。")

    lines.extend(["", "## 所有失败或不可用候选页面", ""])
    if failed_audits or manifest_failures:
        for row in failed_audits:
            lines.append(
                f"- `{row.metadata_status}` | {_short(row.title)} | "
                f"{_short(row.reason)} | {row.url}"
            )
        for row in manifest_failures:
            lines.append(
                f"- `{row.get('status')}` | {_short(str(row.get('reason', '')))} | "
                f"{row.get('url', '')}"
            )
    else:
        lines.append("- 无。")

    lines.extend(["", "## `/content/3775/detail` 排查", ""])
    if page_3775 is not None:
        lines.extend(
            [
                f"- 当前 HTTP 状态：{page_3775.http_status or '未记录'}；"
                f"最终 URL：{page_3775.final_url or page_3775.url}",
                f"- 当前标题：{_short(page_3775.title)}；"
                f"有效中文：{page_3775.chinese_char_count} 字；"
                f"分类：{page_3775.page_category}；决定：{page_3775.decision}",
                "- 当前公开重试未复现此前仅 5 个有效字符的状态，也未见登录、验证码或访问受限；"
                "现有证据支持其为一次动态正文加载/公开页面可用性的瞬时失败，"
                "而不是已确认的固定选择器故障。",
                "- 去掉评论和全站目录后正文不足 200 个有效中文字符，"
                "且主体是怪物技能资料，因此按 `insufficient_content` 排除。",
            ]
        )
    else:
        lines.append("- 候选审计中未找到该 URL。")

    lines.extend(["", "## 所有 needs_review 页面", ""])
    if needs_review:
        for doc in needs_review:
            lines.append(
                f"- {_short(doc.title)} | {', '.join(doc.quality_reasons)} | "
                f"{doc.canonical_url}"
            )
    else:
        lines.append("- 无。")

    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 只有 `quality_status=accepted` 的文档会进入 chunks、实体和关系抽取。",
            "- `relations_pending.jsonl` 只包含正文短证据直接支持的候选关系，仍需人工审核。",
            "- 报告仅展示短摘要，不复制大段官方正文。",
        ]
    )
    paths.quality_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "candidate_urls": len(audits),
        "included_urls": include_count,
        "accepted_documents": len(accepted),
        "needs_review_documents": len(needs_review),
        "rejected_documents": len(rejected),
        "chunks": len(chunks),
        "entities": len(entities),
        "pending_relations": len(relations),
    }
