# -*- coding: utf-8 -*-
"""检索 Top-1 分数评测与 MIN_RETRIEVAL_SCORE 阈值扫描。"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from evaluation.retrieval_cases import RetrievalEvalCase, load_retrieval_cases


@dataclass
class QueryRetrievalResult:
    name: str
    query: str
    should_answer: bool
    top_score: Optional[float]
    top_title: str
    hit_count: int
    note: str = ""


@dataclass
class ThresholdRow:
    threshold: float
    false_reject_rate: float
    false_accept_rate: float
    precision_pass: float
    recall_pass: float
    false_reject_count: int
    false_accept_count: int
    should_answer_total: int
    should_reject_total: int


def evaluate_queries(
    cases: List[RetrievalEvalCase],
    search_fn: Callable[[str], List[Dict[str, Any]]],
) -> List[QueryRetrievalResult]:
    results: List[QueryRetrievalResult] = []
    for case in cases:
        try:
            hits = search_fn(case.query) or []
        except Exception as ex:
            results.append(QueryRetrievalResult(
                name=case.name,
                query=case.query,
                should_answer=case.should_answer,
                top_score=None,
                top_title="",
                hit_count=0,
                note=f"search_error: {ex}",
            ))
            continue

        top_score: Optional[float] = None
        top_title = ""
        for item in hits:
            if not isinstance(item, dict):
                continue
            score = float(item.get("score", 0) or 0)
            if top_score is None or score > top_score:
                top_score = score
                top_title = str(item.get("title", ""))

        results.append(QueryRetrievalResult(
            name=case.name,
            query=case.query,
            should_answer=case.should_answer,
            top_score=top_score,
            top_title=top_title,
            hit_count=len(hits),
            note=case.note,
        ))
    return results


def _gate_passes(top_score: Optional[float], threshold: float) -> bool:
    return top_score is not None and top_score >= threshold


def sweep_thresholds(
    query_results: List[QueryRetrievalResult],
    *,
    start: float = 0.30,
    end: float = 0.55,
    step: float = 0.05,
) -> List[ThresholdRow]:
    rows: List[ThresholdRow] = []
    should_answer = [r for r in query_results if r.should_answer]
    should_reject = [r for r in query_results if not r.should_answer]

    t = start
    while t <= end + 1e-9:
        false_reject = sum(
            1 for r in should_answer if not _gate_passes(r.top_score, t)
        )
        false_accept = sum(
            1 for r in should_reject if _gate_passes(r.top_score, t)
        )
        tp = sum(1 for r in should_answer if _gate_passes(r.top_score, t))
        fp = false_accept
        fn = false_reject
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        rows.append(ThresholdRow(
            threshold=round(t, 4),
            false_reject_rate=round(false_reject / len(should_answer), 4) if should_answer else 0.0,
            false_accept_rate=round(false_accept / len(should_reject), 4) if should_reject else 0.0,
            precision_pass=round(precision, 4),
            recall_pass=round(recall, 4),
            false_reject_count=false_reject,
            false_accept_count=false_accept,
            should_answer_total=len(should_answer),
            should_reject_total=len(should_reject),
        ))
        t = round(t + step, 4)
    return rows


def recommend_threshold(
    rows: List[ThresholdRow],
    *,
    max_false_accept_rate: float = 0.0,
) -> Dict[str, Any]:
    """优先压低误放行（应拒却放行），其次降低误拒答。"""
    if not rows:
        return {"threshold": 0.4, "reason": "无扫描数据，回退默认 0.4"}

    feasible = [r for r in rows if r.false_accept_rate <= max_false_accept_rate]
    if not feasible:
        strictest = max(rows, key=lambda r: r.threshold)
        return {
            "threshold": strictest.threshold,
            "reason": f"无法在 {max_false_accept_rate:.0%} 误放行内达标，取最严阈值 {strictest.threshold}",
            "false_reject_rate": strictest.false_reject_rate,
            "false_accept_rate": strictest.false_accept_rate,
        }

    best = min(feasible, key=lambda r: (r.false_reject_rate, -r.threshold))
    return {
        "threshold": best.threshold,
        "reason": (
            f"误放行 ≤ {max_false_accept_rate:.0%} 下误拒答最低 "
            f"({best.false_reject_rate:.1%} / {best.false_accept_rate:.1%})"
        ),
        "false_reject_rate": best.false_reject_rate,
        "false_accept_rate": best.false_accept_rate,
        "recall_pass": best.recall_pass,
    }


def score_distribution(query_results: List[QueryRetrievalResult]) -> Dict[str, Any]:
    def _stats(items: List[QueryRetrievalResult]) -> Dict[str, Any]:
        scores = [r.top_score for r in items if r.top_score is not None]
        if not scores:
            return {"count": len(items), "with_score": 0}
        scores_sorted = sorted(scores)
        return {
            "count": len(items),
            "with_score": len(scores),
            "min": round(min(scores), 4),
            "p10": round(scores_sorted[max(0, int(len(scores_sorted) * 0.1) - 1)], 4),
            "median": round(statistics.median(scores), 4),
            "p90": round(scores_sorted[min(len(scores_sorted) - 1, int(len(scores_sorted) * 0.9))], 4),
            "max": round(max(scores), 4),
        }

    pos = [r for r in query_results if r.should_answer]
    neg = [r for r in query_results if not r.should_answer]
    return {"should_answer": _stats(pos), "should_reject": _stats(neg)}


def run_retrieval_threshold_eval(
    search_fn: Callable[[str], List[Dict[str, Any]]],
    *,
    cases: Optional[List[RetrievalEvalCase]] = None,
    current_threshold: float = 0.4,
    start: float = 0.30,
    end: float = 0.55,
    step: float = 0.05,
    max_false_accept_rate: float = 0.0,
) -> Dict[str, Any]:
    cases = cases or load_retrieval_cases()
    query_results = evaluate_queries(cases, search_fn)
    sweep = sweep_thresholds(query_results, start=start, end=end, step=step)
    recommendation = recommend_threshold(sweep, max_false_accept_rate=max_false_accept_rate)

    current_row = next((r for r in sweep if abs(r.threshold - current_threshold) < 1e-6), None)

    return {
        "case_count": len(cases),
        "current_threshold": current_threshold,
        "current_metrics": {
            "false_reject_rate": current_row.false_reject_rate if current_row else None,
            "false_accept_rate": current_row.false_accept_rate if current_row else None,
        },
        "distribution": score_distribution(query_results),
        "recommendation": recommendation,
        "queries": [
            {
                "name": r.name,
                "query": r.query,
                "should_answer": r.should_answer,
                "top_score": r.top_score,
                "top_title": r.top_title,
                "hit_count": r.hit_count,
                "note": r.note,
            }
            for r in query_results
        ],
        "threshold_sweep": [
            {
                "threshold": row.threshold,
                "false_reject_rate": row.false_reject_rate,
                "false_accept_rate": row.false_accept_rate,
                "recall_pass": row.recall_pass,
                "precision_pass": row.precision_pass,
                "false_reject_count": row.false_reject_count,
                "false_accept_count": row.false_accept_count,
            }
            for row in sweep
        ],
    }
