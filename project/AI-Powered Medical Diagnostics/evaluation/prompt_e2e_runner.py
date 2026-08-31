# -*- coding: utf-8 -*-
"""工程化 Prompt 端到端回归：Agent + RAG + 内容启发式校验。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.intent_recognizer import IntentCategory
from core.medical_security import check_question
from core.safety_judge import rule_check_response

CASES_JSON = Path(__file__).resolve().parent / "prompt_e2e_cases.json"


@dataclass
class PromptE2ECase:
    name: str
    message: str
    intent: Optional[str] = None
    mode: str = "full"
    inject_context_suffix: str = ""
    expect: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptE2EResult:
    name: str
    passed: bool
    checks: List[str]
    response: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def load_prompt_e2e_cases(path: Path | None = None) -> tuple[List[PromptE2ECase], Dict[str, Any]]:
    path = path or CASES_JSON
    raw = json.loads(path.read_text(encoding="utf-8"))
    fixture_doc = raw.get("fixture_doc") or {}
    items = raw.get("cases", [])
    cases: List[PromptE2ECase] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        cases.append(PromptE2ECase(
            name=str(item.get("name", item["message"][:24])),
            message=str(item["message"]),
            intent=item.get("intent"),
            mode=str(item.get("mode", "full")),
            inject_context_suffix=str(item.get("inject_context_suffix", "")),
            expect=dict(item.get("expect") or {}),
        ))
    return cases, fixture_doc


def _intent_enum(name: Optional[str]) -> Optional[IntentCategory]:
    if not name:
        return None
    mapping = {
        "triage": IntentCategory.TRIAGE,
        "report": IntentCategory.REPORT_INTERPRET,
        "general": IntentCategory.GENERAL_MEDICAL,
        "emergency": IntentCategory.EMERGENCY,
        "greeting": IntentCategory.GREETING,
    }
    return mapping.get(name)


def _check_patterns(text: str, patterns: List[str], *, must: bool) -> tuple[bool, str]:
    body = text or ""
    for pat in patterns:
        if must and not re.search(pat, body, re.IGNORECASE):
            return False, f"missing pattern /{pat}/"
        if not must and re.search(pat, body, re.IGNORECASE):
            return False, f"forbidden pattern /{pat}/"
    label = "must" if must else "must_not"
    return True, f"✓ {label} patterns ({len(patterns)})"


def _agent_body_for_rule_check(text: str) -> str:
    """免责段会含「处方」等说明性用语，规则检仅看正文。"""
    body = text or ""
    for marker in ("**免责声明**", "免责声明"):
        if marker in body:
            body = body.split(marker, 1)[0]
    return body.strip()


def _check_expect(resp: Dict[str, Any], expect: Dict[str, Any]) -> tuple[bool, List[str]]:
    notes: List[str] = []
    passed = True
    text = str(resp.get("response") or "")
    body_for_check = _agent_body_for_rule_check(text) if not resp.get("blocked") else text

    for key, expected in expect.items():
        if key in (
            "comment",
            "response_must_match",
            "response_must_not_match",
        ):
            continue
        actual = resp.get(key)
        if actual != expected:
            passed = False
            notes.append(f"expect {key}={expected!r}, got {actual!r}")
        else:
            notes.append(f"✓ {key}={expected!r}")

    must = expect.get("response_must_match") or []
    if must:
        ok, detail = _check_patterns(body_for_check, list(must), must=True)
        if not ok:
            passed = False
        notes.append(detail)

    must_not = expect.get("response_must_not_match") or []
    if must_not:
        ok, detail = _check_patterns(body_for_check, list(must_not), must=False)
        if not ok:
            passed = False
        notes.append(detail)

    if expect.get("comment"):
        notes.append(f"note: {expect['comment']}")

    # 拒答模板会提及「处方」等词说明禁止开方，不做输出规则误杀
    if text.strip() and not resp.get("blocked"):
        judge = rule_check_response(_agent_body_for_rule_check(text))
        if not judge.passed:
            passed = False
            notes.append(f"rule_check failed: {judge.reasons}")

    return passed, notes


def run_security_only_case(case: PromptE2ECase) -> Dict[str, Any]:
    sec = check_question(case.message)
    return {
        "response": sec.response_text or "",
        "blocked": not sec.allowed,
        "emergency": sec.emergency,
        "blocked_reason": sec.blocked_reason,
        "agent_type": "security",
        "knowledge_used": False,
        "intent": sec.blocked_reason or "allowed",
    }


async def run_inprocess_prompt_e2e(
    *,
    mock_llm: bool = False,
    cases: Optional[List[PromptE2ECase]] = None,
    fixture_doc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """进程内跑 Agent 链路（不启 HTTP 服务）。"""
    import os
    from unittest.mock import AsyncMock, patch

    from agents.agent_orchestrator import AgentOrchestrator, Request as OrcReq
    from core.medical_security import (
        append_disclaimer,
        check_empty_agent_response,
        check_knowledge_gate,
    )
    from core.prompt_registry import init_prompt_registry
    from config import PROMPTS_DIR
    from mcp.knowledge_base import KnowledgeBase

    init_prompt_registry(PROMPTS_DIR)
    from core.medical_security import sync_templates_from_registry
    from core.prompt_registry import get_registry

    sync_templates_from_registry(get_registry())

    chroma_path = os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma")
    kb = KnowledgeBase(chroma_path=chroma_path)

    if not cases:
        loaded, fix = load_prompt_e2e_cases()
        cases = loaded
        if fixture_doc is None:
            fixture_doc = fix

    if fixture_doc:
        kb.add_documents([fixture_doc], tenant_id="shared")

    def _llm_cfg() -> Dict[str, Any]:
        from api.main import _llm_cfg as api_llm_cfg
        return api_llm_cfg()

    cfg = _llm_cfg()
    orchestrator = AgentOrchestrator(
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
    )

    async def _mock_create_message(*_args, **kwargs):
        stage = str(kwargs.get("stage") or "")
        if "agent_triage" in stage:
            payload = {
                "symptom_summary": "头痛三天伴恶心，可能需面诊评估",
                "suggested_departments": [
                    {"name": "神经内科", "reason": "头痛伴恶心常见初诊方向"},
                ],
                "visit_advice": "若头痛突然加重或呕吐频繁，请急诊",
                "clarifying_questions": ["是否发热？"],
            }
        elif "agent_report" in stage:
            payload = {
                "indicator_meaning": "指标需结合临床解读",
                "common_factors": ["需医生面诊"],
                "next_steps": "携带报告咨询相关科室",
            }
        else:
            payload = {
                "topic_summary": "就医咨询",
                "answer": "请咨询医疗机构获取个体化建议",
            }
        text = json.dumps(payload, ensure_ascii=False)
        block = type("B", (), {"type": "text", "text": text})()
        return type("R", (), {"content": [block]})()

    results: List[PromptE2EResult] = []

    from contextlib import ExitStack, nullcontext

    stack = ExitStack()
    if mock_llm:
        stack.enter_context(
            patch(
                "core.llm_utils.create_message",
                new=AsyncMock(side_effect=_mock_create_message),
            )
        )
        stack.enter_context(
            patch(
                "agents.agent_orchestrator.create_message",
                new=AsyncMock(side_effect=_mock_create_message),
            )
        )

    with stack:
        for case in cases:
            try:
                if case.mode == "security_only":
                    resp = run_security_only_case(case)
                    ok, checks = _check_expect(resp, case.expect)
                    results.append(PromptE2EResult(case.name, ok, checks, resp))
                    continue

                sec = check_question(case.message)
                if not sec.allowed:
                    resp = {
                        "response": sec.response_text or "",
                        "blocked": True,
                        "emergency": sec.emergency,
                        "blocked_reason": sec.blocked_reason,
                        "agent_type": "security",
                        "knowledge_used": False,
                        "intent": sec.blocked_reason or "blocked",
                    }
                    ok, checks = _check_expect(resp, case.expect)
                    results.append(PromptE2EResult(case.name, ok, checks, resp))
                    continue

                hits = kb.search(case.message, top_k=3, tenant_id="shared")
                sources = []
                top_score = None
                for h in hits:
                    score = float(h.get("score", 0) or 0)
                    if top_score is None or score > top_score:
                        top_score = score
                    sources.append({
                        "title": h.get("title", ""),
                        "content": h.get("content", ""),
                        "doc_type": h.get("doc_type", ""),
                        "source": h.get("source", ""),
                        "score": score,
                    })

                rag_gate = check_knowledge_gate(
                    case.message,
                    evidence_required=True,
                    source_count=len(sources),
                    top_score=top_score,
                )
                if not rag_gate.allowed:
                    resp = {
                        "response": rag_gate.response_text or "",
                        "blocked": True,
                        "blocked_reason": rag_gate.blocked_reason,
                        "agent_type": "rag_gate",
                        "knowledge_used": bool(sources),
                        "intent": rag_gate.blocked_reason or "rag_gate",
                        "source_count": len(sources),
                    }
                    ok, checks = _check_expect(resp, case.expect)
                    results.append(PromptE2EResult(case.name, ok, checks, resp))
                    continue

                reg = get_registry()
                rag_items = [
                    {
                        "title": s["title"],
                        "content": s["content"],
                        "doc_type": s.get("doc_type", ""),
                        "source": s.get("source", ""),
                        "score": s.get("score", 0),
                    }
                    for s in sources
                ]
                knowledge_text = reg.format_rag_context(rag_items)
                if case.inject_context_suffix:
                    knowledge_text = f"{knowledge_text}\n{case.inject_context_suffix}"

                orch_req = OrcReq(
                    message=case.message,
                    user_id="prompt-e2e",
                    conv_id="prompt-e2e",
                    context=knowledge_text,
                    intent=_intent_enum(case.intent),
                )
                result = await orchestrator.run(orch_req)

                empty_sec = check_empty_agent_response(result.response)
                if empty_sec is not None:
                    resp = {
                        "response": empty_sec.response_text or "",
                        "blocked": True,
                        "agent_type": "empty_agent",
                        "knowledge_used": True,
                        "intent": result.intent.value if result.intent else None,
                        "source_count": len(sources),
                    }
                    ok, checks = _check_expect(resp, case.expect)
                    results.append(PromptE2EResult(case.name, ok, checks, resp))
                    continue

                final = append_disclaimer(result.response)
                resp = {
                    "response": final,
                    "blocked": False,
                    "emergency": result.emergency,
                    "agent_type": result.agent_type.value,
                    "knowledge_used": True,
                    "intent": result.intent.value if result.intent else None,
                    "source_count": len(sources),
                    "sources": sources,
                }
                ok, checks = _check_expect(resp, case.expect)
                results.append(PromptE2EResult(case.name, ok, checks, resp))
            except Exception as ex:
                results.append(PromptE2EResult(
                    case.name, False, [f"error: {ex}"], {}, str(ex),
                ))

    passed = sum(1 for r in results if r.passed)
    return {
        "mode": "mock" if mock_llm else "live",
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "all_passed": passed == len(results),
        "cases": [
            {
                "name": r.name,
                "passed": r.passed,
                "checks": r.checks,
                "error": r.error,
                "blocked": r.response.get("blocked"),
                "emergency": r.response.get("emergency"),
                "agent_type": r.response.get("agent_type"),
                "knowledge_used": r.response.get("knowledge_used"),
                "intent": r.response.get("intent"),
                "source_count": r.response.get("source_count"),
                "response_preview": (r.response.get("response") or "")[:600],
                "full_response": r.response.get("response"),
            }
            for r in results
        ],
    }


def run_prompt_e2e_http(
    chat_fn: Callable[..., Dict[str, Any]],
    *,
    cases: Optional[List[PromptE2ECase]] = None,
) -> Dict[str, Any]:
    cases = cases or load_prompt_e2e_cases()[0]
    results: List[PromptE2EResult] = []
    for case in cases:
        if case.mode == "security_only":
            resp = run_security_only_case(case)
            ok, checks = _check_expect(resp, case.expect)
            results.append(PromptE2EResult(case.name, ok, checks, resp))
            continue
        try:
            resp = chat_fn(case.message)
            ok, checks = _check_expect(resp, case.expect)
            results.append(PromptE2EResult(case.name, ok, checks, resp))
        except Exception as ex:
            results.append(PromptE2EResult(case.name, False, [f"http error: {ex}"], {}, str(ex)))

    passed = sum(1 for r in results if r.passed)
    return {
        "mode": "http",
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "all_passed": passed == len(results),
        "cases": [
            {
                "name": r.name,
                "passed": r.passed,
                "checks": r.checks,
                "error": r.error,
                "response_preview": (r.response.get("response") or "")[:600],
                "full_response": r.response.get("response"),
                "blocked": r.response.get("blocked"),
                "emergency": r.response.get("emergency"),
                "agent_type": r.response.get("agent_type"),
            }
            for r in results
        ],
    }
