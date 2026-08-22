"""Human review tables for pending entities, relations, and alias suggestions."""

from __future__ import annotations

from data_pipeline.config import PipelinePaths
from data_pipeline.schemas import BH3TextPendingRelation, LoreEntity, LoreRelation
from data_pipeline.utils import read_jsonl


def _short(text: str, limit: int = 100) -> str:
    value = " ".join(text.split()).replace("|", "\\|")
    return value[:limit] + ("…" if len(value) > limit else "")


def build_review_workbench(paths: PipelinePaths | None = None) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    entities: list[LoreEntity] = []
    for row in read_jsonl(paths.entities):
        try:
            entities.append(LoreEntity.model_validate(row))
        except ValueError:
            continue
    relations: list[LoreRelation] = []
    for row in read_jsonl(paths.relations_pending):
        try:
            relations.append(LoreRelation.model_validate(row))
        except ValueError:
            continue
    transcript_relations: list[BH3TextPendingRelation] = []
    for row in read_jsonl(paths.bh3text_relations_pending):
        try:
            transcript_relations.append(BH3TextPendingRelation.model_validate(row))
        except ValueError:
            continue

    entity_lines = [
        "# 实体人工审核工作台",
        "",
        "> 本文件只提供建议，不会自动确认、拒绝或合并实体。",
        "",
        "| 实体名称 | 类型 | 别名 | 出现次数 | 来源页面 | 短证据 | 建议操作 | accept/reject/merge |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for entity in entities:
        source = "<br>".join(entity.source_urls[:3])
        evidence = _short(entity.evidence_snippets[0]) if entity.evidence_snippets else ""
        suggestion = "核对身份与证据后 accept 或 reject"
        if entity.name == "爱莉希雅":
            suggestion = "检查下方装甲/身份别名建议，禁止直接自动 merge"
        entity_lines.append(
            f"| {entity.name} | {entity.entity_type} | {'、'.join(entity.aliases)} | "
            f"{entity.mention_count} | {source} | {evidence} | {suggestion} | 待填写 |"
        )
    if not entities:
        entity_lines.append("| - | - | - | 0 | - | - | 无实体候选 | - |")
    entity_lines.extend(
        [
            "",
            "## 别名/身份合并建议（仅供人工判断）",
            "",
            "| 基础名称 | 候选名称 | 可能关系 | 必须人工确认的问题 | 自动执行 |",
            "|---|---|---|---|---|",
            "| 爱莉希雅 | 真我·人之律者 | 可能为同一角色的不同装甲或剧情身份 | "
            "是别名、装甲、律者身份还是应保留独立实体？ | 否 |",
            "| 爱莉希雅 | 粉色妖精小姐♪ | 可能为同一角色的装甲名称 | "
            "是否只作为装甲别名，是否涉及不同剧情阶段？ | 否 |",
            "",
            "身份、装甲、记忆体和不同剧情阶段在人工确认前不得合并。",
        ]
    )
    paths.entities_review.write_text(
        "\n".join(entity_lines) + "\n", encoding="utf-8"
    )

    relation_lines = [
        "# 关系人工审核工作台",
        "",
        "> 同页共现不构成关系。所有候选仍为 pending，必须打开来源核对原文。",
        "",
        "| 来源实体 | 关系 | 目标实体 | time_scope | universe | confidence | 短证据 | 来源 | accept/reject |",
        "|---|---|---|---|---|---:|---|---|---|",
    ]
    for relation in relations:
        relation_lines.append(
            f"| {relation.source_entity} | {relation.relation} | "
            f"{relation.target_entity} | {relation.time_scope} | "
            f"{relation.universe} | {relation.confidence} | "
            f"{_short(relation.evidence)} | {relation.source_url} | 待填写 |"
        )
    if not relations:
        relation_lines.append("| - | - | - | - | - | 0 | 无明确关系句 | - | - |")
    relation_lines.extend(
        [
            "",
            "## BH3Text待审核语义关系",
            "",
            "> 这些候选来自非官方托管剧情转录，必须由官方资料佐证；不得写入confirmed。",
            "",
            "| 来源实体 | 关系 | 目标实体 | 章节/场景 | confidence | 短证据 | 来源 | review |",
            "|---|---|---|---|---:|---|---|---|",
        ]
    )
    for relation in transcript_relations:
        relation_lines.append(
            f"| {relation.source_entity} | {relation.relation} | "
            f"{relation.target_entity} | {relation.chapter}/{relation.scene} | "
            f"{relation.confidence} | {_short(relation.evidence)} | "
            f"{relation.source_url} | pending，需官方佐证 |"
        )
    if not transcript_relations:
        relation_lines.append(
            "| - | - | - | - | 0 | 严格规则未生成候选（这是允许结果） | - | - |"
        )
    paths.relations_review.write_text(
        "\n".join(relation_lines) + "\n", encoding="utf-8"
    )
    pair_relations: dict[tuple[str, str], set[str]] = {}
    pair_sources: dict[tuple[str, str], set[str]] = {}
    combined = [
        (row.source_entity, row.relation, row.target_entity, row.source_url)
        for row in relations
    ] + [
        (row.source_entity, row.relation, row.target_entity, row.source_url)
        for row in transcript_relations
    ]
    for source, relation, target, source_url in combined:
        key = (source, target)
        pair_relations.setdefault(key, set()).add(str(relation))
        pair_sources.setdefault(key, set()).add(source_url)
    conflicts = [
        (pair, sorted(values), sorted(pair_sources[pair]))
        for pair, values in pair_relations.items()
        if len(values) > 1
    ]
    conflict_lines = [
        "# 关系候选冲突报告",
        "",
        "> 仅比较pending候选；证据边 `SPEAKS_TO/SPEAKS_ABOUT/APPEARS_WITH` 不视为语义关系，也不会出现在这里。",
        "",
        "| 来源实体 | 目标实体 | 冲突关系 | 来源URL | 人工结论 |",
        "|---|---|---|---|---|",
    ]
    for (source, target), relation_types, urls in conflicts:
        conflict_lines.append(
            f"| {source} | {target} | {'、'.join(relation_types)} | "
            f"{'<br>'.join(urls)} | 待填写 |"
        )
    if not conflicts:
        conflict_lines.append("| - | - | 无pending关系冲突 | - | - |")
    paths.relation_conflicts.write_text(
        "\n".join(conflict_lines) + "\n", encoding="utf-8"
    )
    return {
        "pending_entities": len(entities),
        "pending_relations": len(relations) + len(transcript_relations),
        "relation_conflicts": len(conflicts),
        "alias_merge_suggestions": 2,
    }
