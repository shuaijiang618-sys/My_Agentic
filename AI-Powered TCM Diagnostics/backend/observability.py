# -*- coding: utf-8 -*-
"""运行观测：request_id + JSONL 审计（SKILL §二 / §三）。"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .config import DOC_EMB_DIR, ENABLE_OBSERVABILITY_LOG, LOGS_DIR

RUNS_LOG = LOGS_DIR / "runs.jsonl"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def get_release_id(index_dir: Path | None = None) -> str:
    index_dir = index_dir or DOC_EMB_DIR
    if not index_dir.is_dir():
        return "doc_emb@missing"
    parts: list[str] = []
    for p in sorted(index_dir.glob("*.json")):
        try:
            parts.append(f"{p.name}:{p.stat().st_mtime_ns}")
        except OSError:
            continue
    if not parts:
        return "doc_emb@empty"
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:8]
    return f"doc_emb@{digest}"


def log_run(
    *,
    request_id: str,
    query: str,
    duration_ms: Optional[int] = None,
    source_count: int = 0,
    top_k: int = 5,
    session_id: Optional[str] = None,
    blocked: bool = False,
    blocked_reason: Optional[str] = None,
    hitl_required: bool = False,
    error: Optional[str] = None,
    release_id: Optional[str] = None,
) -> None:
    if not ENABLE_OBSERVABILITY_LOG:
        return
    record: dict[str, Any] = {
        "ts": time.time(),
        "request_id": request_id,
        "session_id": session_id,
        "query": query[:200],
        "duration_ms": duration_ms,
        "top_k": top_k,
        "source_count": source_count,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
        "hitl_required": hitl_required,
        "error": error,
        "release_id": release_id,
    }
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        with RUNS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    if not RUNS_LOG.exists():
        return []
    try:
        lines = RUNS_LOG.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def aggregate_stats() -> dict[str, Any]:
    runs = recent_runs(limit=500)
    if not runs:
        return {"total_logged": 0, "error_rate": 0.0, "avg_duration_ms": None}
    errors = sum(1 for r in runs if r.get("error") or r.get("blocked"))
    durs = [r["duration_ms"] for r in runs if r.get("duration_ms") is not None]
    blocked_counts: dict[str, int] = {}
    for r in runs:
        reason = r.get("blocked_reason")
        if reason:
            blocked_counts[reason] = blocked_counts.get(reason, 0) + 1
    return {
        "total_logged": len(runs),
        "error_rate": round(errors / len(runs), 3) if runs else 0.0,
        "avg_duration_ms": int(sum(durs) / len(durs)) if durs else None,
        "last_request_id": runs[0].get("request_id") if runs else None,
        "blocked_by_reason": blocked_counts,
    }
