"""Pydantic schemas for persisted lore-pipeline data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EntityType = Literal["character", "faction", "location", "event", "concept", "chapter"]
RelationType = Literal[
    "MEMBER_OF",
    "ALLY_OF",
    "ENEMY_OF",
    "KNOWS",
    "CREATED_BY",
    "RELATED_TO",
    "ALIAS_OF",
    "APPEARS_IN",
    "PARTICIPATED_IN",
    "SIBLING_OF",
    "COMPANION_OF",
    "LEADS",
    "HOLDS_ROLE_IN",
]
ReviewStatus = Literal["pending", "confirmed", "rejected"]
ManualReviewStatus = Literal["pending", "accepted", "rejected"]
QualityStatus = Literal["accepted", "needs_review", "rejected"]
SourceTier = Literal[
    "A",
    "A-manual",
    "B",
    "B-recording",
    "Tier B-primary-transcript",
    "Tier B-curated-index",
    "C",
    "pending",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PageDocument(StrictModel):
    document_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    canonical_url: str = Field(pattern=r"^https?://")
    source_domain: str = Field(min_length=1)
    source_type: Literal["official_site", "official_wiki", "official_comic"]
    content: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    retrieved_at: datetime
    published_at: datetime | None = None
    language: Literal["zh-CN"] = "zh-CN"
    crawl_status: Literal["success"] = "success"


class CleanedDocument(PageDocument):
    chinese_char_count: int = Field(ge=0)
    navigation_noise_ratio: float = Field(ge=0.0, le=1.0)
    duplicate_paragraph_count: int = Field(ge=0)
    quality_status: QualityStatus
    quality_reasons: list[str] = Field(default_factory=list)


class LoreEntity(StrictModel):
    entity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    entity_type: EntityType
    era: list[str] = Field(default_factory=list)
    universe: list[str] = Field(default_factory=list)
    summary: str = ""
    source_urls: list[str] = Field(default_factory=list)
    mention_count: int = Field(default=0, ge=0)
    source_document_ids: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    is_core_entity: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    review_status: ReviewStatus = "pending"


class LoreRelation(StrictModel):
    relation_id: str = Field(min_length=8)
    source_entity: str = Field(min_length=1)
    relation: RelationType
    target_entity: str = Field(min_length=1)
    time_scope: str = ""
    universe: str = ""
    evidence: str = Field(min_length=2, max_length=300)
    source_url: str = Field(pattern=r"^(?:https?://|manual-official://)")
    confidence: float = Field(ge=0.0, le=1.0)
    review_status: ReviewStatus = "pending"

class ChunkMetadata(StrictModel):
    title: str
    source_url: str = Field(pattern=r"^(?:https?://|manual-official://)")
    source_type: str
    source_tier: SourceTier = "A"
    source_note: str = ""
    entity_names: list[str] = Field(default_factory=list)
    era: list[str] = Field(default_factory=list)
    universe: list[str] = Field(default_factory=list)
    retrieved_at: datetime
    document_id: str
    chunk_id: str


class RagChunk(StrictModel):
    chunk_id: str = Field(min_length=8)
    content: str = Field(min_length=1)
    metadata: ChunkMetadata


class CrawlRecord(StrictModel):
    url: str
    status: Literal[
        "success",
        "skipped",
        "robots_disallowed",
        "failed",
        "duplicate",
    ]
    reason: str = ""
    document_id: str = ""
    content_hash: str = ""
    recorded_at: datetime


class CandidateAuditRecord(StrictModel):
    url: str = Field(pattern=r"^https?://")
    title: str = Field(min_length=1)
    source_type: Literal["official_site", "official_wiki", "official_comic"]
    matched_keywords: list[str] = Field(default_factory=list)
    relevance_score: int
    decision: Literal["include", "exclude"]
    reason: str = Field(min_length=1)
    crawl_priority: int = Field(ge=1)
    score_breakdown: list[str] = Field(default_factory=list)
    metadata_status: Literal[
        "success", "insufficient_content", "robots_disallowed", "failed"
    ]
    page_category: Literal["lore", "mixed", "gameplay", "navigation", "unknown"]
    chinese_char_count: int = Field(ge=0)
    summary_excerpt: str = Field(default="", max_length=300)
    http_status: int | None = None
    final_url: str = ""
    diagnostic_note: str = ""
    audited_at: datetime


class SourceDefinition(StrictModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1)
    tier: SourceTier
    source_type: str = Field(min_length=1)
    base_urls: list[str] = Field(default_factory=list)
    discovery_urls: list[str] = Field(default_factory=list)
    enabled: bool = True
    automated_collection: bool = False
    rag_allowed: bool = False
    domain: str = ""
    content_origin: str = ""
    source_role: str = ""
    official_host: bool | None = None
    contains_curator_annotations: bool = False
    contains_official_outbound_links: bool = False
    can_enter_main_lore_rag: bool = False
    can_enter_navigation_index: bool = False
    direct_game_text_claimed: bool = False
    requires_sample_verification: bool = False
    can_enter_supplemental_rag: bool = False
    can_override_tier_a: bool = False
    can_generate_confirmed_relations: bool = False
    copyright_owner: str = ""
    content_policy: str = Field(min_length=1)


BH3HelperContentType = Literal[
    "mainline_chapter",
    "elysian_realm_arc",
    "archive_index",
    "story_guide",
    "unknown",
]
BH3HelperMaterialType = Literal[
    "official_website",
    "official_news",
    "official_comic",
    "official_animation",
    "official_video",
    "official_pv",
    "official_concert",
    "official_music",
    "unknown",
]
BH3HelperGraphRelation = Literal[
    "GUIDES_TO",
    "LINKS_TO",
    "SAME_CHAPTER_AS",
    "TRANSCRIPT_AVAILABLE_AT",
    "ARCHIVE_AVAILABLE_AT",
    "PRECEDES",
    "FOLLOWS",
    "POSSIBLE_DUPLICATE_OF",
]


class StoryNavigationRecord(StrictModel):
    navigation_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    content_type: BH3HelperContentType
    story_arc: str = ""
    chapter_number: str = ""
    update_version: str = ""
    update_date: str = ""
    estimated_duration: str = ""
    text_word_count: int | None = Field(default=None, ge=0)
    recommended_order: int | None = Field(default=None, ge=1)
    prerequisites: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    character_names: list[str] = Field(default_factory=list)
    topic_names: list[str] = Field(default_factory=list)
    source_url: str = Field(pattern=r"^https://bh3helper\.xrysnow\.xyz/")
    source_type: Literal["community_story_guide"] = "community_story_guide"
    source_tier: Literal["Tier B-curated-index"] = "Tier B-curated-index"
    content_classification: Literal["navigation_metadata"] = "navigation_metadata"
    review_status: Literal["pending"] = "pending"


class BH3HelperOfficialLink(StrictModel):
    link_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    target_domain: str = Field(min_length=1)
    material_type: BH3HelperMaterialType
    discovered_from: str = Field(pattern=r"^https://bh3helper\.xrysnow\.xyz/")
    content_classification: Literal["official_outbound_link"] = (
        "official_outbound_link"
    )
    official_status: Literal["unverified"] = "unverified"
    crawl_recommendation: Literal["review"] = "review"


class BH3HelperArchiveCandidate(StrictModel):
    candidate_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    archive_type: Literal[
        "character_archive",
        "flame_chaser_archive",
        "recollection",
        "collectible",
        "npc_text",
        "art_archive",
        "event_archive",
        "unknown_archive",
    ]
    source_url: str = Field(pattern=r"^https://bh3helper\.xrysnow\.xyz/")
    discovered_from: str = Field(pattern=r"^https://bh3helper\.xrysnow\.xyz/")
    character_names: list[str] = Field(default_factory=list)
    topic_names: list[str] = Field(default_factory=list)
    content_classification: Literal["game_archive_candidate"] = (
        "game_archive_candidate"
    )
    review_status: Literal["pending"] = "pending"


class BH3HelperAnnotation(StrictModel):
    annotation_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    annotation_type: Literal[
        "story_note", "operation_instruction", "viewing_advice", "content_notice", "curation_note"
    ]
    section: str = ""
    summary: str = Field(min_length=1, max_length=500)
    source_url: str = Field(pattern=r"^https://bh3helper\.xrysnow\.xyz/")
    content_classification: Literal["curator_annotation"] = "curator_annotation"
    official_fact_allowed: Literal[False] = False
    review_status: Literal["pending"] = "pending"


class BH3HelperDuplicateMap(StrictModel):
    mapping_id: str = Field(min_length=8)
    helper_navigation_id: str = Field(min_length=8)
    helper_title: str = Field(min_length=1)
    helper_url: str = Field(pattern=r"^https://bh3helper\.xrysnow\.xyz/")
    bh3text_node: str = Field(min_length=8)
    bh3text_title: str = Field(min_length=1)
    bh3text_url: str = Field(pattern=r"^https://www\.bh3text\.com/dialog/")
    match_basis: list[Literal["normalized_title", "chapter_number", "scene_name", "content_hash", "text_similarity", "official_url"]] = Field(min_length=1)
    similarity: float = Field(ge=0.0, le=1.0)
    content_classification: Literal["duplicate_dialogue_text"] = (
        "duplicate_dialogue_text"
    )
    review_status: Literal["pending"] = "pending"


class SourceLinkGraphEdge(StrictModel):
    edge_id: str = Field(min_length=8)
    source_node: str = Field(min_length=1)
    relation: BH3HelperGraphRelation
    target_node: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https?://")
    target_url: str = Field(pattern=r"^https?://")
    confidence: float = Field(ge=0.0, le=1.0)


class StoryNavigationChunk(StrictModel):
    chunk_id: str = Field(min_length=8)
    navigation_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=2000)
    source_url: str = Field(pattern=r"^https://bh3helper\.xrysnow\.xyz/")
    source_type: Literal["community_story_guide"] = "community_story_guide"
    source_tier: Literal["Tier B-curated-index"] = "Tier B-curated-index"
    index_name: Literal["story_navigation_index"] = "story_navigation_index"
    facts_and_relations_allowed: Literal[False] = False
    review_status: Literal["pending"] = "pending"


class ManualOfficialRecord(StrictModel):
    record_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", min_length=3)
    title: str = Field(min_length=1)
    source_type: Literal["official_game_manual"] = "official_game_manual"
    game_section: str = Field(min_length=1)
    chapter: str = ""
    character_names: list[str] = Field(default_factory=list)
    era: str = ""
    universe: str = ""
    summary: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    source_note: str = Field(min_length=1)
    captured_by: Literal["manual"] = "manual"
    review_status: ManualReviewStatus = "pending"


class OfficialComicMetadata(StrictModel):
    title: str = Field(min_length=1)
    chapter: str = ""
    summary: str = ""
    source_url: str = Field(pattern=r"^https?://")
    content_available: Literal[False] = False
    manual_review_required: Literal[True] = True


class OfficialCharacterProfile(StrictModel):
    character_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    introduction: str = Field(min_length=1)
    identity_description: str = ""
    source_url: str = Field(pattern=r"^https?://")
    source_type: Literal["official_site"] = "official_site"
    retrieved_at: datetime


class PotentialVideoSource(StrictModel):
    video_id: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    reason: str = Field(min_length=1)
    verification_status: Literal["not_verified"] = "not_verified"


class CoverageEvidenceLayer(StrictModel):
    direct_evidence_chunks: int = Field(ge=0)
    substantial_evidence_chunks: int = Field(ge=0)
    mention_only_chunks: int = Field(ge=0)
    distinct_documents: int = Field(ge=0)
    distinct_official_documents: int = Field(ge=0)
    dedicated_page_available: bool = False
    confirmed_entities: int = Field(ge=0)
    confirmed_relations: int = Field(ge=0)
    coverage_status: Literal["missing", "thin", "usable", "strong"]
    coverage_reason: str = Field(min_length=1)
    evidence_urls: list[str] = Field(default_factory=list)


class CoverageRecord(StrictModel):
    topic_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    topic_name: str = Field(min_length=1)
    topic_type: Literal["character", "organization", "concept"]
    official_documents: int = Field(ge=0)
    manual_official_documents: int = Field(ge=0)
    accepted_chunks: int = Field(ge=0)
    direct_evidence_chunks: int = Field(ge=0)
    substantial_evidence_chunks: int = Field(ge=0)
    mention_only_chunks: int = Field(ge=0)
    distinct_documents: int = Field(ge=0)
    distinct_official_documents: int = Field(ge=0)
    dedicated_page_available: bool = False
    confirmed_entities: int = Field(ge=0)
    confirmed_relations: int = Field(ge=0)
    coverage_status: Literal["missing", "thin", "usable", "strong"]
    coverage_reason: str = Field(min_length=1)
    evidence_urls: list[str] = Field(default_factory=list)
    potential_video_sources: list[PotentialVideoSource] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommended_source_action: str = Field(min_length=1)
    official_coverage: CoverageEvidenceLayer
    bh3text_transcript_coverage: CoverageEvidenceLayer
    combined_coverage: CoverageEvidenceLayer


BH3TextDecision = Literal["include", "exclude"]
BH3TextReviewStatus = Literal["unverified_transcript", "sampled_verified"]
BH3TextSemanticRelation = Literal[
    "MEMBER_OF",
    "ALLY_OF",
    "ENEMY_OF",
    "KNOWS",
    "CREATED_BY",
    "RELATED_TO",
    "ALIAS_OF",
    "PARTICIPATED_IN",
    "TRUSTS",
    "FRIEND_OF",
    "LEADER_OF",
]


class BH3TextCandidateAudit(StrictModel):
    url: str = Field(pattern=r"^https://www\.bh3text\.com/dialog/")
    arc: str = Field(min_length=1)
    chapter: str = ""
    scene: str = Field(min_length=1)
    title: str = Field(min_length=1)
    matched_characters: list[str] = Field(default_factory=list)
    matched_topics: list[str] = Field(default_factory=list)
    priority_score: int
    decision: BH3TextDecision
    reason: str = Field(min_length=1)


class DialogueTurn(StrictModel):
    turn_index: int = Field(ge=1)
    speaker: str | None = None
    text: str = Field(min_length=1)
    turn_type: Literal["dialogue", "narration"]

    @model_validator(mode="after")
    def validate_speaker(self) -> "DialogueTurn":
        if self.turn_type == "narration" and self.speaker is not None:
            raise ValueError("Narration cannot have a speaker")
        if self.turn_type == "dialogue" and not self.speaker:
            raise ValueError("Dialogue requires an explicit speaker")
        return self


class BH3TextVerificationRecord(StrictModel):
    verification_id: str = Field(min_length=8)
    document_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    arc: str = Field(min_length=1)
    chapter: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://www\.bh3text\.com/dialog/")
    source_tier: Literal["Tier B-primary-transcript"] = (
        "Tier B-primary-transcript"
    )
    scene_context: str = ""
    character_names: list[str] = Field(default_factory=list)
    evidence_excerpt: str = ""
    confirmation_items: list[str] = Field(default_factory=list)
    video_id: str = ""
    suggested_video_part: str = ""
    video_timestamp: str = ""
    sample_turns: list[DialogueTurn] = Field(min_length=3, max_length=5)
    verification_status: Literal[
        "not_checked", "match", "minor_mismatch", "critical_mismatch"
    ] = "not_checked"
    mismatch_type: str = ""
    reviewer_note: str = ""


class BH3TextDocument(StrictModel):
    document_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    arc: str = Field(min_length=1)
    chapter: str = ""
    scene: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://www\.bh3text\.com/dialog/")
    source_type: Literal["community_game_text_archive"] = (
        "community_game_text_archive"
    )
    source_tier: Literal["Tier B-primary-transcript"] = (
        "Tier B-primary-transcript"
    )
    official_host: Literal[False] = False
    dialogue_turns: list[DialogueTurn] = Field(min_length=1)
    character_names: list[str] = Field(default_factory=list)
    topic_names: list[str] = Field(default_factory=list)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    retrieved_at: datetime
    review_status: BH3TextReviewStatus = "unverified_transcript"
    quality_status: Literal["accepted"] = "accepted"


class BH3TextChunk(StrictModel):
    chunk_id: str = Field(min_length=8)
    document_id: str = Field(min_length=8)
    title: str = Field(min_length=1)
    arc: str = Field(min_length=1)
    chapter: str = ""
    scene: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://www\.bh3text\.com/dialog/")
    source_type: Literal["community_game_text_archive"] = (
        "community_game_text_archive"
    )
    source_tier: Literal["Tier B-primary-transcript"] = (
        "Tier B-primary-transcript"
    )
    official_host: Literal[False] = False
    content: str = Field(min_length=1)
    turn_start: int = Field(ge=1)
    turn_end: int = Field(ge=1)
    dialogue_turns: list[DialogueTurn] = Field(min_length=1)
    speaker_names: list[str] = Field(default_factory=list)
    character_names: list[str] = Field(default_factory=list)
    topic_names: list[str] = Field(default_factory=list)
    review_status: BH3TextReviewStatus = "unverified_transcript"


class DialogueEvidenceEdge(StrictModel):
    edge_id: str = Field(min_length=8)
    source_entity: str = Field(min_length=1)
    relation: Literal["SPEAKS_TO", "SPEAKS_ABOUT", "APPEARS_WITH"]
    target_entity: str = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=300)
    arc: str = Field(min_length=1)
    chapter: str = ""
    scene: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://www\.bh3text\.com/dialog/")
    source_tier: Literal["Tier B-primary-transcript"] = (
        "Tier B-primary-transcript"
    )
    review_status: Literal["evidence_only"] = "evidence_only"


class BH3TextPendingRelation(StrictModel):
    relation_id: str = Field(min_length=8)
    source_entity: str = Field(min_length=1)
    relation: BH3TextSemanticRelation
    target_entity: str = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=300)
    speaker: str = Field(min_length=1)
    arc: str = Field(min_length=1)
    chapter: str = ""
    scene: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://www\.bh3text\.com/dialog/")
    source_tier: Literal["Tier B-primary-transcript"] = (
        "Tier B-primary-transcript"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    requires_official_corroboration: Literal[True] = True
    review_status: Literal["pending"] = "pending"


VideoContentType = Literal[
    "official_video",
    "official_game_recording",
    "community_lore_summary",
    "community_analysis",
    "fan_theory",
    "unknown_video",
]
VideoMetadataStatus = Literal[
    "success", "metadata_access_blocked", "failed"
]
VideoEvidenceType = Literal[
    "game_dialogue",
    "game_archive",
    "official_narration",
    "uploader_summary",
    "uploader_opinion",
    "fan_theory",
]


class VideoPart(StrictModel):
    part_number: int = Field(ge=1)
    title: str = ""
    duration_seconds: int | None = Field(default=None, ge=0)


class VideoSubtitleTrack(StrictModel):
    language_code: str = ""
    language_name: str = ""
    subtitle_type: str = "public_page"
    public_url: str = ""


class BilibiliVideoMetadata(StrictModel):
    video_id: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    canonical_url: str = Field(pattern=r"^https://www\.bilibili\.com/video/BV")
    title: str = ""
    uploader_name: str = ""
    uploader_id: str = ""
    published_at: datetime | None = None
    description: str = ""
    duration_seconds: int | None = Field(default=None, ge=0)
    parts: list[VideoPart] = Field(default_factory=list)
    observed_characters: list[str] = Field(default_factory=list)
    observed_topics: list[str] = Field(default_factory=list)
    subtitle_available: bool = False
    subtitle_tracks: list[VideoSubtitleTrack] = Field(default_factory=list)
    uploader_verified: bool = False
    official_identity_evidence: str = ""
    content_type: VideoContentType = "unknown_video"
    source_tier: SourceTier = "pending"
    review_status: ReviewStatus = "pending"
    metadata_status: VideoMetadataStatus = "success"
    failure_reason: str = ""
    public_access: bool = False
    inspection_method: str = "public_html_no_cookie"
    subtitle_access_note: str = ""
    diagnostic_note: str = ""
    requires_manual_review: Literal[True] = True
    inspected_at: datetime

    @model_validator(mode="after")
    def validate_source_classification(self) -> "BilibiliVideoMetadata":
        expected_tier = {
            "official_video": "A",
            "official_game_recording": "B-recording",
            "community_lore_summary": "B",
            "community_analysis": "C",
            "fan_theory": "C",
            "unknown_video": "pending",
        }[self.content_type]
        if self.source_tier != expected_tier:
            raise ValueError(
                f"{self.content_type} requires source_tier={expected_tier}"
            )
        if self.content_type == "official_video" and (
            not self.uploader_verified or not self.official_identity_evidence
        ):
            raise ValueError(
                "official_video requires verified uploader and identity evidence"
            )
        return self


class VideoSubtitleCue(StrictModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_time_range(self) -> "VideoSubtitleCue":
        if self.end_seconds < self.start_seconds:
            raise ValueError("Subtitle end_seconds cannot precede start_seconds")
        return self


class VideoSubtitleChunk(StrictModel):
    chunk_id: str = Field(min_length=8)
    video_id: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    title: str
    uploader_name: str
    source_tier: SourceTier
    content_type: VideoContentType
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    content: str = Field(min_length=1)
    character_names: list[str] = Field(default_factory=list)
    topic_names: list[str] = Field(default_factory=list)
    source_url: str = Field(pattern=r"^https://www\.bilibili\.com/video/BV")
    evidence_type: VideoEvidenceType | None = None
    source_note: str = Field(min_length=1)
    review_status: Literal["pending"] = "pending"


class VideoManualSegment(StrictModel):
    start_time: str = ""
    end_time: str = ""
    summary: str = ""
    evidence: str = ""
    evidence_type: VideoEvidenceType | None = None

    @field_validator("evidence_type", mode="before")
    @classmethod
    def empty_evidence_type_is_pending(cls, value: object) -> object:
        return None if value == "" else value


class VideoManualRecord(StrictModel):
    video_id: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    title: str = ""
    uploader_name: str = ""
    content_type: VideoContentType = "unknown_video"
    source_tier: SourceTier = "pending"
    topics: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    segments: list[VideoManualSegment] = Field(
        default_factory=lambda: [VideoManualSegment()]
    )
    review_status: Literal["pending"] = "pending"
    reviewer_note: str = ""

    @model_validator(mode="after")
    def validate_source_classification(self) -> "VideoManualRecord":
        expected_tier = {
            "official_video": "A",
            "official_game_recording": "B-recording",
            "community_lore_summary": "B",
            "community_analysis": "C",
            "fan_theory": "C",
            "unknown_video": "pending",
        }[self.content_type]
        if self.source_tier != expected_tier:
            raise ValueError(
                f"{self.content_type} requires source_tier={expected_tier}"
            )
        return self
