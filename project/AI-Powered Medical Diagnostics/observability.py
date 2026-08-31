# -*- coding: utf-8 -*-
"""JSONL 审计日志。"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from config import ENABLE_OBSERVABILITY_LOG, LOGS_DIR

RUNS_LOG = LOGS_DIR / "runs.jsonl"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def get_release_id(kb_doc_count: int = 0) -> str:
    kb_part = f"medical_kb@{kb_doc_count}"
    try:
        from core.prompt_registry import get_registry

        return f"{kb_part}+{get_registry().prompt_release_tag}"
    except Exception:
        return kb_part


def response_preview_max_len() -> int:
    return max(0, int(os.getenv("LOG_RESPONSE_PREVIEW_MAX", "500")))


def response_preview_for_log(text: Optional[str], *, max_len: Optional[int] = None) -> Optional[str]:
    """回复摘要：PII 脱敏 + 截断，供 runs.jsonl 审计。"""
    limit = response_preview_max_len() if max_len is None else max(0, max_len)
    if limit == 0:
        return None
    from core.medical_security import redact_pii

    preview = redact_pii((text or "").strip())
    if not preview:
        return ""
    return preview[:limit]


def blocked_outcome(*, metrics_stage: str, emergency: bool = False) -> str:
    if emergency:
        return "blocked_emergency"
    return {
        "input": "blocked_input",
        "rag": "blocked_rag",
        "agent": "blocked_agent",
    }.get(metrics_stage, "blocked_input")


def success_outcome(*, safety_passed: bool) -> str:
    return "success" if safety_passed else "blocked_judge"


def chat_outcome(*, safety_passed: bool, agent_success: bool = True) -> str:
    """/chat 成功路径 outcome：Agent LLM 失败时记 llm_failed，而非 success。"""
    if not agent_success:
        return "llm_failed"
    if not safety_passed:
        return "blocked_judge"
    return "success"


def _derive_timeout(llm_errors: Any) -> bool:
    if not isinstance(llm_errors, list):
        return False
    return any(
        isinstance(item, dict) and item.get("reason") == "timeout"
        for item in llm_errors
    )


def _truncate_message(text: Optional[str], limit: int = 500) -> Optional[str]:
    if text is None:
        return None
    msg = str(text).strip()
    if not msg:
        return ""
    return msg[:limit]


def log_run(
    *,
    request_id: str,
    query: str,
    duration_ms: Optional[int] = None,
    source_count: int = 0,
    session_id: Optional[str] = None,
    blocked: bool = False,
    blocked_reason: Optional[str] = None,
    hitl_required: bool = False,
    emergency: bool = False,
    intent: Optional[str] = None,
    agent_type: Optional[str] = None,
    safety_passed: bool = True,
    error: Optional[str] = None,
    release_id: Optional[str] = None,
    response_preview: Optional[str] = None,
    outcome: Optional[str] = None,
    exception_type: Optional[str] = None,
    exception_message: Optional[str] = None,
    timeout: Optional[bool] = None,
    rag_queried: Optional[bool] = None,
    rag_hit: Optional[bool] = None,
    effective_answer: Optional[bool] = None,
    hitl_escalated: Optional[bool] = None,
) -> None:
    if not ENABLE_OBSERVABILITY_LOG:
        return
    if outcome is None:
        if error:
            outcome = "error"
        elif blocked:
            outcome = blocked_outcome(metrics_stage="input", emergency=emergency)
        elif not safety_passed:
            outcome = "blocked_judge"
        else:
            outcome = "success"

    record: dict[str, Any] = {
        "ts": time.time(),
        "request_id": request_id,
        "session_id": session_id,
        "query": query[:200],
        "duration_ms": duration_ms,
        "source_count": source_count,
        "outcome": outcome,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
        "hitl_required": hitl_required,
        "emergency": emergency,
        "intent": intent,
        "agent_type": agent_type,
        "safety_passed": safety_passed,
        "error": _truncate_message(error),
        "exception_type": exception_type,
        "exception_message": _truncate_message(exception_message),
        "release_id": release_id,
    }
    if response_preview is not None:
        record["response_preview"] = response_preview
    if rag_queried is not None:
        record["rag_queried"] = rag_queried
    if rag_hit is not None:
        record["rag_hit"] = rag_hit
    if effective_answer is not None:
        record["effective_answer"] = effective_answer
    if hitl_escalated is not None:
        record["hitl_escalated"] = hitl_escalated

    try:
        from core.token_usage import token_fields_for_log

        record.update(token_fields_for_log())
    except Exception:
        pass

    record["timeout"] = (
        timeout if timeout is not None else _derive_timeout(record.get("llm_errors"))
    )

    try:
        LOGS_DIR.mkdir(exist_ok=True)
        with RUNS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def aggregate_stats() -> dict[str, Any]:
    if not RUNS_LOG.exists():
        return {"total_logged": 0}
    try:
        lines = RUNS_LOG.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return {"total_logged": 0}
    runs = [json.loads(line) for line in lines[-500:] if line.strip()]
    blocked = sum(1 for r in runs if r.get("blocked"))
    emergency = sum(1 for r in runs if r.get("emergency"))
    rag_queries = sum(1 for r in runs if r.get("rag_queried"))
    rag_hits = sum(1 for r in runs if r.get("rag_hit"))
    effective = sum(1 for r in runs if r.get("effective_answer"))
    hitl = sum(1 for r in runs if r.get("hitl_escalated"))
    llm_attempts = sum(int(r.get("llm_attempts", 0) or 0) for r in runs)
    llm_errors = sum(int(r.get("llm_error_count", 0) or 0) for r in runs)
    timeouts = sum(1 for r in runs if r.get("timeout"))
    return {
        "total_logged": len(runs),
        "blocked_rate": round(blocked / len(runs), 3) if runs else 0.0,
        "emergency_count": emergency,
        "rag_hit_rate": round(rag_hits / rag_queries, 3) if rag_queries else 0.0,
        "effective_answer_rate": round(effective / len(runs), 3) if runs else 0.0,
        "hitl_rate": round(hitl / len(runs), 3) if runs else 0.0,
        "llm_failure_rate": round(llm_errors / llm_attempts, 3) if llm_attempts else 0.0,
        "llm_timeout_rate": round(timeouts / len(runs), 3) if runs else 0.0,
    }
