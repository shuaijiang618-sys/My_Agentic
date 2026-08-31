# -*- coding: utf-8 -*-
"""RAG 检索阈值标定用例。

should_answer=True  ：知识库中应有足够相关片段，期望 top_score >= 阈值
should_answer=False ：不应放行（库外题/无关题/易误匹配题），期望 top_score < 阈值或无结果
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

EVAL_DIR = Path(__file__).resolve().parent
CASES_JSON = EVAL_DIR / "retrieval_cases.json"


@dataclass
class RetrievalEvalCase:
    name: str
    query: str
    should_answer: bool
    note: str = ""


DEFAULT_RETRIEVAL_CASES: List[RetrievalEvalCase] = [
    # ── 应答题（默认知识库可覆盖）──────────────────────────────────────────
    RetrievalEvalCase("alt_high", "ALT 52 偏高是什么意思", True, "lab_item"),
    RetrievalEvalCase("triage_abdominal", "肚子胀恶心应该挂什么科", True, "department"),
    RetrievalEvalCase("blood_pressure", "血压偏高要注意什么", True, "popular_science"),
    RetrievalEvalCase("registration_flow", "门诊挂号流程是怎样的", True, "hospital_flow"),
    RetrievalEvalCase("respiratory_triage", "咳嗽胸闷看什么科", True, "department"),
    # ── 应拒答（库外或弱相关）────────────────────────────────────────────────
    RetrievalEvalCase("oob_crp", "CRP 180 严重吗", False, "默认库无 CRP"),
    RetrievalEvalCase("oob_psa", "PSA 4.5 需要担心吗", False, "默认库无 PSA"),
    RetrievalEvalCase("off_topic_stock", "今天股票怎么样", False, "非医疗"),
    RetrievalEvalCase("off_topic_code", "帮我写一段 Python 代码", False, "非医疗"),
    RetrievalEvalCase("vague_short", "嗯", False, "过短无意义"),
    RetrievalEvalCase("wrong_domain", "王者荣耀怎么上分", False, "非医疗"),
]


def load_retrieval_cases(path: Path | None = None) -> List[RetrievalEvalCase]:
    path = path or CASES_JSON
    if not path.is_file():
        return list(DEFAULT_RETRIEVAL_CASES)
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: List[RetrievalEvalCase] = []
    for item in raw.get("cases", raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        cases.append(RetrievalEvalCase(
            name=str(item.get("name", item.get("query", ""))[:32]),
            query=str(item["query"]),
            should_answer=bool(item.get("should_answer", item.get("label") == "should_answer")),
            note=str(item.get("note", "")),
        ))
    return cases or list(DEFAULT_RETRIEVAL_CASES)


def cases_to_dict(cases: List[RetrievalEvalCase]) -> List[Dict[str, Any]]:
    return [
        {
            "name": c.name,
            "query": c.query,
            "should_answer": c.should_answer,
            "note": c.note,
        }
        for c in cases
    ]
