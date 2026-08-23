from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from data_pipeline.candidate_audit import audit_candidates
from data_pipeline.bh3text import (
    BH3TextAccessError,
    build_bh3text,
    build_dialogue_evidence_edges,
    build_vector_readiness,
    chunk_bh3text_document,
    crawl_bh3text,
    discover_bh3text,
    extract_pending_semantic_relations,
    load_bh3text_collection_groups,
    parse_bh3text_dialogue,
    select_coverage_gap_candidates,
    select_verification_documents,
)
from data_pipeline.bh3helper import (
    build_story_navigation,
    discover_bh3helper,
    discover_public_scope_links,
    map_duplicate_sources,
    parse_bh3helper_page,
)
from data_pipeline.chunker import build_rag, split_text
from data_pipeline.config import CrawlSettings, PipelinePaths
from data_pipeline.coverage import (
    build_coverage,
    calculate_coverage_status,
    classify_chunk_evidence,
)
from data_pipeline.crawler import OfficialLoreCrawler
from data_pipeline.extractor import extract_html
from data_pipeline.lore_integrity import (
    build_lore_integrity_audit,
    normalize_bh3text_metadata,
)
from data_pipeline.manual_official import ManualRecordValidationError, load_manual_records
from data_pipeline.normalizer import normalize_documents
from data_pipeline.relevance import clean_content_for_url, clean_document_text, score_candidate
from data_pipeline.relation_extractor import (
    extract_relations,
    extract_llm_relations,
    extract_rule_relations,
)
from data_pipeline.review_workbench import build_review_workbench
from data_pipeline.schemas import (
    BH3TextCandidateAudit,
    BH3TextDocument,
    BH3TextVerificationRecord,
    BilibiliVideoMetadata,
    DialogueTurn,
    LoreRelation,
    OfficialComicMetadata,
    PageDocument,
    RagChunk,
)
from data_pipeline.source_registry import (
    discovery_sources,
    identify_source_tier,
    load_source_registry,
)
from data_pipeline.source_inventory import build_source_inventory
from data_pipeline.utils import (
    content_hash,
    is_allowed_url,
    normalize_url,
    read_jsonl,
    upsert_jsonl,
    write_json,
    write_jsonl,
)
from data_pipeline.video_sources import (
    build_video_review,
    clean_subtitle_cues,
    inspect_videos,
    normalize_bilibili_video_url,
    parse_public_video_html,
    parse_subtitle_text,
    process_video_subtitles,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _paths(tmp_path: Path) -> PipelinePaths:
    data = tmp_path / "data"
    paths = PipelinePaths(
        root=tmp_path,
        source_registry=data / "config" / "source_registry.yaml",
        seeds=data / "seeds" / "elysia_official_urls.txt",
        raw_documents=data / "raw" / "official_pages.jsonl",
        cleaned_documents=data / "cleaned" / "official_pages.jsonl",
        chunks=data / "chunks" / "elysia_lore_chunks.jsonl",
        markdown_dir=data / "chunks" / "elysia_lore_markdown",
        entities=data / "entities" / "entities_pending.jsonl",
        relations_pending=data / "relations" / "relations_pending.jsonl",
        relations_confirmed=data / "relations" / "relations_confirmed.jsonl",
        manifest=data / "manifests" / "crawl_manifest.json",
        candidate_audit_jsonl=data / "manifests" / "elysia_candidate_audit.jsonl",
        candidate_audit_markdown=data / "manifests" / "elysia_candidate_audit.md",
        quality_report=data / "manifests" / "data_quality_report.md",
        discovery_report=data / "manifests" / "discovery_report.json",
        comic_metadata=data / "manifests" / "official_comics.jsonl",
        character_profiles=data / "manifests" / "official_character_profiles.jsonl",
        coverage_json=data / "manifests" / "lore_coverage_matrix.json",
        coverage_markdown=data / "manifests" / "lore_coverage_matrix.md",
        manual_source_gap=data / "manifests" / "manual_source_gap.md",
        source_inventory=data / "manifests" / "source_inventory.json",
        deduplication_report=data / "manifests" / "deduplication_report.md",
        lore_integrity_audit=data / "manifests" / "lore_integrity_audit.json",
        lore_integrity_audit_markdown=data / "manifests" / "lore_integrity_audit.md",
        manual_templates_dir=data / "manual_official" / "templates",
        manual_inbox_dir=data / "manual_official" / "inbox",
        manual_accepted_dir=data / "manual_official" / "accepted",
        manual_pending_index=data / "manual_official" / "manual_pending.jsonl",
        manual_review=data / "review" / "manual_review.md",
        entities_review=data / "review" / "entities_review.md",
        relations_review=data / "review" / "relations_review.md",
        relation_conflicts=data / "review" / "relation_conflicts.md",
        bilibili_official_accounts=data / "config" / "bilibili_official_accounts.yaml",
        video_seed_file=data / "video_sources" / "bilibili_seeds.txt",
        video_metadata_dir=data / "video_sources" / "metadata",
        video_subtitles_raw_dir=data / "video_sources" / "subtitles_raw",
        video_subtitles_cleaned_dir=data / "video_sources" / "subtitles_cleaned",
        video_chunks=data / "video_sources" / "chunks" / "video_chunks.jsonl",
        video_manual_inbox_dir=data / "video_sources" / "manual_inbox",
        video_audit_jsonl=data / "video_sources" / "review" / "bilibili_source_audit.jsonl",
        video_audit_markdown=data / "video_sources" / "review" / "bilibili_source_audit.md",
        video_subtitle_review=data / "video_sources" / "review" / "subtitle_review.md",
        video_fact_review=data / "video_sources" / "review" / "video_fact_review.md",
        bh3text_candidate_audit_jsonl=data / "manifests" / "bh3text_candidate_audit.jsonl",
        bh3text_candidate_audit_markdown=data / "manifests" / "bh3text_candidate_audit.md",
        bh3text_collection_groups=data / "config" / "bh3text_collection_groups.yaml",
        bh3text_group_coverage_before=data / "manifests" / "bh3text_group_coverage_before.json",
        bh3text_group_coverage_after=data / "manifests" / "bh3text_group_coverage_after.json",
        bh3text_manifest=data / "manifests" / "bh3text_crawl_manifest.json",
        bh3text_raw_documents=data / "raw" / "bh3text_pages.jsonl",
        bh3text_documents=data / "cleaned" / "bh3text_dialogues.jsonl",
        bh3text_chunks=data / "chunks" / "bh3text_lore_chunks.jsonl",
        dialogue_evidence_edges=data / "relations" / "dialogue_evidence_edges.jsonl",
        bh3text_relations_pending=data / "relations" / "bh3text_relations_pending.jsonl",
        bh3text_transcript_verification=data / "review" / "bh3text_transcript_verification.md",
        bh3text_transcript_verification_jsonl=data / "review" / "bh3text_transcript_verification.jsonl",
        vector_readiness=data / "manifests" / "vector_readiness.json",
        story_guide_dir=data / "story_guide",
        bh3helper_navigation=data / "story_guide" / "bh3helper_navigation.jsonl",
        bh3helper_official_links=data / "story_guide" / "bh3helper_official_links.jsonl",
        bh3helper_archive_candidates=data / "story_guide" / "bh3helper_archive_candidates.jsonl",
        bh3helper_annotations=data / "story_guide" / "bh3helper_annotations.jsonl",
        bh3helper_duplicate_map=data / "story_guide" / "bh3helper_duplicate_map.jsonl",
        source_link_graph=data / "story_guide" / "source_link_graph.jsonl",
        story_navigation_chunks=data / "story_guide" / "story_navigation_chunks.jsonl",
        bh3helper_manifest=data / "manifests" / "bh3helper_discovery_report.json",
        log=data / "logs" / "data_pipeline.log",
    )
    paths.bh3text_collection_groups.parent.mkdir(parents=True, exist_ok=True)
    paths.bh3text_collection_groups.write_text(
        (FIXTURES.parent.parent / "data" / "config" / "bh3text_collection_groups.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return paths


def _document(content: str, url: str = "https://baike.mihoyo.com/bh3/wiki/content/123/detail") -> PageDocument:
    return PageDocument(
        document_id="doc_1234567890abcdef",
        title="本地测试文档",
        canonical_url=url,
        source_domain="baike.mihoyo.com",
        source_type="official_wiki",
        content=content,
        content_hash=content_hash(content),
        retrieved_at="2026-08-21T00:00:00+00:00",
    )


def _rag_chunk(
    content: str,
    *,
    title: str = "汇总资料",
    document_id: str = "doc_summary_001",
    chunk_id: str = "chunk_summary_001",
    source_url: str = "https://baike.mihoyo.com/bh3/wiki/content/123/detail",
    source_type: str = "official_wiki",
    source_tier: str = "A",
    entity_names: list[str] | None = None,
) -> RagChunk:
    return RagChunk.model_validate(
        {
            "chunk_id": chunk_id,
            "content": content,
            "metadata": {
                "title": title,
                "source_url": source_url,
                "source_type": source_type,
                "source_tier": source_tier,
                "entity_names": entity_names or [],
                "retrieved_at": "2026-08-21T00:00:00+00:00",
                "document_id": document_id,
                "chunk_id": chunk_id,
            },
        }
    )


def test_url_normalization_removes_tracking_and_keeps_route_parameters() -> None:
    result = normalize_url(
        "HTTPS://BAIKE.MIHOYO.COM//bh3/wiki/content/123/detail/"
        "?utm_source=x&bbs_presentation_style=no_header&z=2#part"
    )
    assert result == (
        "https://baike.mihoyo.com/bh3/wiki/content/123/detail"
        "?bbs_presentation_style=no_header&z=2"
    )
    assert "token" not in normalize_url(
        "https://baike.mihoyo.com/bh3/wiki/content/1/detail?token=secret&z=2"
    )


def test_domain_and_path_allowlist() -> None:
    settings = CrawlSettings()
    assert is_allowed_url(
        "https://baike.mihoyo.com/bh3/wiki/content/123/detail",
        settings.allowed_path_prefixes,
    )
    assert not is_allowed_url(
        "https://example.com/bh3/wiki/content/123/detail",
        settings.allowed_path_prefixes,
    )
    assert is_allowed_url(
        "https://comic.bh3.com/book",
        settings.allowed_path_prefixes,
    )
    assert not is_allowed_url(
        "https://comic.bh3.com/music",
        settings.allowed_path_prefixes,
    )


def test_blocked_path_is_rejected() -> None:
    settings = CrawlSettings()
    assert not is_allowed_url(
        "https://baike.mihoyo.com/bh3/wiki/content/user/123/detail",
        settings.allowed_path_prefixes,
    )


def test_allowlist_accepts_directory_root_without_prefix_collision() -> None:
    settings = CrawlSettings()
    assert is_allowed_url("https://www.bh3.com/news", settings.allowed_path_prefixes)
    assert not is_allowed_url(
        "https://www.bh3.com/newsletter/123", settings.allowed_path_prefixes
    )


def test_html_main_text_cleaning_and_link_discovery() -> None:
    html = (FIXTURES / "official_article.html").read_text(encoding="utf-8")
    page = extract_html(
        html, "https://baike.mihoyo.com/bh3/wiki/content/123/detail"
    )
    assert page.title == "爱莉希雅官方档案"
    assert "爱莉希雅是逐火十三英桀的一员" in page.content
    assert "玩家社区" not in page.content
    assert "window.secret" not in page.content
    assert not page.needs_dynamic_render
    assert any(link.label == "往世乐土" for link in page.links)


def test_normalize_deduplicates_identical_content_hashes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    content = "爱莉希雅角色设定与前文明档案测试正文。" * 30
    first = _document(content)
    second_data = first.model_dump(mode="json")
    second_data.update(
        {
            "document_id": "doc_fedcba0987654321",
            "canonical_url": "https://baike.mihoyo.com/bh3/wiki/content/456/detail",
        }
    )
    write_jsonl(paths.raw_documents, [first.model_dump(mode="json"), second_data])

    result = normalize_documents(paths)

    assert result["cleaned_documents"] == 2
    assert result["accepted_documents"] == 1
    assert result["rejected_documents"] == 1
    assert result["content_duplicates"] == 1
    assert len(read_jsonl(paths.cleaned_documents)) == 2


def test_normalize_keeps_discovery_index_out_of_rag(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    content = "爱莉希雅与第一阶段相关的本地合成栏目文字。" * 20
    index_document = _document(
        content,
        "https://baike.mihoyo.com/bh3/wiki/channel/map/17/59",
    )
    write_jsonl(paths.raw_documents, [index_document.model_dump(mode="json")])

    result = normalize_documents(paths)

    assert result["cleaned_documents"] == 1
    assert result["rejected_documents"] == 1
    assert build_rag(paths)["chunks"] == 0


class _FakeRenderer:
    def __init__(self, html: str) -> None:
        self.html = html
        self.calls = 0

    def render(self, url: str) -> str:
        self.calls += 1
        return self.html


def test_empty_static_page_triggers_dynamic_renderer(tmp_path: Path) -> None:
    loading = (FIXTURES / "loading.html").read_text(encoding="utf-8")
    rendered = (FIXTURES / "official_article.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=loading, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    renderer = _FakeRenderer(rendered)
    crawler = OfficialLoreCrawler(
        CrawlSettings(delay_seconds=0, max_retries=0),
        _paths(tmp_path),
        client=client,
        renderer=renderer,  # type: ignore[arg-type]
    )
    page, _, _ = crawler._fetch_and_extract(  # noqa: SLF001 - focused unit seam
        "https://baike.mihoyo.com/bh3/wiki/content/123/detail"
    )
    client.close()

    assert renderer.calls == 1
    assert not page.needs_dynamic_render
    assert "爱莉希雅" in page.content


def test_jsonl_schemas_validate_round_trip(tmp_path: Path) -> None:
    document = _document("用于 schema 验证的中文正文。" * 20)
    path = tmp_path / "documents.jsonl"
    write_jsonl(path, [document.model_dump(mode="json")])
    parsed = PageDocument.model_validate(read_jsonl(path)[0])
    assert parsed.document_id == document.document_id

    chunk_payload = {
        "chunk_id": "chunk_1234567890abcdef",
        "content": "有效正文",
        "metadata": {
            "title": "测试",
            "source_url": document.canonical_url,
            "source_type": document.source_type,
            "entity_names": ["爱莉希雅"],
            "era": [],
            "universe": [],
            "retrieved_at": "2026-08-21T00:00:00+00:00",
            "document_id": document.document_id,
            "chunk_id": "chunk_1234567890abcdef",
        },
    }
    assert RagChunk.model_validate(chunk_payload).metadata.entity_names == ["爱莉希雅"]


def test_sentence_aware_chunking_respects_configured_size() -> None:
    sentences = [f"这是第{index}条用于测试完整句子边界的合成说明，内容不会来自官方正文。" for index in range(80)]
    text = "".join(sentence + "。" for sentence in sentences)
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 900 for chunk in chunks)
    assert all(chunk.endswith("。") for chunk in chunks)
    assert all(len(chunk) >= 500 for chunk in chunks[:-1])


def test_relation_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LoreRelation(
            relation_id="rel_1234567890abcdef",
            source_entity="爱莉希雅",
            relation="MEMBER_OF",
            target_entity="逐火十三英桀",
            evidence="",
            source_url="https://baike.mihoyo.com/bh3/wiki/content/123/detail",
            confidence=0.8,
        )


class _FakeLLM:
    def chat_json(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        return json.dumps(
            {
                "relations": [
                    {
                        "source_entity": "爱莉希雅",
                        "relation": "MEMBER_OF",
                        "target_entity": "逐火十三英桀",
                        "evidence": "输入正文中不存在的证据",
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        )


def test_llm_relation_with_non_verbatim_evidence_is_rejected() -> None:
    document = _document("爱莉希雅的测试页面没有提供该关系。")
    assert extract_llm_relations(document, _FakeLLM()) == []


def test_rule_relation_is_pending_and_keeps_source() -> None:
    document = _document("爱莉希雅是逐火十三英桀的一员。")
    relations = extract_rule_relations(document)
    assert any(
        relation.source_entity == "爱莉希雅"
        and relation.relation == "MEMBER_OF"
        and relation.target_entity == "逐火十三英桀"
        and relation.review_status == "pending"
        and relation.source_url == document.canonical_url
        for relation in relations
    )


def test_identical_jsonl_upsert_does_not_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    row = {"document_id": "doc_stable", "content": "相同内容"}
    assert upsert_jsonl(path, row, "document_id") is True
    assert upsert_jsonl(path, row, "document_id") is False
    assert read_jsonl(path) == [row]


def test_resume_does_not_exceed_total_manifest_page_limit(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.seeds.parent.mkdir(parents=True, exist_ok=True)
    paths.seeds.write_text(
        "\n".join(
            [
                "https://baike.mihoyo.com/bh3/wiki/content/1/detail",
                "https://baike.mihoyo.com/bh3/wiki/content/2/detail",
                "https://baike.mihoyo.com/bh3/wiki/content/3/detail",
            ]
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", request=request
            )
        body = (
            f"<html><title>爱莉希雅 {request.url.path}</title><main>"
            + (f"爱莉希雅本地合成正文 {request.url.path}。" * 30)
            + "</main></html>"
        )
        return httpx.Response(200, text=body, request=request)

    settings = CrawlSettings(
        max_pages=2,
        delay_seconds=0,
        max_retries=0,
        render_dynamic=False,
    )
    first_client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    first = OfficialLoreCrawler(settings, paths, client=first_client)
    assert first.crawl()["success"] == 2
    first_client.close()

    second_client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    second = OfficialLoreCrawler(settings, paths, client=second_client)
    second.crawl()
    second_client.close()

    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert len(manifest["records"]) == 2
    assert len(read_jsonl(paths.raw_documents)) == 2


def test_candidate_relevance_scoring_is_explainable() -> None:
    result = score_candidate(
        title="爱莉希雅与逐火十三英桀角色档案",
        content="爱莉希雅与凯文的前文明角色设定。" * 30,
        url="https://baike.mihoyo.com/bh3/wiki/content/123/detail",
    )
    assert result.decision == "include"
    assert result.relevance_score == 32
    assert any("爱莉希雅 +10" in item for item in result.score_breakdown)
    assert any("核心组织/概念 +8" in item for item in result.score_breakdown)


def test_gameplay_guide_is_downgraded_and_excluded() -> None:
    result = score_candidate(
        title="凯文记忆战场配装攻略",
        content=(
            "凯文技能伤害类型、武器圣痕数值、阵容配装与特殊机制攻略。" * 30
        ),
        url="https://baike.mihoyo.com/bh3/wiki/content/999/detail",
    )
    assert result.page_category == "gameplay"
    assert result.decision == "exclude"
    assert any("-8" in item for item in result.score_breakdown)


def test_structured_monster_page_overrides_incidental_lore_markers() -> None:
    result = score_candidate(
        title="逐火十三英桀 爱莉希雅",
        content=(
            "怪物信息 怪物名称 爱莉希雅 技能 伤害类型 特殊机制。"
            "世界蛇档案中有一段背景故事。" * 25
        ),
        url="https://baike.mihoyo.com/bh3/wiki/content/1538/detail",
    )
    assert result.page_category == "gameplay"
    assert result.decision == "exclude"


def test_single_character_names_require_title_boundaries() -> None:
    result = score_candidate(
        title="华彩璀耀自选箱",
        content="材料描述、获取途径、消耗途径与活动补给说明。" * 30,
        url="https://baike.mihoyo.com/bh3/wiki/content/3847/detail",
    )
    assert "华" not in result.matched_keywords
    assert not any("核心角色 +6" in item for item in result.score_breakdown)
    assert result.decision == "exclude"


def test_wiki_feedback_tail_is_removed_from_cleaned_text() -> None:
    cleaned = clean_document_text(
        "米哈游官方社区\n爱莉希雅角色档案\n前文明角色设定正文。\n"
        "词条内容由圣芙蕾雅档案馆编辑团队原创，禁止转载\n"
        "建议与反馈\n全部评论\n数据加载中"
    )
    assert cleaned.content == "爱莉希雅角色档案\n前文明角色设定正文。"
    assert "全部评论" not in cleaned.content


def test_single_character_entity_does_not_match_common_word(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    document = _document(
        "爱莉希雅角色设定中的人性之华与才华横溢只是普通词语。" * 20
    )
    write_jsonl(paths.raw_documents, [document.model_dump(mode="json")])

    normalize_documents(paths)
    names = {row["name"] for row in read_jsonl(paths.entities)}

    assert "爱莉希雅" in names
    assert "华" not in names


def test_empty_or_short_body_is_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    short = _document("爱莉希雅角色档案。")
    write_jsonl(paths.raw_documents, [short.model_dump(mode="json")])

    result = normalize_documents(paths)
    row = read_jsonl(paths.cleaned_documents)[0]

    assert result["rejected_documents"] == 1
    assert row["quality_status"] == "rejected"
    assert "insufficient_chinese_content" in row["quality_reasons"]


def test_candidate_audit_marks_short_cleaned_body_insufficient(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    short = _document("绯樱召唤师怪物信息与技能。")
    write_jsonl(paths.raw_documents, [short.model_dump(mode="json")])
    write_json(
        paths.manifest,
        {
            "scope": "elysia",
            "discovered_urls": [short.canonical_url],
            "records": [],
        },
    )

    result = audit_candidates(
        paths,
        crawl_settings=CrawlSettings(
            delay_seconds=0,
            max_retries=0,
            render_dynamic=False,
        ),
    )
    audit = read_jsonl(paths.candidate_audit_jsonl)[0]

    assert result["network_inspections"] == 0
    assert result["metadata_insufficient"] == 1
    assert audit["metadata_status"] == "insufficient_content"
    assert audit["decision"] == "exclude"


def _candidate_audit_row(
    url: str,
    *,
    decision: str,
    priority: int,
) -> dict[str, object]:
    return {
        "url": url,
        "title": "爱莉希雅角色档案",
        "source_type": "official_wiki",
        "matched_keywords": ["爱莉希雅"],
        "relevance_score": 10 if decision == "include" else 0,
        "decision": decision,
        "reason": "本地审计测试",
        "crawl_priority": priority,
        "score_breakdown": [],
        "metadata_status": "success",
        "page_category": "lore",
        "chinese_char_count": 300,
        "summary_excerpt": "",
        "http_status": 200,
        "final_url": url,
        "diagnostic_note": "",
        "audited_at": "2026-08-21T00:00:00+00:00",
    }


def test_only_audited_include_urls_enter_formal_crawl_queue(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    included = "https://baike.mihoyo.com/bh3/wiki/content/101/detail"
    excluded = "https://baike.mihoyo.com/bh3/wiki/content/202/detail"
    write_jsonl(
        paths.candidate_audit_jsonl,
        [
            _candidate_audit_row(excluded, decision="exclude", priority=1),
            _candidate_audit_row(included, decision="include", priority=2),
        ],
    )
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /", request=request
            )
        requested_paths.append(request.url.path)
        body = (
            "<html><title>爱莉希雅角色档案</title><main>"
            + ("爱莉希雅与前文明角色设定测试正文。" * 30)
            + "</main></html>"
        )
        return httpx.Response(200, text=body, request=request)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    crawler = OfficialLoreCrawler(
        CrawlSettings(
            max_pages=30,
            delay_seconds=0,
            max_retries=0,
            render_dynamic=False,
        ),
        paths,
        client=client,
    )
    crawler.crawl()
    client.close()

    assert requested_paths == ["/bh3/wiki/content/101/detail"]
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert [row["url"] for row in manifest["records"]] == [included]


def test_quality_status_filters_rag_entities_and_relations(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    accepted = _document(
        "爱莉希雅是逐火十三英桀的一员。前文明角色设定与组织档案。" * 20
    )
    rejected_data = _document(
        "凯文技能伤害类型、怪物信息、武器圣痕数值和特殊机制攻略。" * 25,
        "https://baike.mihoyo.com/bh3/wiki/content/456/detail",
    ).model_dump(mode="json")
    rejected_data["document_id"] = "doc_rejected12345678"
    write_jsonl(
        paths.raw_documents,
        [accepted.model_dump(mode="json"), rejected_data],
    )

    normalized = normalize_documents(paths)
    rag_result = build_rag(paths)
    relation_result = extract_relations(paths)

    assert normalized["accepted_documents"] == 1
    assert normalized["rejected_documents"] == 1
    assert rag_result["accepted_documents"] == 1
    assert relation_result["accepted_documents"] == 1
    chunks = read_jsonl(paths.chunks)
    assert chunks
    assert {row["metadata"]["document_id"] for row in chunks} == {
        accepted.document_id
    }
    assert all(
        row["source_url"] == accepted.canonical_url
        for row in read_jsonl(paths.relations_pending)
    )


def test_fixture_text_cannot_mix_into_runtime_results(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    collected = _document(
        "爱莉希雅角色设定与前文明档案的独立运行样本。" * 25,
        "https://baike.mihoyo.com/bh3/wiki/content/700/detail",
    )
    write_jsonl(paths.raw_documents, [collected.model_dump(mode="json")])

    normalize_documents(paths)
    extract_relations(paths)
    build_rag(paths)

    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            paths.cleaned_documents,
            paths.entities,
            paths.relations_pending,
            paths.chunks,
        )
    )
    assert "本地测试夹具中的合成文本" not in runtime_text


def test_repeated_normalize_and_build_do_not_duplicate_outputs(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    document = _document("爱莉希雅角色设定与前文明档案测试正文。" * 80)
    write_jsonl(paths.raw_documents, [document.model_dump(mode="json")])

    first_normalize = normalize_documents(paths)
    first_build = build_rag(paths)
    first_chunk_ids = [row["chunk_id"] for row in read_jsonl(paths.chunks)]
    second_normalize = normalize_documents(paths)
    second_build = build_rag(paths)
    second_chunk_ids = [row["chunk_id"] for row in read_jsonl(paths.chunks)]

    assert first_normalize == second_normalize
    assert first_build == second_build
    assert first_chunk_ids == second_chunk_ids
    assert len(second_chunk_ids) == len(set(second_chunk_ids))


def test_bilibili_url_normalization_rejects_unrelated_hosts() -> None:
    canonical, video_id = normalize_bilibili_video_url(
        "https://www.bilibili.com/video/BV1kM4y1K733?p=2"
    )
    assert video_id == "BV1kM4y1K733"
    assert canonical == "https://www.bilibili.com/video/BV1kM4y1K733"
    with pytest.raises(ValueError):
        normalize_bilibili_video_url("https://example.com/video/BV1kM4y1K733")


def test_public_video_metadata_requires_uploader_allowlist_for_tier_a() -> None:
    html = (FIXTURES / "bilibili_public_video.html").read_text(encoding="utf-8")
    url = "https://www.bilibili.com/video/BV1kM4y1K733"

    unverified = parse_public_video_html(html, url, {})
    verified = parse_public_video_html(
        html,
        url,
        {"123456": "Manually verified official-account UID from a public profile."},
    )

    assert unverified.uploader_name == "合成测试上传者"
    assert unverified.content_type == "official_game_recording"
    assert unverified.source_tier == "B-recording"
    assert not unverified.uploader_verified
    assert verified.content_type == "official_video"
    assert verified.source_tier == "A"
    assert verified.uploader_verified
    assert verified.review_status == "pending"
    assert verified.subtitle_available
    assert verified.observed_characters == ["爱莉希雅"]
    assert "往世乐土" not in verified.observed_topics


def test_official_video_schema_rejects_title_only_claim() -> None:
    with pytest.raises(ValidationError):
        BilibiliVideoMetadata(
            video_id="BV1kM4y1K733",
            canonical_url="https://www.bilibili.com/video/BV1kM4y1K733",
            title="官方标题不能证明官方身份",
            content_type="official_video",
            source_tier="A",
            inspected_at="2026-08-22T00:00:00+00:00",
        )


@pytest.mark.parametrize("status_code", [403, 412, 429])
def test_blocked_video_inspection_is_single_request_and_creates_manual_template(
    tmp_path: Path, status_code: int,
) -> None:
    paths = _paths(tmp_path)
    paths.video_seed_file.parent.mkdir(parents=True, exist_ok=True)
    paths.video_seed_file.write_text(
        "https://www.bilibili.com/video/BV1kM4y1K733\n", encoding="utf-8"
    )
    paths.bilibili_official_accounts.parent.mkdir(parents=True, exist_ok=True)
    paths.bilibili_official_accounts.write_text("accounts: []\n", encoding="utf-8")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text="request blocked", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    result = inspect_videos(paths, delay_seconds=0, client=client)
    client.close()

    assert calls == 1
    assert result["metadata_blocked"] == 1
    audit = read_jsonl(paths.video_audit_jsonl)[0]
    assert audit["metadata_status"] == "metadata_access_blocked"
    assert audit["review_status"] == "pending"
    assert (paths.video_manual_inbox_dir / "BV1kM4y1K733.yaml").exists()


def test_subtitle_cleaning_preserves_timestamps_and_removes_only_safe_noise() -> None:
    cues = parse_subtitle_text(
        "1\n00:00:01,000 --> 00:00:03,000\n（音乐）\n\n"
        "2\n00:00:03,500 --> 00:00:05,000\n爱莉希雅来到往世乐土。\n\n"
        "3\n00:00:05,500 --> 00:00:07,000\n爱莉希雅来到往世乐土。\n",
        ".srt",
    )
    cleaned = clean_subtitle_cues(cues)
    assert len(cues) == 3
    assert len(cleaned) == 1
    assert cleaned[0].start_seconds == 3.5
    assert cleaned[0].end_seconds == 5.0
    assert cleaned[0].content == "爱莉希雅来到往世乐土。"


def test_video_subtitles_stay_pending_and_separate_from_main_rag(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    metadata = parse_public_video_html(
        (FIXTURES / "bilibili_public_video.html").read_text(encoding="utf-8"),
        "https://www.bilibili.com/video/BV1kM4y1K733",
        {},
    )
    write_json(
        paths.video_metadata_dir / f"{metadata.video_id}.json",
        metadata.model_dump(mode="json"),
    )
    subtitle = tmp_path / "subtitle.srt"
    subtitle.write_text(
        "1\n00:00:01,000 --> 00:00:05,000\n"
        + ("爱莉希雅在往世乐土中的剧情证据。" * 40),
        encoding="utf-8",
    )

    result = process_video_subtitles(metadata.video_id, paths, input_path=subtitle)
    review = build_video_review(paths)

    assert result["chunks"] >= 1
    assert review["confirmed_video_facts"] == 0
    assert all(row["review_status"] == "pending" for row in read_jsonl(paths.video_chunks))
    assert read_jsonl(paths.video_chunks)[0]["source_url"].endswith("?t=1")
    assert not paths.chunks.exists()
    assert "No facts or relations are automatically confirmed" in paths.video_fact_review.read_text(encoding="utf-8")


def test_tier_c_video_never_generates_even_pending_chunks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    html = (FIXTURES / "bilibili_public_video.html").read_text(encoding="utf-8")
    html = html.replace("全剧情", "同人理论推测")
    metadata = parse_public_video_html(
        html, "https://www.bilibili.com/video/BV1kM4y1K733", {}
    )
    write_json(
        paths.video_metadata_dir / f"{metadata.video_id}.json",
        metadata.model_dump(mode="json"),
    )
    subtitle = tmp_path / "fan_theory.txt"
    subtitle.write_text("爱莉希雅同人理论推测。" * 80, encoding="utf-8")

    result = process_video_subtitles(metadata.video_id, paths, input_path=subtitle)

    assert metadata.content_type == "fan_theory"
    assert metadata.source_tier == "C"
    assert result["chunks"] == 0
    assert read_jsonl(paths.video_chunks) == []


def test_full_video_subtitle_runtime_paths_are_gitignored() -> None:
    ignore = (FIXTURES.parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/video_sources/subtitles_raw/*" in ignore
    assert "data/video_sources/subtitles_cleaned/*" in ignore
    assert "data/video_sources/chunks/*" in ignore


def test_player_summary_defaults_to_tier_b_and_pending() -> None:
    html = (FIXTURES / "bilibili_public_video.html").read_text(encoding="utf-8")
    html = html.replace("爱莉希雅全剧情", "爱莉希雅剧情梳理")
    metadata = parse_public_video_html(
        html, "https://www.bilibili.com/video/BV1kM4y1K733", {}
    )
    assert metadata.content_type == "community_lore_summary"
    assert metadata.source_tier == "B"
    assert metadata.review_status == "pending"


def test_source_registry_identifies_tiers_and_disables_tier_b_discovery() -> None:
    registry_path = FIXTURES.parent.parent / "data" / "config" / "source_registry.yaml"
    definitions = load_source_registry(registry_path)

    assert identify_source_tier(
        definitions,
        url="https://www.bh3.com/news/123",
    ) == "A"
    assert identify_source_tier(
        definitions,
        source_type="official_game_manual",
    ) == "A-manual"
    bh3text = next(row for row in definitions if row.source_id == "bh3text")
    assert bh3text.tier == "Tier B-primary-transcript"
    assert bh3text.official_host is False
    assert bh3text.direct_game_text_claimed is True
    assert bh3text.requires_sample_verification is True
    assert bh3text.can_enter_supplemental_rag is True
    assert bh3text.can_override_tier_a is False
    assert bh3text.can_generate_confirmed_relations is False
    helper = next(row for row in definitions if row.source_id == "bh3helper")
    assert helper.tier == "Tier B-curated-index"
    assert helper.source_type == "community_story_guide"
    assert helper.source_role == "discovery_and_story_navigation"
    assert helper.official_host is False
    assert helper.contains_curator_annotations is True
    assert helper.contains_official_outbound_links is True
    assert helper.can_enter_main_lore_rag is False
    assert helper.can_enter_navigation_index is True
    assert helper.can_generate_confirmed_relations is False
    assert helper.can_override_tier_a is False
    with pytest.raises(ValueError):
        discovery_sources(definitions, ["community-wiki"])
    with pytest.raises(ValueError):
        discovery_sources(definitions, ["bh3text"])
    with pytest.raises(ValueError):
        discovery_sources(definitions, ["bh3helper"])


def test_official_news_keeps_lore_and_removes_promotion_and_numbers() -> None:
    result = clean_content_for_url(
        "爱莉希雅在前文明的角色故事与身份介绍。\n"
        "本期补给可获得角色，概率公示请见活动页。\n"
        "技能倍率为350%，攻击力提高40%。\n"
        "她与往世乐土的剧情仍在延续。",
        "https://www.bh3.com/news/123",
    )
    assert "前文明的角色故事" in result.content
    assert "往世乐土的剧情" in result.content
    assert "补给" not in result.content
    assert "350%" not in result.content


def test_comic_metadata_is_never_treated_as_rag_body(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    comic = OfficialComicMetadata(
        title="合成测试漫画书目",
        chapter="合成测试章节",
        summary="",
        source_url="https://comic.bh3.com/book/123",
    )
    write_jsonl(paths.comic_metadata, [comic.model_dump(mode="json")])

    result = build_rag(paths)

    assert result["chunks"] == 0
    assert read_jsonl(paths.chunks) == []


def _manual_record_payload(
    *,
    status: str = "pending",
    source_note: str = "游戏内角色档案人工核对",
) -> dict[str, object]:
    return {
        "record_id": "manual-elysia-001",
        "title": "爱莉希雅游戏内档案（合成测试）",
        "source_type": "official_game_manual",
        "game_section": "角色档案",
        "chapter": "本地测试章节",
        "character_names": ["爱莉希雅"],
        "era": "前文明",
        "universe": "本征世界",
        "summary": "爱莉希雅的本地人工资料摘要。",
        "evidence": "本地测试证据，不代表真实游戏文本。",
        "source_note": source_note,
        "captured_by": "manual",
        "review_status": status,
    }


def test_manual_record_without_source_note_is_rejected(tmp_path: Path) -> None:
    record = tmp_path / "manual.json"
    record.write_text(
        json.dumps(_manual_record_payload(source_note=""), ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ManualRecordValidationError):
        load_manual_records(record)


def test_pending_manual_record_cannot_enter_rag(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.manual_accepted_dir.mkdir(parents=True, exist_ok=True)
    (paths.manual_accepted_dir / "pending.json").write_text(
        json.dumps(_manual_record_payload(status="pending"), ensure_ascii=False),
        encoding="utf-8",
    )

    result = build_rag(paths)

    assert result["manual_accepted_documents"] == 0
    assert read_jsonl(paths.chunks) == []


def test_accepted_manual_and_web_sources_remain_distinct(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    web = _document("爱莉希雅在前文明的角色档案与往世乐土故事。" * 30)
    write_jsonl(paths.raw_documents, [web.model_dump(mode="json")])
    normalize_documents(paths)
    paths.manual_accepted_dir.mkdir(parents=True, exist_ok=True)
    (paths.manual_accepted_dir / "accepted.json").write_text(
        json.dumps(_manual_record_payload(status="accepted"), ensure_ascii=False),
        encoding="utf-8",
    )

    result = build_rag(paths)
    chunks = read_jsonl(paths.chunks)

    assert result["accepted_documents"] == 1
    assert result["manual_accepted_documents"] == 1
    assert {row["metadata"]["source_type"] for row in chunks} == {
        "official_wiki",
        "official_game_manual",
    }
    assert {row["metadata"]["source_tier"] for row in chunks} == {"A", "A-manual"}
    assert len({row["metadata"]["document_id"] for row in chunks}) == 2


@pytest.mark.parametrize(
    (
        "direct",
        "substantial",
        "documents",
        "official_documents",
        "dedicated",
        "confirmed_entities",
        "confirmed_relations",
        "expected",
    ),
    [
        (0, 0, 0, 0, False, 0, 0, "missing"),
        (1, 0, 1, 1, False, 0, 0, "thin"),
        (0, 2, 2, 2, False, 0, 0, "thin"),
        (2, 0, 1, 1, False, 0, 0, "thin"),
        (2, 0, 2, 2, False, 0, 0, "usable"),
        (3, 0, 1, 1, True, 0, 0, "usable"),
        (5, 0, 3, 3, False, 0, 0, "usable"),
        (5, 0, 3, 3, False, 1, 0, "strong"),
    ],
)
def test_coverage_status_calculation(
    direct: int,
    substantial: int,
    documents: int,
    official_documents: int,
    dedicated: bool,
    confirmed_entities: int,
    confirmed_relations: int,
    expected: str,
) -> None:
    assert calculate_coverage_status(
        direct_evidence_chunks=direct,
        substantial_evidence_chunks=substantial,
        distinct_documents=documents,
        distinct_official_documents=official_documents,
        dedicated_page_available=dedicated,
        confirmed_entities=confirmed_entities,
        confirmed_relations=confirmed_relations,
    ) == expected


def test_summary_page_mentioning_seven_characters_does_not_make_them_usable(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    chunk = _rag_chunk(
        "英桀名单：爱莉希雅、伊甸、维尔薇、樱、梅比乌斯、格蕾修、华。",
        entity_names=["爱莉希雅", "伊甸", "维尔薇", "樱", "梅比乌斯", "格蕾修", "华"],
    )
    write_jsonl(paths.chunks, [chunk.model_dump(mode="json")])

    build_coverage(paths)
    rows = {
        row["topic_name"]: row
        for row in json.loads(paths.coverage_json.read_text(encoding="utf-8"))["topics"]
    }

    for name in ("爱莉希雅", "伊甸", "维尔薇", "樱", "梅比乌斯", "格蕾修", "华"):
        assert rows[name]["coverage_status"] == "missing"
        assert rows[name]["mention_only_chunks"] == 1
        assert rows[name]["direct_evidence_chunks"] == 0


def test_flame_chaser_name_list_is_mention_only() -> None:
    chunk = _rag_chunk("英桀名单：爱莉希雅、伊甸、维尔薇、樱、梅比乌斯、格蕾修、华。")
    assessment = classify_chunk_evidence(chunk, "爱莉希雅")
    assert assessment is not None
    assert assessment.kind == "mention_only"


def test_about_page_title_is_direct_for_named_target() -> None:
    chunk = _rag_chunk(
        "两名角色进行了一段完整对话。",
        title="爱莉希雅-关于芽衣·其一",
    )
    assessment = classify_chunk_evidence(chunk, "雷电芽衣")
    assert assessment is not None
    assert assessment.kind == "direct_evidence"


def test_multiple_chunks_from_same_document_count_as_one_document(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    chunks = [
        _rag_chunk(
            "伊甸曾经生活在前文明，她的经历、身份与所属组织逐火之蛾的历史设定有关。" * 4,
            document_id="doc_shared_001",
            chunk_id=f"chunk_shared_{index:03d}",
        )
        for index in range(3)
    ]
    write_jsonl(paths.chunks, [row.model_dump(mode="json") for row in chunks])

    build_coverage(paths)
    rows = json.loads(paths.coverage_json.read_text(encoding="utf-8"))["topics"]
    eden = next(row for row in rows if row["topic_name"] == "伊甸")

    assert eden["direct_evidence_chunks"] == 3
    assert eden["distinct_documents"] == 1
    assert eden["coverage_status"] == "thin"


def test_dedicated_character_page_can_produce_direct_evidence(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    chunks = [
        _rag_chunk(
            "爱莉希雅的身份、经历与前文明设定。" * 4,
            title="爱莉希雅角色档案",
            document_id="doc_elysia_dedicated",
            chunk_id=f"chunk_elysia_{index:03d}",
        )
        for index in range(3)
    ]
    write_jsonl(paths.chunks, [row.model_dump(mode="json") for row in chunks])

    build_coverage(paths)
    rows = json.loads(paths.coverage_json.read_text(encoding="utf-8"))["topics"]
    elysia = next(row for row in rows if row["topic_name"] == "爱莉希雅")

    assert elysia["dedicated_page_available"] is True
    assert elysia["direct_evidence_chunks"] == 3
    assert elysia["coverage_status"] == "usable"


def test_unverified_video_metadata_cannot_raise_coverage(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_jsonl(
        paths.video_audit_jsonl,
        [
            {
                "video_id": "BV1F5411K7Xg",
                "canonical_url": "https://www.bilibili.com/video/BV1F5411K7Xg",
                "title": "爱莉希雅剧情",
                "observed_characters": ["爱莉希雅"],
                "content_type": "community_lore_summary",
                "source_tier": "B",
                "review_status": "pending",
                "inspected_at": "2026-08-21T00:00:00+00:00",
            }
        ],
    )

    build_coverage(paths)
    rows = json.loads(paths.coverage_json.read_text(encoding="utf-8"))["topics"]
    elysia = next(row for row in rows if row["topic_name"] == "爱莉希雅")

    assert elysia["coverage_status"] == "missing"
    assert elysia["distinct_official_documents"] == 0
    assert elysia["direct_evidence_chunks"] == 0
    assert elysia["potential_video_sources"][0]["video_id"] == "BV1F5411K7Xg"


def test_alias_workbench_only_suggests_and_never_merges(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = build_review_workbench(paths)
    review = paths.entities_review.read_text(encoding="utf-8")
    assert result["alias_merge_suggestions"] == 2
    assert "真我·人之律者" in review
    assert "粉色妖精小姐♪" in review
    assert "自动执行 |" in review
    assert "| 否 |" in review
    assert not paths.entities.exists()


def test_pending_relation_conflicts_remain_human_review_only(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_jsonl(
        paths.relations_pending,
        [
            {
                "relation_id": "relation_official_001",
                "source_entity": "爱莉希雅",
                "relation": "KNOWS",
                "target_entity": "凯文",
                "evidence": "爱莉希雅明确说自己认识凯文。",
                "source_url": "https://baike.mihoyo.com/bh3/wiki/content/1/detail",
                "confidence": 0.8,
                "review_status": "pending",
            }
        ],
    )
    write_jsonl(
        paths.bh3text_relations_pending,
        [
            {
                "relation_id": "bh3relation_pending_001",
                "source_entity": "爱莉希雅",
                "relation": "TRUSTS",
                "target_entity": "凯文",
                "evidence": "这是一条仍需官方佐证的短证据。",
                "speaker": "爱莉希雅",
                "arc": "往世乐土",
                "chapter": "在无限的阴影之中",
                "scene": "爱莉希雅-关于凯文",
                "source_url": "https://www.bh3text.com/dialog/er/1/elysia-kevin",
                "source_tier": "Tier B-primary-transcript",
                "confidence": 0.6,
                "requires_official_corroboration": True,
                "review_status": "pending",
            }
        ],
    )

    result = build_review_workbench(paths)

    assert result["pending_relations"] == 2
    assert result["relation_conflicts"] == 1
    conflicts = paths.relation_conflicts.read_text(encoding="utf-8")
    assert "KNOWS" in conflicts and "TRUSTS" in conflicts
    assert not paths.relations_confirmed.exists()


def test_character_cooccurrence_alone_does_not_create_relation() -> None:
    document = _document("爱莉希雅、凯文与伊甸出现在同一段官方页面。")
    assert extract_rule_relations(document) == []


def test_explicit_alias_relation_remains_pending() -> None:
    document = _document("爱莉希雅又名粉色妖精小姐♪。")
    relations = extract_rule_relations(document)
    assert len(relations) == 1
    assert relations[0].relation == "ALIAS_OF"
    assert relations[0].target_entity == "粉色妖精小姐♪"
    assert relations[0].review_status == "pending"


def _bh3text_html(
    title: str = "爱莉希雅-关于凯文·其一",
    lines: list[str] | None = None,
) -> str:
    dialogue = lines or [
        "芽衣：你很早就认识凯文吗？",
        "爱莉希雅：我知道他的名字与一些经历。",
        "风吹过空旷的大厅。",
    ]
    paragraphs = "".join(f"<p>{line}</p>" for line in dialogue)
    return (
        "<html><body><nav><a href='/dialog/'>← 对话文本</a></nav>"
        f"<main><h1>{title}</h1>{paragraphs}"
        "<a href='/'>首页</a><a href='/about/'>关于本站</a></main>"
        "<footer>下一页</footer></body></html>"
    )


def _bh3text_document(
    *,
    title: str = "爱莉希雅-关于凯文·其一",
    turns: list[DialogueTurn] | None = None,
) -> BH3TextDocument:
    dialogue_turns = turns or [
        DialogueTurn(
            turn_index=1,
            speaker="芽衣",
            text="你很早就认识凯文吗？",
            turn_type="dialogue",
        ),
        DialogueTurn(
            turn_index=2,
            speaker="爱莉希雅",
            text="我知道他的名字与经历。",
            turn_type="dialogue",
        ),
    ]
    rendered = "\n".join(
        f"{turn.speaker}：{turn.text}" if turn.speaker else turn.text
        for turn in dialogue_turns
    )
    return BH3TextDocument(
        document_id="bh3text_synthetic_001",
        title=title,
        arc="往世乐土",
        chapter="在无限的阴影之中",
        scene=title,
        source_url="https://www.bh3text.com/dialog/er/1/synthetic",
        dialogue_turns=dialogue_turns,
        character_names=["爱莉希雅", "凯文", "芽衣"],
        topic_names=["往世乐土"],
        content_hash=content_hash(rendered),
        retrieved_at="2026-08-21T00:00:00+00:00",
    )


def test_bh3text_discovery_only_audits_details_and_never_builds_rag(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    directory_rows = {
        "/dialog/er/1": ("在无限的阴影之中", "爱莉希雅-关于凯文·其一"),
        "/dialog/er/2": ("致世界上的另一个我", "伊甸-关于爱莉希雅·其一"),
        "/dialog/er/3": ("愿时光永驻此刻，愿明日——", "梅比乌斯-关于自身·其一"),
        "/dialog/mainline/1/29": ("第二十九章 来自乐土", "29-12-3 十三英桀"),
        "/dialog/mainline/1/30": ("第三十章 英雄们的葬礼", "30-13-1 维尔薇篇"),
        "/dialog/mainline/1/31": ("第三十一章 因你而在的故事", "31-2-1 侵蚀之律者"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rstrip("/") or "/"
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /dialog/", request=request)
        if path == "/about":
            return httpx.Response(
                200,
                text="游戏文本存档，内容来源于网络收集，版权归米哈游所有。",
                request=request,
            )
        if path == "/dialog":
            links = "".join(
                f"<a href='{url}/'>{title}</a>"
                for url, (title, _) in directory_rows.items()
            )
            return httpx.Response(200, text=f"<html>{links}</html>", request=request)
        if path in directory_rows:
            _, scene = directory_rows[path]
            return httpx.Response(
                200,
                text=f"<h1>目录</h1><a href='{path}/{scene}'>{scene}</a>",
                request=request,
            )
        raise AssertionError(f"unexpected URL: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    result = discover_bh3text(
        paths,
        max_candidates=300,
        delay_seconds=0,
        client=client,
        sleeper=lambda _: None,
    )
    client.close()

    audit = read_jsonl(paths.bh3text_candidate_audit_jsonl)
    directory_urls = {f"https://www.bh3text.com{path}" for path in directory_rows}
    assert result["directory_pages_discovered"] == 6
    assert result["directory_pages_in_rag"] == 0
    assert all(row["url"] not in directory_urls for row in audit)
    assert not paths.bh3text_documents.exists()
    assert not paths.bh3text_chunks.exists()


def test_bh3text_robots_disallow_stops_without_bypass(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/robots.txt"
        return httpx.Response(200, text="User-agent: *\nDisallow: /dialog/", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(BH3TextAccessError, match="disallows"):
        discover_bh3text(
            _paths(tmp_path),
            delay_seconds=0,
            client=client,
            sleeper=lambda _: None,
        )
    client.close()


def test_bh3text_parser_preserves_scene_speakers_narration_and_order() -> None:
    document = parse_bh3text_dialogue(
        _bh3text_html(),
        source_url="https://www.bh3text.com/dialog/er/1/synthetic",
        arc="往世乐土",
        chapter="在无限的阴影之中",
        scene="爱莉希雅-关于凯文·其一",
        retrieved_at="2026-08-21T00:00:00+00:00",
    )

    assert document.chapter == "在无限的阴影之中"
    assert document.scene == "爱莉希雅-关于凯文·其一"
    assert [turn.turn_index for turn in document.dialogue_turns] == [1, 2, 3]
    assert [turn.speaker for turn in document.dialogue_turns] == ["芽衣", "爱莉希雅", None]
    assert document.dialogue_turns[2].turn_type == "narration"
    assert all("首页" not in turn.text for turn in document.dialogue_turns)
    assert all("下一页" not in turn.text for turn in document.dialogue_turns)


def test_bh3text_parser_supports_stage_dialog_line_structure() -> None:
    html = """
    <html><body>
      <section id="main-content"><h1>伊甸-关于爱莉希雅·其一</h1></section>
      <section class="stage" id="stage_1">
        <div class="content dialog-line">
          <span class="dialog-actor dialog-descriptive">芽衣</span>
          <span class="dialog-content">你信任爱莉希雅吗？</span>
        </div>
        <div class="content dialog-line">
          <span class="dialog-content">大厅中响起悠远的音乐。</span>
        </div>
        <div class="content dialog-line">
          <span class="dialog-actor dialog-descriptive">伊甸</span>
          <span class="dialog-content">这是一个需要认真回答的问题。</span>
        </div>
      </section>
    </body></html>
    """
    document = parse_bh3text_dialogue(
        html,
        source_url="https://www.bh3text.com/dialog/er/1/stage-structure",
        arc="往世乐土",
        chapter="在无限的阴影之中",
        scene="伊甸-关于爱莉希雅·其一",
        retrieved_at="2026-08-21T00:00:00+00:00",
    )

    assert [turn.speaker for turn in document.dialogue_turns] == ["芽衣", None, "伊甸"]
    assert document.dialogue_turns[1].turn_type == "narration"
    assert [turn.turn_index for turn in document.dialogue_turns] == [1, 2, 3]


def test_short_bh3text_page_is_one_scene_chunk() -> None:
    chunks = chunk_bh3text_document(_bh3text_document())
    assert len(chunks) == 1
    assert chunks[0].turn_start == 1
    assert chunks[0].turn_end == 2
    assert chunks[0].scene == "爱莉希雅-关于凯文·其一"


def test_long_bh3text_page_splits_on_turns_with_overlap() -> None:
    turns = [
        DialogueTurn(
            turn_index=index,
            speaker="爱莉希雅" if index % 2 else "芽衣",
            text=f"第{index}轮" + "这是保持完整且不得从中间切断的合成台词。" * 3,
            turn_type="dialogue",
        )
        for index in range(1, 51)
    ]
    chunks = chunk_bh3text_document(_bh3text_document(turns=turns))

    assert len(chunks) > 1
    assert all(chunk.dialogue_turns for chunk in chunks)
    assert all(
        turn.text in chunk.content
        for chunk in chunks
        for turn in chunk.dialogue_turns
    )
    for left, right in zip(chunks, chunks[1:]):
        left_indices = {turn.turn_index for turn in left.dialogue_turns}
        right_indices = {turn.turn_index for turn in right.dialogue_turns}
        assert 2 <= len(left_indices & right_indices) <= 4


def test_scene_cooccurrence_and_about_title_create_evidence_edges_only() -> None:
    document = _bh3text_document()
    edges = build_dialogue_evidence_edges(document)
    relations = {edge.relation for edge in edges}

    assert "SPEAKS_TO" in relations
    assert "SPEAKS_ABOUT" in relations
    assert "APPEARS_WITH" in relations
    assert all(edge.relation != "FRIEND_OF" for edge in edges)
    assert extract_pending_semantic_relations(document) == []


def test_jokes_hypotheses_and_questions_do_not_create_semantic_relations() -> None:
    turns = [
        DialogueTurn(
            turn_index=1,
            speaker="爱莉希雅",
            text="爱莉希雅是伊甸的朋友，只是一个玩笑。",
            turn_type="dialogue",
        ),
        DialogueTurn(
            turn_index=2,
            speaker="芽衣",
            text="如果凯文信任梅比乌斯，会怎样？",
            turn_type="dialogue",
        ),
    ]
    assert extract_pending_semantic_relations(_bh3text_document(turns=turns)) == []


def test_explicit_bh3text_semantic_relation_stays_pending() -> None:
    turns = [
        DialogueTurn(
            turn_index=1,
            speaker="爱莉希雅",
            text="爱莉希雅是逐火十三英桀的一员。",
            turn_type="dialogue",
        )
    ]
    relations = extract_pending_semantic_relations(_bh3text_document(turns=turns))

    assert len(relations) == 1
    assert relations[0].relation == "MEMBER_OF"
    assert relations[0].review_status == "pending"
    assert relations[0].requires_official_corroboration is True
    assert relations[0].source_tier == "Tier B-primary-transcript"


def test_bh3text_never_counts_as_official_documents(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    document = _bh3text_document()
    chunk = chunk_bh3text_document(document)[0]
    write_jsonl(paths.bh3text_documents, [document.model_dump(mode="json")])
    write_jsonl(paths.bh3text_chunks, [chunk.model_dump(mode="json")])

    build_coverage(paths)
    rows = json.loads(paths.coverage_json.read_text(encoding="utf-8"))["topics"]
    elysia = next(row for row in rows if row["topic_name"] == "爱莉希雅")

    assert elysia["official_coverage"]["distinct_official_documents"] == 0
    assert elysia["official_coverage"]["coverage_status"] == "missing"
    assert elysia["bh3text_transcript_coverage"]["direct_evidence_chunks"] == 1
    assert elysia["combined_coverage"]["distinct_official_documents"] == 0


def test_bh3text_complete_text_runtime_paths_are_gitignored() -> None:
    ignore = (FIXTURES.parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/raw/*" in ignore
    assert "data/cleaned/*" in ignore
    assert "data/chunks/*" in ignore
    assert "data/relations/*" in ignore
    assert "data/review/*" in ignore


def test_bh3text_fixture_text_stays_in_temporary_runtime(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    synthetic_marker = "本地BH3Text测试夹具专用标记"
    document = parse_bh3text_dialogue(
        _bh3text_html(lines=[f"爱莉希雅：{synthetic_marker}"]),
        source_url="https://www.bh3text.com/dialog/er/1/synthetic",
        arc="往世乐土",
        chapter="在无限的阴影之中",
        scene="合成测试场景",
        retrieved_at="2026-08-21T00:00:00+00:00",
    )
    write_jsonl(paths.bh3text_documents, [document.model_dump(mode="json")])

    assert synthetic_marker in paths.bh3text_documents.read_text(encoding="utf-8")
    assert str(paths.bh3text_documents).startswith(str(tmp_path))


def test_repeated_bh3text_crawl_does_not_duplicate_documents_or_chunks(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    detail_url = "https://www.bh3text.com/dialog/er/1/synthetic"
    write_jsonl(
        paths.bh3text_candidate_audit_jsonl,
        [
            {
                "url": detail_url,
                "arc": "往世乐土",
                "chapter": "在无限的阴影之中",
                "scene": "爱莉希雅-关于凯文·其一",
                "title": "爱莉希雅-关于凯文·其一",
                "matched_characters": ["爱莉希雅", "凯文"],
                "matched_topics": [],
                "priority_score": 100,
                "decision": "include",
                "reason": "合成审计记录",
            }
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rstrip("/") or "/"
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /dialog/", request=request)
        if path == "/about":
            return httpx.Response(
                200,
                text="游戏文本存档，内容来源于网络收集，版权归米哈游所有。",
                request=request,
            )
        if path == "/dialog":
            return httpx.Response(200, text="<h1>对话文本</h1>", request=request)
        if path == "/dialog/er/1/synthetic":
            return httpx.Response(200, text=_bh3text_html(), request=request)
        raise AssertionError(f"unexpected URL: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    for _ in range(2):
        crawl_bh3text(
            paths,
            max_pages=1,
            delay_seconds=0,
            client=client,
            sleeper=lambda _: None,
        )
    client.close()

    assert len(read_jsonl(paths.bh3text_documents)) == 1
    assert len(read_jsonl(paths.bh3text_chunks)) == 1
    manifest = json.loads(paths.bh3text_manifest.read_text(encoding="utf-8"))
    assert manifest["independent_transcript_index_ready"] is False
    assert manifest["sampled_verified_documents"] == 0


def _bh3helper_root_html() -> str:
    return """
    <html><body>
      <a href="/pages/common.html?id=29">第二十九章 来自乐土</a>
      <a href="/pages/common.html?id=30">第三十章 英雄们的葬礼</a>
      <a href="/pages/common.html?id=32">第三十二章 世界的止境</a>
      <a href="/pages/common.html?id=9001">第二部 活动攻略</a>
    </body></html>
    """


def _bh3helper_detail_html() -> str:
    return """
    <html><head><title>第二十九章 来自乐土 | 《崩坏3》剧情助手</title></head>
    <body>
      <h1>第二十九章 来自乐土</h1>
      <div class="common-info">
        <p>更新版本：5.8</p><p>更新日期：2022-05-19</p>
        <p>参考时长：4小时</p><p>文本字数：12345</p>
      </div>
      <section class="content-section">
        <h2 class="content-title">观前内容</h2>
        <a href="/pages/common.html?id=3003">愿时光永驻此刻，愿明日——</a>
      </section>
      <section class="content-section">
        <h2 class="content-title">版本PV</h2>
        <a href="https://www.bilibili.com/video/BV1kM4y1K733">官方PV候选</a>
      </section>
      <section class="content-section"><h2 class="content-title">官方资讯</h2>
        <a href="https://bbs.mihoyo.com/bh3/wiki/content/781/detail">米游社页面</a>
      </section>
      <h3>英桀档案</h3><h3>角色档案 - 爱莉希雅</h3><h3>登场角色资料 - 雷电芽衣</h3>
      <div class="content-hint">观看建议：先完成往世乐土前置内容。本提示由网站作者整理。</div>
      <div class="dialog-viewer-wrapper">雷电芽衣：SYNTHETIC_DIALOGUE_MUST_NOT_PERSIST</div>
    </body></html>
    """


def test_bh3helper_page_parses_dynamic_metadata_without_dialogue_text() -> None:
    navigation, links, archives, annotations, audit = parse_bh3helper_page(
        _bh3helper_detail_html(),
        source_url="https://bh3helper.xrysnow.xyz/pages/common.html?id=29",
        recommended_order=1,
    )
    assert navigation.title == "第二十九章 来自乐土"
    assert navigation.content_type == "mainline_chapter"
    assert navigation.chapter_number == "29"
    assert navigation.update_version == "5.8"
    assert navigation.update_date == "2022-05-19"
    assert navigation.estimated_duration == "4小时"
    assert navigation.text_word_count == 12345
    assert "爱莉希雅" in navigation.character_names
    assert navigation.source_tier == "Tier B-curated-index"
    assert audit["embedded_dialogue_present"] is True
    assert audit["embedded_dialogue_content_hash"]
    assert audit["embedded_dialogue_minhash"]
    assert audit["embedded_dialogue_text_saved"] is False
    assert all(row.official_status == "unverified" for row in links)
    assert all(row.crawl_recommendation == "review" for row in links)
    assert any(row.archive_type == "flame_chaser_archive" for row in archives)
    assert annotations and annotations[0].official_fact_allowed is False
    persisted = json.dumps(
        {
            "navigation": navigation.model_dump(mode="json"),
            "links": [row.model_dump(mode="json") for row in links],
            "archives": [row.model_dump(mode="json") for row in archives],
            "annotations": [row.model_dump(mode="json") for row in annotations],
            "audit": audit,
        },
        ensure_ascii=False,
    )
    assert "SYNTHETIC_DIALOGUE_MUST_NOT_PERSIST" not in persisted


def test_bh3helper_discovery_uses_only_public_links_and_isolated_outputs(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404, request=request)
        return httpx.Response(200, text="<html><body>app</body></html>", request=request)

    def renderer(url: str) -> str:
        return _bh3helper_root_html() if url.endswith("/") else _bh3helper_detail_html()

    write_jsonl(paths.chunks, [{"sentinel": "main-lore"}])
    write_jsonl(paths.bh3text_chunks, [{"sentinel": "bh3text"}])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = discover_bh3helper(
            paths,
            max_pages=1,
            delay_seconds=0,
            client=client,
            renderer=renderer,
            sleeper=lambda _: None,
        )

    assert result["root_rendered"] is True
    assert result["numeric_id_scanning"] is False
    assert result["relevant_pages_discovered"] == 2
    assert result["pages_parsed_total"] == 1
    assert any("id=29" in url for url in requested)
    assert not any("id=28" in url or "id=31" in url for url in requested)
    assert read_jsonl(paths.chunks) == [{"sentinel": "main-lore"}]
    assert read_jsonl(paths.bh3text_chunks) == [{"sentinel": "bh3text"}]
    assert len(read_jsonl(paths.bh3helper_navigation)) == 1
    assert all(
        row["official_status"] == "unverified"
        for row in read_jsonl(paths.bh3helper_official_links)
    )
    assert all(
        row["official_fact_allowed"] is False
        for row in read_jsonl(paths.bh3helper_annotations)
    )


def test_bh3helper_duplicate_mapping_builds_navigation_only(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    navigation, links, archives, annotations, audit = parse_bh3helper_page(
        _bh3helper_detail_html(),
        source_url="https://bh3helper.xrysnow.xyz/pages/common.html?id=29",
        recommended_order=1,
    )
    write_jsonl(paths.bh3helper_navigation, [navigation.model_dump(mode="json")])
    write_jsonl(paths.bh3helper_official_links, [row.model_dump(mode="json") for row in links])
    write_jsonl(paths.bh3helper_archive_candidates, [row.model_dump(mode="json") for row in archives])
    write_jsonl(paths.bh3helper_annotations, [row.model_dump(mode="json") for row in annotations])
    write_json(paths.bh3helper_manifest, {"pages": [audit]})
    write_jsonl(
        paths.bh3text_candidate_audit_jsonl,
        [{
            "chapter": "第二十九章 来自乐土",
            "title": "爱莉希雅-关于自身",
            "url": "https://www.bh3text.com/dialog/main/29/elysia",
        }],
    )
    write_jsonl(paths.chunks, [{"sentinel": "main-lore"}])
    write_jsonl(paths.bh3text_chunks, [{"sentinel": "bh3text"}])

    mapped = map_duplicate_sources(paths)
    built = build_story_navigation(paths)

    assert mapped["duplicate_mappings"] == 1
    assert built["navigation_chunks"] == 1
    assert read_jsonl(paths.chunks) == [{"sentinel": "main-lore"}]
    assert read_jsonl(paths.bh3text_chunks) == [{"sentinel": "bh3text"}]
    chunk_text = read_jsonl(paths.story_navigation_chunks)[0]["content"]
    assert "SYNTHETIC_DIALOGUE_MUST_NOT_PERSIST" not in chunk_text
    assert "用途限制：仅用于剧情导航" in chunk_text
    graph = read_jsonl(paths.source_link_graph)
    assert graph
    assert not ({row["relation"] for row in graph} & {
        "MEMBER_OF", "ALLY_OF", "ENEMY_OF", "KNOWS", "FRIEND_OF"
    })
    assert not paths.relations_confirmed.exists()


def test_bh3helper_does_not_raise_official_coverage(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    navigation, _, _, _, _ = parse_bh3helper_page(
        _bh3helper_detail_html(),
        source_url="https://bh3helper.xrysnow.xyz/pages/common.html?id=29",
    )
    write_jsonl(paths.bh3helper_navigation, [navigation.model_dump(mode="json")])
    build_coverage(paths)
    matrix = json.loads(paths.coverage_json.read_text(encoding="utf-8"))
    elysia = next(row for row in matrix["topics"] if row["topic_name"] == "爱莉希雅")
    assert elysia["official_coverage"]["distinct_official_documents"] == 0
    assert elysia["official_coverage"]["coverage_status"] == "missing"


def test_bh3helper_scope_links_do_not_construct_or_scan_ids() -> None:
    links = discover_public_scope_links(_bh3helper_root_html())
    assert links == [
        (
            "第二十九章 来自乐土",
            "https://bh3helper.xrysnow.xyz/pages/common.html?id=29",
        ),
        (
            "第三十章 英雄们的葬礼",
            "https://bh3helper.xrysnow.xyz/pages/common.html?id=30",
        ),
    ]


def test_bh3helper_runtime_data_is_gitignored() -> None:
    ignore = (FIXTURES.parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/story_guide/*" in ignore
    assert "!data/story_guide/.gitkeep" in ignore


_GROUP_CHAPTERS = {
    "elysian_realm_1": "在无限的阴影之中",
    "elysian_realm_2": "致世界上的另一个我",
    "elysian_realm_3": "愿时光永驻此刻，愿明日——",
    "mainline_29": "第二十九章 来自乐土",
    "mainline_30": "第三十章 英雄们的葬礼",
    "mainline_31": "第三十一章 因你而在的故事",
}


def _group_document(
    group_id: str,
    index: int,
    *,
    involves_elysia: bool = True,
) -> BH3TextDocument:
    chapter = _GROUP_CHAPTERS[group_id]
    other = f"角色{group_id}_{index}"
    turns = [
        DialogueTurn(
            turn_index=1,
            speaker="芽衣",
            text="我们来确认这段记忆。",
            turn_type="dialogue",
        ),
        DialogueTurn(
            turn_index=2,
            speaker="爱莉希雅" if involves_elysia else other,
            text="英桀与律者身份必须以原始台词核验。",
            turn_type="dialogue",
        ),
        DialogueTurn(
            turn_index=3,
            speaker=other,
            text="我会保留记忆体中的原意。",
            turn_type="dialogue",
        ),
        DialogueTurn(
            turn_index=4,
            speaker="芽衣",
            text="说话者和顺序也要一致。",
            turn_type="dialogue",
        ),
        DialogueTurn(
            turn_index=5,
            speaker="爱莉希雅" if involves_elysia else other,
            text="那么就从这一幕开始吧。",
            turn_type="dialogue",
        ),
    ]
    rendered = "\n".join(turn.text for turn in turns)
    path_group = "mainline/1" if group_id.startswith("mainline") else "er"
    return BH3TextDocument(
        document_id=f"bh3text_{group_id}_{index:03d}",
        title=f"{chapter}-核验场景{index}",
        arc="主线第一部" if group_id.startswith("mainline") else "往世乐土",
        chapter=chapter,
        scene=f"核验场景{index}",
        source_url=f"https://www.bh3text.com/dialog/{path_group}/{group_id}/scene-{index}",
        dialogue_turns=turns,
        character_names=["芽衣", other, *(["爱莉希雅"] if involves_elysia else [])],
        topic_names=["英桀", "记忆体"],
        content_hash=content_hash(rendered),
        retrieved_at="2026-08-22T00:00:00+00:00",
    )


def _group_candidate(group_id: str, index: int, score: int = 10) -> BH3TextCandidateAudit:
    document = _group_document(group_id, index)
    return BH3TextCandidateAudit(
        url=document.source_url,
        arc=document.arc,
        chapter=document.chapter,
        scene=document.scene,
        title=document.title,
        matched_characters=document.character_names,
        matched_topics=document.topic_names,
        priority_score=score,
        decision="include",
        reason="合成的分组配额测试候选，不执行网络请求",
    )


def test_coverage_gap_quotas_prevent_mainline_31_starvation_and_cap_new_pages(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    groups = load_bh3text_collection_groups(paths.bh3text_collection_groups)
    existing_counts = {
        "elysian_realm_1": 65,
        "elysian_realm_2": 23,
        "elysian_realm_3": 10,
        "mainline_29": 1,
        "mainline_30": 1,
        "mainline_31": 0,
    }
    existing = [
        _group_document(group_id, index)
        for group_id, count in existing_counts.items()
        for index in range(count)
    ]
    candidates = [
        _group_candidate(group_id, 100 + index, score=10_000 if group_id == "elysian_realm_1" else 1)
        for group_id in _GROUP_CHAPTERS
        for index in range(30)
    ]
    selected = select_coverage_gap_candidates(
        candidates,
        existing,
        groups,
        max_new_pages=40,
    )
    selected_counts = {
        group_id: sum(row.chapter == chapter for row in selected)
        for group_id, chapter in _GROUP_CHAPTERS.items()
    }
    assert len(selected) == 38
    assert len(selected) <= 40
    assert selected_counts == {
        "elysian_realm_1": 0,
        "elysian_realm_2": 0,
        "elysian_realm_3": 5,
        "mainline_29": 9,
        "mainline_30": 9,
        "mainline_31": 15,
    }
    assert all(row.chapter == _GROUP_CHAPTERS["mainline_31"] for row in selected[:15])
    assert not ({row.url for row in selected} & {row.source_url for row in existing})


def test_verification_sample_has_fixed_distribution_and_content_constraints(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    groups = load_bh3text_collection_groups(paths.bh3text_collection_groups)
    documents = [
        _group_document(group_id, index)
        for group_id in _GROUP_CHAPTERS
        for index in range(4)
    ]
    selected = select_verification_documents(documents, groups)
    distribution = {
        group_id: sum(row.chapter == chapter for row in selected)
        for group_id, chapter in _GROUP_CHAPTERS.items()
    }
    assert distribution == {
        "elysian_realm_1": 2,
        "elysian_realm_2": 1,
        "elysian_realm_3": 1,
        "mainline_29": 2,
        "mainline_30": 2,
        "mainline_31": 2,
    }
    assert sum("爱莉希雅" in "\n".join(turn.text for turn in row.dialogue_turns) or "爱莉希雅" in row.character_names for row in selected) >= 5
    assert sum(len({turn.speaker for turn in row.dialogue_turns if turn.speaker}) >= 2 for row in selected) >= 3
    assert sum(any(topic in {"英桀", "记忆体"} for topic in row.topic_names) for row in selected) >= 2
    assert len({name for row in selected for name in row.character_names}) > 1


def test_build_bh3text_never_auto_marks_verification_match(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    documents = [
        _group_document(group_id, index)
        for group_id, quota in {
            "elysian_realm_1": 2,
            "elysian_realm_2": 1,
            "elysian_realm_3": 1,
            "mainline_29": 2,
            "mainline_30": 2,
            "mainline_31": 2,
        }.items()
        for index in range(quota)
    ]
    write_jsonl(paths.bh3text_documents, [row.model_dump(mode="json") for row in documents])
    result = build_bh3text(paths)
    verification = read_jsonl(paths.bh3text_transcript_verification_jsonl)
    assert len(verification) == 10
    assert {row["verification_status"] for row in verification} == {"not_checked"}
    assert all(3 <= len(row["sample_turns"]) <= 5 for row in verification)
    assert all(row["source_tier"] == "Tier B-primary-transcript" for row in verification)
    assert all(row["scene_context"] for row in verification)
    assert all(row["character_names"] for row in verification)
    assert all(row["evidence_excerpt"] for row in verification)
    assert all(len(row["confirmation_items"]) == 5 for row in verification)
    assert result["vector_ready"] is False
    report = paths.bh3text_transcript_verification.read_text(encoding="utf-8")
    assert "minor_mismatch" in report
    assert "critical_mismatch" in report
    assert "绝不会自行填写 `match`" in report
    assert "场景上下文" in report
    assert "涉及角色" in report
    assert "证据片段（原顺序3～5轮）" in report
    assert "待确认项" in report


def test_critical_mismatch_blocks_otherwise_satisfied_vector_gate(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    documents = [
        _group_document("mainline_31", index) for index in range(8)
    ] + [_group_document("mainline_30", index) for index in range(2)]
    verification: list[BH3TextVerificationRecord] = []
    for index, document in enumerate(documents):
        status = "match" if index < 8 else ("minor_mismatch" if index == 8 else "critical_mismatch")
        verification.append(
            BH3TextVerificationRecord(
                verification_id=f"bh3verify_{index:03d}",
                document_id=document.document_id,
                title=document.title,
                arc=document.arc,
                chapter=document.chapter,
                source_url=document.source_url,
                sample_turns=document.dialogue_turns[:3],
                verification_status=status,
            )
        )
    write_jsonl(
        paths.bh3text_transcript_verification_jsonl,
        [row.model_dump(mode="json") for row in verification],
    )
    base_chunks = [chunk_bh3text_document(document)[0] for document in documents]
    chunks = [
        base_chunks[index % len(base_chunks)].model_copy(
            update={"chunk_id": f"bh3chunk_gate_{index:03d}"}
        )
        for index in range(120)
    ]
    readiness = build_vector_readiness(paths, documents, chunks)
    assert readiness["actual"] == {
        "reviewed_scenes": 10,
        "matches": 8,
        "critical_mismatches": 1,
        "mainline_31_documents": 8,
        "total_bh3text_chunks": 120,
        "all_chunks_have_source_url": True,
        "test_fixture_hits": 0,
    }
    assert readiness["conditions_met"]["maximum_critical_mismatches"] is False
    assert readiness["vector_ready"] is False


def test_user_bulk_accept_does_not_unlock_transcript_vector_gate(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    documents = [
        _group_document("mainline_31", index) for index in range(8)
    ] + [_group_document("mainline_30", index) for index in range(2)]
    verification = [
        BH3TextVerificationRecord(
            verification_id=f"bh3verify_bulk_{index:03d}",
            document_id=document.document_id,
            title=document.title,
            arc=document.arc,
            chapter=document.chapter,
            source_url=document.source_url,
            sample_turns=document.dialogue_turns[:3],
            verification_status="match",
            reviewer_note=(
                "User accepted the current packet without scene-by-scene comparison; "
                "review_method=user_bulk_accept; recheck_policy=review_on_issue"
            ),
        )
        for index, document in enumerate(documents)
    ]
    write_jsonl(
        paths.bh3text_transcript_verification_jsonl,
        [row.model_dump(mode="json") for row in verification],
    )
    base_chunks = [chunk_bh3text_document(document)[0] for document in documents]
    chunks = [
        base_chunks[index % len(base_chunks)].model_copy(
            update={"chunk_id": f"bh3chunk_bulk_gate_{index:03d}"}
        )
        for index in range(120)
    ]

    readiness = build_vector_readiness(paths, documents, chunks)

    assert readiness["actual"]["reviewed_scenes"] == 10
    assert readiness["actual"]["matches"] == 10
    assert readiness["bulk_accepted_scenes"] == 10
    assert readiness["manual_review_complete"] is True
    assert readiness["manual_transcript_comparison_complete"] is False
    assert (
        readiness["conditions_met"]["individual_transcript_comparison_complete"]
        is False
    )
    assert readiness["vector_ready"] is False


def test_bh3helper_content_cannot_enter_bh3text_chunks_or_fixture_hits(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    documents = [
        _group_document(group_id, index)
        for group_id in _GROUP_CHAPTERS
        for index in range(2)
    ]
    write_jsonl(paths.bh3text_documents, [row.model_dump(mode="json") for row in documents])
    write_jsonl(
        paths.bh3helper_navigation,
        [{"content": "SYNTHETIC_HELPER_DIALOGUE_MUST_STAY_ISOLATED"}],
    )
    build_bh3text(paths)
    chunks = read_jsonl(paths.bh3text_chunks)
    assert chunks
    assert all(
        row["source_url"].startswith("https://www.bh3text.com/dialog/") for row in chunks
    )
    assert all(
        "SYNTHETIC_HELPER_DIALOGUE_MUST_STAY_ISOLATED" not in row["content"]
        for row in chunks
    )
    readiness = json.loads(paths.vector_readiness.read_text(encoding="utf-8"))
    assert readiness["actual"]["test_fixture_hits"] == 0


def test_source_inventory_keeps_community_corpora_out_of_official_counts(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    official = _rag_chunk("爱莉希雅是逐火英桀成员。")
    document = _group_document("mainline_31", 1)
    transcript_chunks = chunk_bh3text_document(document)
    write_jsonl(paths.chunks, [official.model_dump(mode="json")])
    write_jsonl(paths.bh3text_documents, [document.model_dump(mode="json")])
    write_jsonl(
        paths.bh3text_chunks,
        [row.model_dump(mode="json") for row in transcript_chunks],
    )
    write_jsonl(
        paths.bh3helper_navigation,
        [{"navigation_id": "nav_001", "title": "第三十一章"}],
    )
    write_jsonl(
        paths.story_navigation_chunks,
        [
            {
                "chunk_id": "story_nav_chunk_001",
                "navigation_id": "nav_001",
                "title": "第三十一章",
                "content": "章节：第三十一章；用途限制：仅用于剧情导航。",
                "source_url": "https://bh3helper.xrysnow.xyz/pages/common.html?id=31",
                "source_type": "community_story_guide",
                "source_tier": "Tier B-curated-index",
                "review_status": "pending",
            }
        ],
    )
    write_json(
        paths.vector_readiness,
        {"actual": {"test_fixture_hits": 0}},
    )

    inventory = build_source_inventory(paths)

    assert inventory["official_document_count"] == 1
    assert inventory["community_documents_counted_as_official"] == 0
    assert inventory["corpora"]["bh3text_dialogue"]["official_documents"] == 0
    assert inventory["corpora"]["story_navigation"]["official_documents"] == 0
    assert inventory["development_prototype_gate"]["structurally_validated"] is True
    assert inventory["development_prototype_gate"]["production_enabled"] is False
    report = paths.deduplication_report.read_text(encoding="utf-8")
    assert document.dialogue_turns[0].text not in report
    assert "社区文档计入official文档数：0" in report


def test_bh3text_integrity_normalizes_safe_topics_and_url_chapter() -> None:
    document = _bh3text_document().model_copy(
        update={
            "arc": "错误篇章",
            "chapter": "错误章节",
            "source_url": "https://www.bh3text.com/dialog/mainline/1/31/31-12-1",
            "topic_names": ["黄金庭园", "约束的惨剧"],
        }
    )
    normalized, repairs = normalize_bh3text_metadata([document])
    assert normalized[0].arc == "主线第一部"
    assert normalized[0].chapter == "第三十一章 因你而在的故事"
    assert normalized[0].topic_names == ["约束惨剧", "黄金庭院"]
    assert repairs == {"chapter_attribution": 1, "topic_surface_normalization": 1}
    assert normalized[0].source_tier == "Tier B-primary-transcript"
    assert normalized[0].review_status == "unverified_transcript"


def test_integrity_audit_never_merges_semantic_aliases(tmp_path: Path) -> None:
    document = _bh3text_document().model_copy(
        update={
            "character_names": ["爱莉希雅", "樱"],
            "topic_names": ["人之律者"],
        }
    )
    payload = build_lore_integrity_audit(
        [document],
        chunk_bh3text_document(document),
        repairs={},
        json_path=tmp_path / "integrity.json",
        markdown_path=tmp_path / "integrity.md",
    )
    assert payload["aliases"]["semantic_aliases_auto_merged"] == 0
    assert all(
        row["status"] == "blocked_human"
        for row in payload["aliases"]["semantic_alias_candidates"]
    )
    assert payload["source_tier_guard"] == {
        "bh3text_official_documents": 0,
        "confirmed_relations_generated": 0,
    }
    assert "语义别名和人格称谓均未自动合并" in (tmp_path / "integrity.md").read_text(encoding="utf-8")
