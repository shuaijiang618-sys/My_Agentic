# -*- coding: utf-8 -*-
"""请求级 LLM Token 统计（ContextVar + Prometheus）。"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.llm_utils import extract_text_content

_tracker_var: contextvars.ContextVar[Optional["TokenTracker"]] = contextvars.ContextVar(
    "medical_token_tracker", default=None,
)


@dataclass
class StageUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class TokenTracker:
    by_stage: Dict[str, StageUsage] = field(default_factory=dict)
    llm_calls: int = 0
    rag_mode: str = "none"
    any_estimated: bool = False
    llm_errors: list[dict[str, Any]] = field(default_factory=list)
    llm_retry_count: int = 0
    llm_attempts: int = 0

    def add(self, stage: str, prompt: int, completion: int, *, estimated: bool) -> None:
        bucket = self.by_stage.setdefault(stage, StageUsage())
        bucket.prompt_tokens += max(0, prompt)
        bucket.completion_tokens += max(0, completion)
        if estimated:
            self.any_estimated = True
        self.llm_calls += 1


def _estimate_tokens(text: str) -> int:
    """中英文混合粗算（无 usage 回退时用）。"""
    text = (text or "").strip()
    if not text:
        return 0
    return max(1, len(text) // 2)


def _usage_from_response(
    response: Any,
    *,
    prompt_text: str = "",
) -> tuple[int, int, bool]:
    usage = getattr(response, "usage", None)
    if usage is not None:
        inp = getattr(usage, "input_tokens", None)
        if inp is None:
            inp = getattr(usage, "prompt_tokens", None)
        out = getattr(usage, "output_tokens", None)
        if out is None:
            out = getattr(usage, "completion_tokens", None)
        if inp is not None and out is not None:
            return int(inp), int(out), False

    completion = extract_text_content(getattr(response, "content", None))
    return _estimate_tokens(prompt_text), _estimate_tokens(completion), True


def _prompt_text_from_kwargs(kwargs: Dict[str, Any]) -> str:
    parts: list[str] = []
    system = kwargs.get("system")
    if system:
        parts.append(str(system))
    for msg in kwargs.get("messages") or []:
        if isinstance(msg, dict):
            parts.append(str(msg.get("content", "")))
        else:
            parts.append(str(msg))
    return "\n".join(parts)


def reset_token_tracker(*, rag_mode: str = "none") -> None:
    _tracker_var.set(TokenTracker(rag_mode=rag_mode))


def set_rag_mode(mode: str) -> None:
    tracker = _tracker_var.get()
    if tracker is not None:
        tracker.rag_mode = mode


def _get_tracker(*, create: bool = False) -> Optional[TokenTracker]:
    tracker = _tracker_var.get()
    if tracker is None and create:
        tracker = TokenTracker()
        _tracker_var.set(tracker)
    return tracker


def record_llm_response(
    stage: str,
    response: Any,
    *,
    request_kwargs: Optional[Dict[str, Any]] = None,
    request_scoped: bool = True,
) -> None:
    if not request_scoped:
        return
    tracker = _get_tracker(create=True)
    prompt_text = _prompt_text_from_kwargs(request_kwargs or {})
    inp, out, estimated = _usage_from_response(response, prompt_text=prompt_text)
    tracker.add(stage, inp, out, estimated=estimated)


def record_llm_error(
    stage: str,
    reason: str,
    *,
    request_scoped: bool = True,
    status_code: Optional[int] = None,
) -> None:
    if request_scoped:
        tracker = _get_tracker(create=True)
        entry: dict[str, Any] = {"stage": str(stage), "reason": str(reason)}
        if status_code is not None:
            entry["status_code"] = int(status_code)
        tracker.llm_errors.append(entry)
    try:
        from monitor.metrics import record_llm_error as prom_record_llm_error

        prom_record_llm_error(stage=str(stage), reason=str(reason))
    except Exception:
        pass


def record_llm_retry(stage: str, *, request_scoped: bool = True) -> None:
    if request_scoped:
        tracker = _get_tracker(create=True)
        tracker.llm_retry_count += 1
    try:
        from monitor.metrics import record_llm_retry as prom_record_llm_retry

        prom_record_llm_retry(stage=str(stage))
    except Exception:
        pass


def record_llm_attempt(stage: str, *, request_scoped: bool = True) -> None:
    if request_scoped:
        tracker = _get_tracker(create=True)
        tracker.llm_attempts += 1
    try:
        from monitor.metrics import record_llm_attempt as prom_record_llm_attempt

        prom_record_llm_attempt(stage=str(stage))
    except Exception:
        pass


def snapshot_token_usage() -> Dict[str, Any]:
    tracker = _tracker_var.get()
    if tracker is None:
        return {
            "estimated_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "tokens_estimated": False,
            "llm_calls": 0,
            "rag_mode": "none",
            "tokens_by_stage": {},
            "llm_errors": [],
            "llm_error_count": 0,
            "llm_retry_count": 0,
            "llm_attempts": 0,
        }

    prompt_total = sum(s.prompt_tokens for s in tracker.by_stage.values())
    completion_total = sum(s.completion_tokens for s in tracker.by_stage.values())
    by_stage = {
        stage: {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total": usage.total,
            "estimated": usage.estimated,
        }
        for stage, usage in sorted(tracker.by_stage.items())
    }
    return {
        "estimated_tokens": prompt_total + completion_total,
        "prompt_tokens": prompt_total,
        "completion_tokens": completion_total,
        "tokens_estimated": tracker.any_estimated,
        "llm_calls": tracker.llm_calls,
        "rag_mode": tracker.rag_mode,
        "tokens_by_stage": by_stage,
        "llm_errors": list(tracker.llm_errors),
        "llm_error_count": len(tracker.llm_errors),
        "llm_retry_count": tracker.llm_retry_count,
        "llm_attempts": tracker.llm_attempts,
    }


def token_fields_for_log() -> Dict[str, Any]:
    """供 observability.log_run 展开写入 JSONL。"""
    snap = snapshot_token_usage()
    return {
        "estimated_tokens": snap["estimated_tokens"],
        "prompt_tokens": snap["prompt_tokens"],
        "completion_tokens": snap["completion_tokens"],
        "tokens_estimated": snap["tokens_estimated"],
        "llm_calls": snap["llm_calls"],
        "rag_mode": snap["rag_mode"],
        "tokens_by_stage": snap["tokens_by_stage"],
        "llm_errors": snap["llm_errors"],
        "llm_error_count": snap["llm_error_count"],
        "llm_retry_count": snap["llm_retry_count"],
        "llm_attempts": snap["llm_attempts"],
    }
