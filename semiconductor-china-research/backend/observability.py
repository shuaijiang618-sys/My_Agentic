"""Phase 3 M3.3 · 请求观测: request_id + JSONL 运行日志。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .config import LOGS, ENABLE_OBSERVABILITY_LOG

RUNS_LOG = LOGS / "runs.jsonl"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def log_run(
    *,
    request_id: str,
    session: str,
    query: str,
    duration_ms: int | None = None,
    run_id: str | None = None,
    quality: dict[str, Any] | None = None,
    experts: list[str] | None = None,
    error: str | None = None,
) -> None:
    """追加一行 JSONL 运行记录(失败静默,不阻塞主流程)。"""
    if not ENABLE_OBSERVABILITY_LOG:
        return
    record = {
        "ts": time.time(),
        "request_id": request_id,
        "session": session,
        "query": query[:200],
        "duration_ms": duration_ms,
        "run_id": run_id,
        "experts": experts or [],
        "quality_passed": (quality or {}).get("fact_check", {}).get("passed"),
        "compliance_flags": len((quality or {}).get("compliance", {}).get("flags", [])),
        "error": error,
    }
    try:
        RUNS_LOG.parent.mkdir(exist_ok=True)
        with RUNS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    """读取最近 N 条 JSONL 记录(新→旧)。"""
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
    """从 JSONL 汇总简单运维指标。"""
    runs = recent_runs(limit=500)
    if not runs:
        return {"total_logged": 0, "error_rate": 0.0, "avg_duration_ms": None}
    errors = sum(1 for r in runs if r.get("error"))
    durs = [r["duration_ms"] for r in runs if r.get("duration_ms") is not None]
    return {
        "total_logged": len(runs),
        "error_rate": round(errors / len(runs), 3) if runs else 0.0,
        "avg_duration_ms": int(sum(durs) / len(durs)) if durs else None,
        "last_request_id": runs[0].get("request_id") if runs else None,
    }
