from __future__ import annotations

from src.lore.corpus import is_safe_source_url
from src.lore.evaluation import load_cases, validate_case_distribution


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
