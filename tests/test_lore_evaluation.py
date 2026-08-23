from __future__ import annotations

import json

from src.lore.corpus import is_safe_source_url
from src.lore.evaluation import load_cases, validate_case_distribution
from src.lore.models import LoreAugmentation, LoreCitation, LoreSearchResult
from src.lore.review import build_retrieval_match_review


def test_fixed_lore_eval_set_has_required_40_case_distribution() -> None:
    cases = load_cases()
    assert len(cases) == 40
    assert validate_case_distribution(cases) == {
        "身份与别名": 6,
        "英桀与组织": 6,
        "人物互动与关系": 8,
        "往世乐土时间线": 6,
        "主线29—31章": 6,
        "观看顺序与资料导航": 3,
        "资料缺失/应拒答": 3,
        "提示注入与来源冲突": 2,
    }


def test_lore_eval_gold_sources_are_traceable_and_fixture_free() -> None:
    cases = load_cases()
    assert all(
        is_safe_source_url(url)
        for case in cases
        for url in case.gold_source_urls
    )
    assert all(
        not any(
            marker in f"{case.case_id}\n{case.question}\n{' '.join(case.gold_source_urls)}".lower()
            for marker in ("fixture", "synthetic", "example.invalid")
        )
        for case in cases
    )
    assert all(not case.gold_source_urls for case in cases if case.should_abstain)


def test_lore_runtime_indexes_and_detailed_results_are_gitignored() -> None:
    ignore = open(".gitignore", encoding="utf-8").read()
    assert "data/lore_index/" in ignore
    assert "evals/lore_rag_results.jsonl" in ignore


def test_eight_relationship_cases_have_expected_answers() -> None:
    cases = [case for case in load_cases() if case.category == "人物互动与关系"]
    assert len(cases) == 8
    assert all(case.expected_answer for case in cases)


def test_retrieval_match_review_keeps_human_fields_not_checked(tmp_path) -> None:
    class FakeLoreRAG:
        def retrieve(self, query: str) -> LoreAugmentation:
            result = LoreSearchResult(
                chunk_id="chunk-001",
                content="短摘要",
                score=1.0,
                source_url="https://www.bh3text.com/dialog/not-the-gold-page",
                source_type="community_game_text_archive",
                source_tier="Tier B-primary-transcript",
                title="候选场景",
                corpus="bh3text_dialogue",
                review_status="unverified_transcript",
            )
            citation = LoreCitation(
                title=result.title,
                source_url=result.source_url,
                source_tier=result.source_tier,
                corpus=result.corpus,
                review_status=result.review_status,
            )
            return LoreAugmentation(
                query=query,
                route="dialogue",
                backend="hybrid",
                context="context",
                results=(result,),
                citations=(citation,),
                enabled=True,
            )

    jsonl_path = tmp_path / "review.jsonl"
    markdown_path = tmp_path / "review.md"
    summary = build_retrieval_match_review(
        FakeLoreRAG(),  # type: ignore[arg-type]
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )
    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert summary["review_cases"] == 8
    assert len(rows) == 8
    assert all(row["review_status"] == "not_checked" for row in rows)
    assert all(row["citation_completeness"]["reviewer_status"] == "not_checked" for row in rows)
    assert all(row["top_5"][0]["reviewer_relevance"] == "not_checked" for row in rows)
    assert all(row["automatic_error_reason"] == "gold_source_not_in_top_5" for row in rows)
    report = markdown_path.read_text(encoding="utf-8")
    assert "Query" in report
    assert "预期答案" in report
    assert "Source tier" in report
    assert "Human relevance" in report


def test_retrieval_match_review_preserves_bulk_accept_without_scores(tmp_path) -> None:
    class FakeLoreRAG:
        chunk_id = "chunk-001"

        def retrieve(self, query: str) -> LoreAugmentation:
            result = LoreSearchResult(
                chunk_id=self.chunk_id,
                content="短摘要",
                score=1.0,
                source_url="https://www.bh3text.com/dialog/not-the-gold-page",
                source_type="community_game_text_archive",
                source_tier="Tier B-primary-transcript",
                title="候选场景",
                corpus="bh3text_dialogue",
                review_status="unverified_transcript",
            )
            citation = LoreCitation(
                title=result.title,
                source_url=result.source_url,
                source_tier=result.source_tier,
                corpus=result.corpus,
                review_status=result.review_status,
            )
            return LoreAugmentation(
                query=query,
                route="dialogue",
                backend="hybrid",
                context="context",
                results=(result,),
                citations=(citation,),
                enabled=True,
            )

    jsonl_path = tmp_path / "review.jsonl"
    markdown_path = tmp_path / "review.md"
    service = FakeLoreRAG()
    build_retrieval_match_review(
        service,  # type: ignore[arg-type]
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )
    rows = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["review_status"] = "user_bulk_accepted"
    rows[0]["reviewer_error_reason"] = (
        "review_method=user_bulk_accept; recheck_policy=review_on_issue"
    )
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    summary = build_retrieval_match_review(
        service,  # type: ignore[arg-type]
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )
    rebuilt = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]

    assert rebuilt[0]["review_status"] == "user_bulk_accepted"
    assert rebuilt[0]["reviewer_error_reason"].startswith(
        "review_method=user_bulk_accept"
    )
    assert rebuilt[0]["top_5"][0]["reviewer_relevance"] == "not_checked"
    assert rebuilt[0]["citation_completeness"]["reviewer_status"] == "not_checked"
    assert summary["user_bulk_accepted"] == 1
    assert summary["individually_scored_results"] == 0

    service.chunk_id = "chunk-002"
    changed_summary = build_retrieval_match_review(
        service,  # type: ignore[arg-type]
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )
    changed = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert changed[0]["review_status"] == "not_checked"
    assert changed[0]["reviewer_error_reason"] == ""
    assert changed_summary["user_bulk_accepted"] == 0
