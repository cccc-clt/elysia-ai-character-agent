"""Evidence-bound rule and optional LLM relation extraction."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from data_pipeline.config import PipelinePaths
from data_pipeline.normalizer import ENTITY_CATALOG
from data_pipeline.schemas import CleanedDocument, LoreRelation, PageDocument, RelationType
from data_pipeline.utils import read_jsonl, stable_id, write_jsonl


RELATION_PROMPT_ID = "elysia-official-lore-relations-v1"
RELATION_SYSTEM_PROMPT = f"""Prompt-ID: {RELATION_PROMPT_ID}
你是官方设定文本的关系证据抽取器。只能使用输入文本，不得使用模型记忆或常识补充。
每条关系必须由输入中的一段短原文直接支持，evidence 必须逐字出现在输入正文中。
无法确认时不输出。不得根据同页出现或一般常识推断关系。
只允许 MEMBER_OF、ALLY_OF、ENEMY_OF、KNOWS、CREATED_BY、RELATED_TO、ALIAS_OF、
APPEARS_IN、PARTICIPATED_IN。区分前文明/现文明、本征世界/世界泡和不同身份形态。
所有结果默认为 pending。输出 JSON 对象，顶层字段为 relations 数组。
每项字段：source_entity、relation、target_entity、time_scope、universe、evidence、confidence。
"""


class RelationLLM(Protocol):
    def chat_json(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        ...


class LLMRelationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_entity: str = Field(min_length=1)
    relation: RelationType
    target_entity: str = Field(min_length=1)
    time_scope: str = ""
    universe: str = ""
    evidence: str = Field(min_length=2, max_length=300)
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)


def _sentences(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[。！？!?；;])|\n+", text)
        if 2 <= len(item.strip()) <= 300
    ]


def _context_fields(evidence: str) -> tuple[str, str]:
    time_scope = ""
    if "前文明" in evidence:
        time_scope = "前文明"
    elif "现文明" in evidence:
        time_scope = "现文明"
    universe = ""
    if "世界泡" in evidence:
        universe = "世界泡"
    elif "本征世界" in evidence:
        universe = "本征世界"
    return time_scope, universe


def _relation(
    source: str,
    relation: RelationType,
    target: str,
    evidence: str,
    source_url: str,
    confidence: float,
    *,
    time_scope: str = "",
    universe: str = "",
) -> LoreRelation:
    relation_id = stable_id(
        "rel", f"{source}|{relation}|{target}|{evidence}|{source_url}"
    )
    return LoreRelation(
        relation_id=relation_id,
        source_entity=source,
        relation=relation,
        target_entity=target,
        time_scope=time_scope,
        universe=universe,
        evidence=evidence,
        source_url=source_url,
        confidence=confidence,
        review_status="pending",
    )


def extract_rule_relations(document: PageDocument) -> list[LoreRelation]:
    relations: list[LoreRelation] = []
    faction_names = {
        name for name, (_, entity_type) in ENTITY_CATALOG.items() if entity_type == "faction"
    }
    character_names = {
        name for name, (_, entity_type) in ENTITY_CATALOG.items() if entity_type == "character"
    }
    event_names = {
        name for name, (_, entity_type) in ENTITY_CATALOG.items() if entity_type == "event"
    }
    for evidence in _sentences(document.content):
        time_scope, universe = _context_fields(evidence)
        for source in character_names:
            if source not in evidence:
                continue
            alias_match = re.search(
                rf"{re.escape(source)}.{{0,12}}(?:又名|亦称)"
                r"(?P<alias>真我·人之律者|粉色妖精小姐♪?)",
                evidence,
            )
            if alias_match:
                relations.append(
                    _relation(
                        source,
                        "ALIAS_OF",
                        alias_match.group("alias"),
                        evidence,
                        document.canonical_url,
                        0.84,
                        time_scope=time_scope,
                        universe=universe,
                    )
                )
        names = [name for name in ENTITY_CATALOG if name in evidence]
        if len(names) < 2:
            continue
        for source in names:
            for target in names:
                if source == target:
                    continue
                escaped_source = re.escape(source)
                escaped_target = re.escape(target)
                if target in faction_names and (
                    re.search(
                        rf"{escaped_source}.{{0,24}}(?:是|为|属于|隶属|加入|位列|身为).{{0,20}}{escaped_target}",
                        evidence,
                    )
                    or re.search(
                        rf"{escaped_target}.{{0,30}}(?:成员|包括|之一|第.{{0,4}}位).{{0,30}}{escaped_source}",
                        evidence,
                    )
                    or (
                        source == "爱莉希雅"
                        and target == "逐火十三英桀"
                        and re.search(r"英桀.{0,12}第.{0,4}位|第.{0,4}位.{0,12}英桀", evidence)
                    )
                ):
                    relations.append(
                        _relation(
                            source,
                            "MEMBER_OF",
                            target,
                            evidence,
                            document.canonical_url,
                            0.82,
                            time_scope=time_scope,
                            universe=universe,
                        )
                    )
                if source in character_names and target in faction_names and re.search(
                    rf"{escaped_source}.{{0,20}}担任.{{0,20}}{escaped_target}",
                    evidence,
                ):
                    relations.append(
                        _relation(
                            source,
                            "HOLDS_ROLE_IN",
                            target,
                            evidence,
                            document.canonical_url,
                            0.76,
                            time_scope=time_scope,
                            universe=universe,
                        )
                    )
                if source in character_names and target in faction_names and re.search(
                    rf"{escaped_source}.{{0,20}}(?:创建|建立|创立).{{0,20}}{escaped_target}",
                    evidence,
                ):
                    relations.append(
                        _relation(
                            target,
                            "CREATED_BY",
                            source,
                            evidence,
                            document.canonical_url,
                            0.8,
                            time_scope=time_scope,
                            universe=universe,
                        )
                    )
                if source in character_names and target in character_names:
                    pair_pattern = rf"{escaped_source}.{{0,40}}{escaped_target}|{escaped_target}.{{0,40}}{escaped_source}"
                    if re.search(pair_pattern, evidence) and re.search(r"盟友|伙伴|朋友|并肩", evidence):
                        relations.append(
                            _relation(source, "ALLY_OF", target, evidence, document.canonical_url, 0.72, time_scope=time_scope, universe=universe)
                        )
                    elif re.search(pair_pattern, evidence) and re.search(r"敌人|敌对|对抗|交战", evidence):
                        relations.append(
                            _relation(source, "ENEMY_OF", target, evidence, document.canonical_url, 0.72, time_scope=time_scope, universe=universe)
                        )
                    elif re.search(pair_pattern, evidence) and re.search(r"相识|认识|结识", evidence):
                        relations.append(
                            _relation(source, "KNOWS", target, evidence, document.canonical_url, 0.68, time_scope=time_scope, universe=universe)
                        )
                    if re.search(
                        rf"{escaped_source}.{{0,12}}是{escaped_target}的(?:妹妹|姐姐)",
                        evidence,
                    ):
                        relations.append(
                            _relation(
                                source,
                                "SIBLING_OF",
                                target,
                                evidence,
                                document.canonical_url,
                                0.82,
                                time_scope=time_scope,
                                universe=universe,
                            )
                        )
                    if re.search(
                        rf"{escaped_source}.{{0,12}}是{escaped_target}的(?:同伴|伙伴)",
                        evidence,
                    ):
                        relations.append(
                            _relation(
                                source,
                                "COMPANION_OF",
                                target,
                                evidence,
                                document.canonical_url,
                                0.78,
                                time_scope=time_scope,
                                universe=universe,
                            )
                        )
                    if re.search(
                        rf"{escaped_source}.{{0,12}}是{escaped_target}的领导者",
                        evidence,
                    ):
                        relations.append(
                            _relation(
                                source,
                                "LEADS",
                                target,
                                evidence,
                                document.canonical_url,
                                0.8,
                                time_scope=time_scope,
                                universe=universe,
                            )
                        )
                    if re.search(
                        rf"{escaped_source}.{{0,12}}(?:又名|亦称){escaped_target}",
                        evidence,
                    ):
                        relations.append(
                            _relation(
                                source,
                                "ALIAS_OF",
                                target,
                                evidence,
                                document.canonical_url,
                                0.84,
                                time_scope=time_scope,
                                universe=universe,
                            )
                        )
                if source in character_names and target in event_names and re.search(
                    rf"{escaped_source}.{{0,30}}(?:参与|参加|经历|执行).{{0,30}}{escaped_target}",
                    evidence,
                ):
                    relations.append(
                        _relation(
                            source,
                            "PARTICIPATED_IN",
                            target,
                            evidence,
                            document.canonical_url,
                            0.76,
                            time_scope=time_scope,
                            universe=universe,
                        )
                    )
                if re.search(
                    rf"{escaped_source}.{{0,30}}(?:相关|有关|联系).{{0,30}}{escaped_target}|{escaped_target}.{{0,30}}(?:相关|有关|联系).{{0,30}}{escaped_source}",
                    evidence,
                ):
                    relations.append(
                        _relation(source, "RELATED_TO", target, evidence, document.canonical_url, 0.65, time_scope=time_scope, universe=universe)
                    )
    unique = {relation.relation_id: relation for relation in relations}
    return list(unique.values())


def extract_llm_relations(
    document: PageDocument,
    llm: RelationLLM,
    model: str | None = None,
) -> list[LoreRelation]:
    request = json.dumps(
        {
            "title": document.title,
            "source_url": document.canonical_url,
            "content": document.content,
        },
        ensure_ascii=False,
    )
    raw = llm.chat_json(RELATION_SYSTEM_PROMPT, request, model=model)
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("relations", []), list):
        raise ValueError("LLM response must contain a relations array")
    output: list[LoreRelation] = []
    for candidate in payload.get("relations", []):
        try:
            item = LLMRelationItem.model_validate(candidate)
        except ValueError:
            continue
        if item.evidence not in document.content:
            continue
        if item.source_entity not in item.evidence or item.target_entity not in item.evidence:
            continue
        output.append(
            _relation(
                item.source_entity,
                item.relation,
                item.target_entity,
                item.evidence,
                document.canonical_url,
                item.confidence,
                time_scope=item.time_scope,
                universe=item.universe,
            )
        )
    return output


def extract_relations(
    paths: PipelinePaths | None = None,
    *,
    use_llm: bool = False,
    llm: RelationLLM | None = None,
    model: str | None = None,
) -> dict[str, Any]:
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
    if use_llm and llm is None:
        from src.config import get_config
        from src.llm_client import LLMClient

        config = get_config()
        llm = LLMClient(config.llm)
        if not llm.has_api_key:
            raise ValueError("API_KEY is required only when --use-llm is selected")
        model = model or config.llm.summary_model

    relations: dict[str, LoreRelation] = {}
    llm_errors = 0
    for document in documents:
        for relation in extract_rule_relations(document):
            relations[relation.relation_id] = relation
        if use_llm and llm is not None:
            try:
                for relation in extract_llm_relations(document, llm, model=model):
                    relations[relation.relation_id] = relation
            except (ValueError, json.JSONDecodeError):
                llm_errors += 1
                continue
    write_jsonl(
        paths.relations_pending,
        [relation.model_dump(mode="json") for relation in relations.values()],
    )
    return {
        "cleaned_documents": len(all_documents),
        "accepted_documents": len(documents),
        "pending_relations": len(relations),
        "llm_enabled": use_llm,
        "llm_document_errors": llm_errors,
    }
