"""Build human review workbenches from deterministic lore retrieval results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.lore.corpus import is_safe_source_url
from src.lore.evaluation import DEFAULT_CASES, LoreEvalCase, load_cases
from src.lore.service import LoreRAG


DEFAULT_MATCH_REVIEW_JSONL = (
    PROJECT_ROOT / "data" / "review" / "lore_retrieval_match_review.jsonl"
)
DEFAULT_MATCH_REVIEW_MARKDOWN = (
    PROJECT_ROOT / "data" / "review" / "lore_retrieval_match_review.md"
)
MATCH_REVIEW_CATEGORY = "人物互动与关系"


def _automatic_error_reason(
    case: LoreEvalCase,
    retrieved_urls: list[str],
    retrieved_tiers: list[str],
    citations_complete: bool,
) -> str:
    gold = set(case.gold_source_urls)
    hit_ranks = [
        rank for rank, url in enumerate(retrieved_urls, 1) if url in gold
    ]
    reasons: list[str] = []
    if not retrieved_urls:
        reasons.append("no_results")
    elif not hit_ranks:
        reasons.append("gold_source_not_in_top_5")
    elif hit_ranks[0] > 1:
        reasons.append(f"gold_source_below_rank_1:rank_{hit_ranks[0]}")
    if retrieved_tiers and retrieved_tiers[0] != case.expected_source_tier:
        reasons.append("top_1_source_tier_mismatch")
    if not citations_complete:
        reasons.append("citation_incomplete_or_unsafe")
    return ";".join(reasons)


def _review_row(
    case: LoreEvalCase,
    service: LoreRAG,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous or {}
    result = service.retrieve(case.question)
    citation_urls = {citation.source_url for citation in result.citations}
    top_five = list(result.results[:5])
    citations_complete = bool(top_five) and all(
        row.source_url in citation_urls and is_safe_source_url(row.source_url)
        for row in top_five
    )
    retrieved_urls = [row.source_url for row in top_five]
    retrieved_tiers = [row.source_tier for row in top_five]
    gold = set(case.gold_source_urls)
    previous_top_fingerprint = [
        (
            str(row.get("chunk_id", "")),
            str(row.get("source_url", "")),
            str(row.get("source_tier", "")),
        )
        for row in previous.get("top_5", [])
        if isinstance(row, dict)
    ]
    current_top_fingerprint = [
        (row.chunk_id, row.source_url, row.source_tier) for row in top_five
    ]
    previous_result_set_unchanged = (
        bool(previous_top_fingerprint)
        and previous_top_fingerprint == current_top_fingerprint
    )
    previous_results = {
        str(row.get("chunk_id", "")): row
        for row in previous.get("top_5", [])
        if isinstance(row, dict)
    }
    previous_citation = (
        previous.get("citation_completeness", {})
        if previous_result_set_unchanged
        else {}
    )
    if not isinstance(previous_citation, dict):
        previous_citation = {}
    return {
        "review_id": f"retrieval-review-{case.case_id.lower()}",
        "case_id": case.case_id,
        "query": case.question,
        "expected_answer": case.expected_answer,
        "expected_source_tier": case.expected_source_tier,
        "gold_source_urls": list(case.gold_source_urls),
        "route": result.route,
        "backend": result.backend,
        "top_5": [
            {
                "rank": rank,
                "chunk_id": row.chunk_id,
                "title": row.title,
                "source_url": row.source_url,
                "source_tier": row.source_tier,
                "corpus": row.corpus,
                "review_status": row.review_status,
                "automatic_relevance": (
                    "gold_source_match" if row.source_url in gold else "not_in_gold_set"
                ),
                "reviewer_relevance": str(
                    previous_results.get(row.chunk_id, {}).get(
                        "reviewer_relevance", "not_checked"
                    )
                ),
                "citation_present": row.source_url in citation_urls,
            }
            for rank, row in enumerate(top_five, 1)
        ],
        "citation_completeness": {
            "automatic_complete": citations_complete,
            "reviewer_status": str(
                previous_citation.get("reviewer_status", "not_checked")
            ),
        },
        "automatic_error_reason": _automatic_error_reason(
            case,
            retrieved_urls,
            retrieved_tiers,
            citations_complete,
        ),
        "reviewer_error_reason": str(
            previous.get("reviewer_error_reason", "")
            if previous_result_set_unchanged
            else ""
        ),
        "review_status": str(
            previous.get("review_status", "not_checked")
            if previous_result_set_unchanged
            else "not_checked"
        ),
    }


def _escape_table(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Lore Retrieval Match Review",
        "",
        "> 本表记录自动检索结果与gold URL对照，不代表人工相关性判断或剧情事实确认。",
        "> 新生成项的人工字段默认保持 `not_checked`；Top 5身份与顺序未变化时，已有用户决定会从JSONL保留。",
        "> 如果重建后的Top 5发生变化，总体接受状态与备注会重置为待审核，避免把旧决定套到新结果上。",
        "> `user_bulk_accepted` 只表示用户整体接受当前Top 5与排序，不会伪造逐结果相关性评分，也不会消除自动风险提示。",
        "",
    ]
    for index, row in enumerate(rows, 1):
        citation = row["citation_completeness"]
        lines.extend(
            [
                f"## {index}. {row['case_id']}",
                "",
                f"- Query：{row['query']}",
                f"- 预期答案：{row['expected_answer']}",
                f"- 预期来源等级：{row['expected_source_tier']}",
                f"- 路由/后端：{row['route']} / {row['backend']}",
                f"- 引用完整性（自动）：{citation['automatic_complete']}",
                f"- 引用完整性（人工）：{citation['reviewer_status']}",
                f"- 自动错误原因：{row['automatic_error_reason'] or 'none'}",
                f"- 人工备注/保留风险：{row['reviewer_error_reason'] or '待填写'}",
                f"- 总审核状态：{row['review_status']}",
                "",
                "| Rank | Title | Source tier | Gold URL match | Citation | Human relevance | URL |",
                "|---:|---|---|---|---|---|---|",
            ]
        )
        for result in row["top_5"]:
            lines.append(
                f"| {result['rank']} | {_escape_table(result['title'])} | "
                f"{result['source_tier']} | {result['automatic_relevance']} | "
                f"{result['citation_present']} | {result['reviewer_relevance']} | "
                f"{result['source_url']} |"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_retrieval_match_review(
    service: LoreRAG,
    *,
    cases_path: Path = DEFAULT_CASES,
    jsonl_path: Path = DEFAULT_MATCH_REVIEW_JSONL,
    markdown_path: Path = DEFAULT_MATCH_REVIEW_MARKDOWN,
) -> dict[str, Any]:
    cases = [
        case for case in load_cases(cases_path) if case.category == MATCH_REVIEW_CATEGORY
    ]
    if len(cases) != 8 or any(not case.expected_answer for case in cases):
        raise ValueError("retrieval match review requires 8 cases with expected answers")
    previous_rows: dict[str, dict[str, Any]] = {}
    if jsonl_path.exists():
        previous_rows = {
            str(row.get("case_id", "")): row
            for line in jsonl_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
            for row in [json.loads(line)]
            if isinstance(row, dict)
        }
    rows = [
        _review_row(case, service, previous_rows.get(case.case_id))
        for case in cases
    ]
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    _write_markdown(markdown_path, rows)
    return {
        "review_cases": len(rows),
        "review_status": (
            rows[0]["review_status"]
            if rows and len({row["review_status"] for row in rows}) == 1
            else "mixed"
        ),
        "user_bulk_accepted": sum(
            row["review_status"] == "user_bulk_accepted" for row in rows
        ),
        "individually_scored_results": sum(
            item["reviewer_relevance"] != "not_checked"
            for row in rows
            for item in row["top_5"]
        ),
        "automatic_gold_hits_at_5": sum(
            any(item["automatic_relevance"] == "gold_source_match" for item in row["top_5"])
            for row in rows
        ),
        "automatic_citation_complete": sum(
            bool(row["citation_completeness"]["automatic_complete"]) for row in rows
        ),
        "automatic_error_cases": sum(bool(row["automatic_error_reason"]) for row in rows),
    }
