"""Configuration for the public official-lore collection pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_USER_AGENT = (
    "ElysiaLoreResearchBot/1.0 "
    "(fan-made non-commercial research; low-rate public-page collector)"
)

ALLOWED_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "www.bh3.com": (
        "/valkyries",
        "/content/",
        "/information/",
        "/news/",
    ),
    "bh3.com": (
        "/valkyries",
        "/content/",
        "/information/",
        "/news/",
    ),
    "baike.mihoyo.com": (
        "/bh3",
        "/bh3/wiki/channel/map/",
        "/bh3/wiki/content/",
    ),
    "comic.bh3.com": ("/book",),
}

BLOCKED_PATH_PARTS = (
    "/api/",
    "/bbs/",
    "/login",
    "/passport/",
    "/user/",
)

SCOPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "elysia": (
        "爱莉希雅",
        "Elysia",
        "逐火十三英桀",
        "十三英桀",
        "逐火之蛾",
        "前文明",
        "往世乐土",
        "人之律者",
        "始源之律者",
        "英桀",
        "伊甸",
        "凯文",
        "阿波尼亚",
        "维尔薇",
        "千劫",
        "苏",
        "樱",
        "梅比乌斯",
        "华",
        "科斯魔",
        "梅",
        "格蕾修",
        "帕朵菲莉丝",
        "融合战士",
        "记忆体",
        "侵蚀之律者",
        "永世乐土",
        "梅博士",
        "约束惨剧",
        "终焉",
    )
}

CORE_CHARACTERS = (
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

CORE_CONCEPTS = (
    "逐火十三英桀",
    "逐火之蛾",
    "往世乐土",
    "前文明",
    "融合战士",
    "记忆体",
    "英桀",
    "人之律者",
    "始源之律者",
    "侵蚀之律者",
    "永世乐土",
    "梅博士",
    "约束惨剧",
    "终焉",
)

HIGH_PRIORITY_CONCEPTS = ("逐火十三英桀", "往世乐土", "前文明", "逐火之蛾")

LORE_MARKERS = (
    "剧情",
    "档案",
    "角色设定",
    "组织设定",
    "人物设定",
    "背景",
    "故事",
    "经历",
    "传记",
    "简介",
    "身份",
    "组织",
)

GAMEPLAY_MARKERS = (
    "配装",
    "武器",
    "圣痕",
    "补给",
    "抽卡",
    "攻略",
    "阵容",
    "数值",
    "技能",
    "伤害类型",
    "怪物信息",
    "怪物名称",
    "怪物属性",
    "怪物类型",
    "威胁等级",
    "特殊机制",
    "记忆战场",
    "超弦空间",
)

HARD_GAMEPLAY_MARKERS = (
    "怪物信息",
    "材料描述",
    "圣痕技能",
    "武器技能",
    "消耗途径",
    "获取途径",
    "获取方式",
    "补给详情",
)

NEWS_PROMO_MARKERS = (
    "补给",
    "装备推荐",
    "圣痕推荐",
    "跃升",
    "服装补给",
    "概率公示",
    "签到",
    "充值",
    "礼包",
    "技能倍率",
)


@dataclass(frozen=True)
class RelevanceScoringConfig:
    """Editable, explainable local relevance weights; no model calls."""

    title_elysia: int = 10
    title_high_priority_concept: int = 8
    title_core_character: int = 6
    summary_multiple_keywords: int = 4
    lore_category: int = 4
    gameplay_category: int = -8
    navigation_page: int = -10
    insufficient_content: int = -10
    include_threshold: int = 6
    minimum_chinese_chars: int = 200
    summary_keyword_threshold: int = 2


@dataclass(frozen=True)
class PipelinePaths:
    """All pipeline paths are local to the repository by default."""

    root: Path = PROJECT_ROOT
    source_registry: Path = PROJECT_ROOT / "data" / "config" / "source_registry.yaml"
    seeds: Path = PROJECT_ROOT / "data" / "seeds" / "elysia_official_urls.txt"
    raw_documents: Path = PROJECT_ROOT / "data" / "raw" / "official_pages.jsonl"
    cleaned_documents: Path = PROJECT_ROOT / "data" / "cleaned" / "official_pages.jsonl"
    chunks: Path = PROJECT_ROOT / "data" / "chunks" / "elysia_lore_chunks.jsonl"
    markdown_dir: Path = PROJECT_ROOT / "data" / "chunks" / "elysia_lore_markdown"
    entities: Path = PROJECT_ROOT / "data" / "entities" / "entities_pending.jsonl"
    relations_pending: Path = (
        PROJECT_ROOT / "data" / "relations" / "relations_pending.jsonl"
    )
    relations_confirmed: Path = (
        PROJECT_ROOT / "data" / "relations" / "relations_confirmed.jsonl"
    )
    manifest: Path = PROJECT_ROOT / "data" / "manifests" / "crawl_manifest.json"
    candidate_audit_jsonl: Path = (
        PROJECT_ROOT / "data" / "manifests" / "elysia_candidate_audit.jsonl"
    )
    candidate_audit_markdown: Path = (
        PROJECT_ROOT / "data" / "manifests" / "elysia_candidate_audit.md"
    )
    quality_report: Path = (
        PROJECT_ROOT / "data" / "manifests" / "data_quality_report.md"
    )
    discovery_report: Path = (
        PROJECT_ROOT / "data" / "manifests" / "discovery_report.json"
    )
    comic_metadata: Path = (
        PROJECT_ROOT / "data" / "manifests" / "official_comics.jsonl"
    )
    character_profiles: Path = (
        PROJECT_ROOT / "data" / "manifests" / "official_character_profiles.jsonl"
    )
    coverage_json: Path = (
        PROJECT_ROOT / "data" / "manifests" / "lore_coverage_matrix.json"
    )
    coverage_markdown: Path = (
        PROJECT_ROOT / "data" / "manifests" / "lore_coverage_matrix.md"
    )
    manual_source_gap: Path = (
        PROJECT_ROOT / "data" / "manifests" / "manual_source_gap.md"
    )
    source_inventory: Path = (
        PROJECT_ROOT / "data" / "manifests" / "source_inventory.json"
    )
    deduplication_report: Path = (
        PROJECT_ROOT / "data" / "manifests" / "deduplication_report.md"
    )
    manual_templates_dir: Path = PROJECT_ROOT / "data" / "manual_official" / "templates"
    manual_inbox_dir: Path = PROJECT_ROOT / "data" / "manual_official" / "inbox"
    manual_accepted_dir: Path = PROJECT_ROOT / "data" / "manual_official" / "accepted"
    manual_pending_index: Path = (
        PROJECT_ROOT / "data" / "manual_official" / "manual_pending.jsonl"
    )
    manual_review: Path = PROJECT_ROOT / "data" / "review" / "manual_review.md"
    entities_review: Path = PROJECT_ROOT / "data" / "review" / "entities_review.md"
    relations_review: Path = PROJECT_ROOT / "data" / "review" / "relations_review.md"
    relation_conflicts: Path = (
        PROJECT_ROOT / "data" / "review" / "relation_conflicts.md"
    )
    bilibili_official_accounts: Path = (
        PROJECT_ROOT / "data" / "config" / "bilibili_official_accounts.yaml"
    )
    video_seed_file: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "bilibili_seeds.txt"
    )
    video_metadata_dir: Path = PROJECT_ROOT / "data" / "video_sources" / "metadata"
    video_subtitles_raw_dir: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "subtitles_raw"
    )
    video_subtitles_cleaned_dir: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "subtitles_cleaned"
    )
    video_chunks: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "chunks" / "video_chunks.jsonl"
    )
    video_manual_inbox_dir: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "manual_inbox"
    )
    video_audit_jsonl: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "review" / "bilibili_source_audit.jsonl"
    )
    video_audit_markdown: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "review" / "bilibili_source_audit.md"
    )
    video_subtitle_review: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "review" / "subtitle_review.md"
    )
    video_fact_review: Path = (
        PROJECT_ROOT / "data" / "video_sources" / "review" / "video_fact_review.md"
    )
    bh3text_candidate_audit_jsonl: Path = (
        PROJECT_ROOT / "data" / "manifests" / "bh3text_candidate_audit.jsonl"
    )
    bh3text_candidate_audit_markdown: Path = (
        PROJECT_ROOT / "data" / "manifests" / "bh3text_candidate_audit.md"
    )
    bh3text_collection_groups: Path = (
        PROJECT_ROOT / "data" / "config" / "bh3text_collection_groups.yaml"
    )
    bh3text_group_coverage_before: Path = (
        PROJECT_ROOT / "data" / "manifests" / "bh3text_group_coverage_before.json"
    )
    bh3text_group_coverage_after: Path = (
        PROJECT_ROOT / "data" / "manifests" / "bh3text_group_coverage_after.json"
    )
    bh3text_manifest: Path = (
        PROJECT_ROOT / "data" / "manifests" / "bh3text_crawl_manifest.json"
    )
    bh3text_raw_documents: Path = (
        PROJECT_ROOT / "data" / "raw" / "bh3text_pages.jsonl"
    )
    bh3text_documents: Path = (
        PROJECT_ROOT / "data" / "cleaned" / "bh3text_dialogues.jsonl"
    )
    bh3text_chunks: Path = (
        PROJECT_ROOT / "data" / "chunks" / "bh3text_lore_chunks.jsonl"
    )
    dialogue_evidence_edges: Path = (
        PROJECT_ROOT / "data" / "relations" / "dialogue_evidence_edges.jsonl"
    )
    bh3text_relations_pending: Path = (
        PROJECT_ROOT / "data" / "relations" / "bh3text_relations_pending.jsonl"
    )
    bh3text_transcript_verification: Path = (
        PROJECT_ROOT / "data" / "review" / "bh3text_transcript_verification.md"
    )
    bh3text_transcript_verification_jsonl: Path = (
        PROJECT_ROOT / "data" / "review" / "bh3text_transcript_verification.jsonl"
    )
    vector_readiness: Path = (
        PROJECT_ROOT / "data" / "manifests" / "vector_readiness.json"
    )
    story_guide_dir: Path = PROJECT_ROOT / "data" / "story_guide"
    bh3helper_navigation: Path = story_guide_dir / "bh3helper_navigation.jsonl"
    bh3helper_official_links: Path = story_guide_dir / "bh3helper_official_links.jsonl"
    bh3helper_archive_candidates: Path = story_guide_dir / "bh3helper_archive_candidates.jsonl"
    bh3helper_annotations: Path = story_guide_dir / "bh3helper_annotations.jsonl"
    bh3helper_duplicate_map: Path = story_guide_dir / "bh3helper_duplicate_map.jsonl"
    source_link_graph: Path = story_guide_dir / "source_link_graph.jsonl"
    story_navigation_chunks: Path = story_guide_dir / "story_navigation_chunks.jsonl"
    bh3helper_manifest: Path = (
        PROJECT_ROOT / "data" / "manifests" / "bh3helper_discovery_report.json"
    )
    log: Path = PROJECT_ROOT / "data" / "logs" / "data_pipeline.log"

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.raw_documents.parent,
            self.cleaned_documents.parent,
            self.chunks.parent,
            self.markdown_dir,
            self.entities.parent,
            self.relations_pending.parent,
            self.manifest.parent,
            self.candidate_audit_jsonl.parent,
            self.quality_report.parent,
            self.source_registry.parent,
            self.manual_templates_dir,
            self.manual_inbox_dir,
            self.manual_accepted_dir,
            self.manual_pending_index.parent,
            self.manual_review.parent,
            self.video_seed_file.parent,
            self.video_metadata_dir,
            self.video_subtitles_raw_dir,
            self.video_subtitles_cleaned_dir,
            self.video_chunks.parent,
            self.video_manual_inbox_dir,
            self.video_audit_jsonl.parent,
            self.bh3text_candidate_audit_jsonl.parent,
            self.bh3text_collection_groups.parent,
            self.bh3text_raw_documents.parent,
            self.bh3text_documents.parent,
            self.bh3text_chunks.parent,
            self.dialogue_evidence_edges.parent,
            self.bh3text_transcript_verification.parent,
            self.story_guide_dir,
            self.log.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class CrawlSettings:
    """Conservative defaults for public official pages."""

    scope: str = "elysia"
    max_pages: int = 30
    delay_seconds: float = 3.0
    concurrency: int = 1
    timeout_seconds: float = 20.0
    max_retries: int = 2
    user_agent: str = DEFAULT_USER_AGENT
    render_dynamic: bool = True
    max_response_bytes: int = 5_000_000
    allowed_path_prefixes: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(ALLOWED_PATH_PREFIXES)
    )

    def validate(self) -> None:
        if self.scope not in SCOPE_KEYWORDS:
            raise ValueError(f"Unsupported scope: {self.scope}")
        if self.max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        if self.concurrency != 1:
            raise ValueError(
                "The official-lore pipeline intentionally supports concurrency=1 only"
            )
        if self.max_retries < 0 or self.max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
