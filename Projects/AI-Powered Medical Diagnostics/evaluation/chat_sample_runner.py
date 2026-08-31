# -*- coding: utf-8 -*-
"""批量调用 /chat，生成可人工评分的评测报告。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

EVAL_DIR = Path(__file__).resolve().parent
CASES_JSON = EVAL_DIR / "chat_sample_cases.json"


@dataclass
class ChatSampleCase:
    name: str
    message: str
    expect: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatSampleResult:
    name: str
    message: str
    ok: bool
    checks: List[str]
    response: Dict[str, Any]
    error: Optional[str] = None


def load_chat_sample_cases(path: Path | None = None) -> List[ChatSampleCase]:
    path = path or CASES_JSON
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("cases", raw if isinstance(raw, list) else [])
    cases: List[ChatSampleCase] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        cases.append(ChatSampleCase(
            name=str(item.get("name", item["message"][:20])),
            message=str(item["message"]),
            expect=dict(item.get("expect") or {}),
        ))
    return cases


def _check_expect(resp: Dict[str, Any], expect: Dict[str, Any]) -> tuple[bool, List[str]]:
    """仅校验 expect 中显式声明的字段（不含 comment）。"""
    notes: List[str] = []
    passed = True

    for key, expected in expect.items():
        if key in ("comment", "blocked_reason_prefix"):
            continue
        actual = resp.get(key)
        if actual != expected:
            passed = False
            notes.append(f"expect {key}={expected!r}, got {actual!r}")
        else:
            notes.append(f"✓ {key}={expected!r}")

    prefix = expect.get("blocked_reason_prefix")
    if prefix is not None:
        if not resp.get("blocked"):
            passed = False
            notes.append(f"expect blocked (reason ~{prefix!r}), got blocked={resp.get('blocked')!r}")
        else:
            intent = str(resp.get("intent", ""))
            if prefix not in intent:
                passed = False
                notes.append(f"expect intent/block_reason ~{prefix!r}, got intent={intent!r}")
            else:
                notes.append(f"✓ blocked intent~{prefix!r}")

    if expect.get("comment"):
        notes.append(f"note: {expect['comment']}")

    # 仅有 comment、无硬性断言时视为通过（留给人工评审）
    hard_keys = {k for k in expect if k not in ("comment", "blocked_reason_prefix")}
    if not hard_keys and expect.get("comment"):
        return True, notes

    return passed, notes


def run_chat_sample_eval(
    chat_fn,
    *,
    cases: Optional[List[ChatSampleCase]] = None,
    user_id: str = "eval-bot",
) -> Dict[str, Any]:
    cases = cases or load_chat_sample_cases()
    results: List[ChatSampleResult] = []

    for case in cases:
        try:
            resp = chat_fn(case.message, user_id=user_id)
            ok, checks = _check_expect(resp, case.expect)
            results.append(ChatSampleResult(
                name=case.name,
                message=case.message,
                ok=ok,
                checks=checks,
                response=resp,
            ))
        except Exception as ex:
            results.append(ChatSampleResult(
                name=case.name,
                message=case.message,
                ok=False,
                checks=[f"request failed: {ex}"],
                response={},
                error=str(ex),
            ))

    passed = sum(1 for r in results if r.ok)
    return {
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "all_passed": passed == len(results),
        "cases": [
            {
                "name": r.name,
                "message": r.message,
                "passed": r.ok,
                "checks": r.checks,
                "error": r.error,
                "response_preview": (r.response.get("response") or "")[:500],
                "blocked": r.response.get("blocked"),
                "emergency": r.response.get("emergency"),
                "safety_passed": r.response.get("safety_passed"),
                "knowledge_used": r.response.get("knowledge_used"),
                "intent": r.response.get("intent"),
                "agent_type": r.response.get("agent_type"),
                "source_count": len(r.response.get("sources") or []),
                "sources": r.response.get("sources"),
                "latency_ms": r.response.get("latency_ms"),
                "request_id": r.response.get("request_id"),
                "full_response": r.response.get("response"),
            }
            for r in results
        ],
    }
