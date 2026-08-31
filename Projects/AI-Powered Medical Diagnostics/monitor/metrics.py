# -*- coding: utf-8 -*-
"""Prometheus 指标定义（应用内 Monitor + HTTP /chat 共用同一 Registry）。"""
from __future__ import annotations

import logging
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

_metrics_started = False

# ── Agent / 工具（PerformanceMonitor 周期写入）────────────────────────────────
AGENT_SUCCESS_RATE = Gauge(
    "agent_success_rate",
    "Agent 成功率",
    ["agent"],
)
AGENT_LATENCY_MS = Histogram(
    "agent_latency_ms",
    "Agent 延迟（毫秒）",
    ["agent"],
    buckets=(100, 250, 500, 1000, 2000, 3000, 5000, 10000, 30000),
)
TOOL_SUCCESS_RATE = Gauge(
    "tool_success_rate",
    "工具成功率",
    ["tool"],
)

# ── Chat / 安全门禁（/chat 请求路径写入）──────────────────────────────────────
CHAT_REQUESTS = Counter(
    "medical_chat_requests_total",
    "Chat 请求总数",
    ["outcome"],
)
KNOWLEDGE_GATE_BLOCKS = Counter(
    "medical_knowledge_gate_blocks_total",
    "RAG 门禁拦截次数",
    ["reason"],
)
SAFETY_JUDGE_BLOCKS = Counter(
    "medical_safety_judge_blocks_total",
    "Safety Judge 拦截次数",
)
RAG_EMPTY_RESULTS = Counter(
    "medical_rag_empty_results_total",
    "需要证据但检索无结果",
)
CHAT_LATENCY_SECONDS = Histogram(
    "medical_chat_latency_seconds",
    "Chat 端点延迟（秒）",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
LLM_TOKENS = Counter(
    "medical_llm_tokens_total",
    "LLM Token 累计（按 stage）",
    ["stage", "kind"],
)
CHAT_ESTIMATED_TOKENS = Histogram(
    "medical_chat_estimated_tokens",
    "单次 Chat 估算 Token 总量",
    buckets=(100, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000),
)
CHAT_LLM_CALLS = Histogram(
    "medical_chat_llm_calls",
    "单次 Chat LLM 调用次数",
    buckets=(0, 1, 2, 3, 4, 5, 6, 8, 10, 15),
)
LLM_ATTEMPTS = Counter(
    "medical_llm_attempts_total",
    "LLM 调用尝试次数（含重试，失败率/超时率分母）",
    ["stage"],
)
LLM_ERRORS = Counter(
    "medical_llm_errors_total",
    "LLM 调用错误累计",
    ["stage", "reason"],
)
LLM_RETRIES = Counter(
    "medical_llm_retries_total",
    "LLM 网络/API 重试次数",
    ["stage"],
)
KNOWLEDGE_CHUNKS = Gauge(
    "medical_knowledge_chunks",
    "知识库向量片段数量",
)

# ── 业务 KPI（/chat 单次请求）────────────────────────────────────────────────
CHAT_RAG_QUERIES = Counter(
    "medical_chat_rag_queries_total",
    "执行了 RAG 检索的 Chat 请求数",
)
CHAT_RAG_HITS = Counter(
    "medical_chat_rag_hits_total",
    "RAG 有命中（source_count>0）的 Chat 请求数",
)
CHAT_EFFECTIVE_ANSWERS = Counter(
    "medical_chat_effective_answers_total",
    "有效回答（Agent 成功 + Safety 通过 + 未拦截）",
)
CHAT_HITL = Counter(
    "medical_chat_hitl_total",
    "需人工转接/升级（hitl / escalated / emergency）",
)


def set_knowledge_chunks(count: int) -> None:
    KNOWLEDGE_CHUNKS.set(max(0, int(count)))


def record_llm_attempt(*, stage: str) -> None:
    LLM_ATTEMPTS.labels(stage=str(stage)).inc()


def record_llm_error(*, stage: str, reason: str) -> None:
    LLM_ERRORS.labels(stage=stage, reason=reason).inc()


def record_llm_retry(*, stage: str) -> None:
    LLM_RETRIES.labels(stage=stage).inc()


def record_chat_business_kpis(
    *,
    rag_queried: bool = False,
    rag_hit: bool = False,
    effective_answer: bool = False,
    hitl: bool = False,
) -> None:
    """业务 KPI 原始计数（比率见 prometheus/recording_rules/medical-kpi.yml）。"""
    if rag_queried:
        CHAT_RAG_QUERIES.inc()
    if rag_hit:
        CHAT_RAG_HITS.inc()
    if effective_answer:
        CHAT_EFFECTIVE_ANSWERS.inc()
    if hitl:
        CHAT_HITL.inc()


def record_chat_tokens(snapshot: dict) -> None:
    """将单次请求的 Token snapshot 写入 Prometheus。"""
    by_stage = snapshot.get("tokens_by_stage") or {}
    for stage, usage in by_stage.items():
        if not isinstance(usage, dict):
            continue
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        if prompt:
            LLM_TOKENS.labels(stage=str(stage), kind="prompt").inc(prompt)
        if completion:
            LLM_TOKENS.labels(stage=str(stage), kind="completion").inc(completion)
    total = int(snapshot.get("estimated_tokens", 0) or 0)
    if total > 0:
        CHAT_ESTIMATED_TOKENS.observe(total)
    calls = int(snapshot.get("llm_calls", 0) or 0)
    CHAT_LLM_CALLS.observe(calls)


def _observe_chat_tokens() -> None:
    try:
        from core.token_usage import snapshot_token_usage

        record_chat_tokens(snapshot_token_usage())
    except Exception:
        pass


def record_chat_blocked(*, stage: str, reason: str, latency_s: float) -> None:
    """stage: input | rag | agent"""
    outcome_map = {
        "input": "blocked_input",
        "rag": "blocked_rag",
        "agent": "blocked_agent",
    }
    outcome = outcome_map.get(stage, "blocked_input")
    CHAT_REQUESTS.labels(outcome=outcome).inc()
    CHAT_LATENCY_SECONDS.observe(latency_s)
    if stage == "rag" and reason:
        KNOWLEDGE_GATE_BLOCKS.labels(reason=reason).inc()
    _observe_chat_tokens()


def record_rag_empty() -> None:
    RAG_EMPTY_RESULTS.inc()


def record_chat_success(*, latency_s: float, judge_blocked: bool) -> None:
    CHAT_REQUESTS.labels(outcome="success").inc()
    CHAT_LATENCY_SECONDS.observe(latency_s)
    if judge_blocked:
        SAFETY_JUDGE_BLOCKS.inc()
        CHAT_REQUESTS.labels(outcome="blocked_judge").inc()
    _observe_chat_tokens()


def record_chat_llm_failed(*, latency_s: float, judge_blocked: bool) -> None:
    CHAT_REQUESTS.labels(outcome="llm_failed").inc()
    CHAT_LATENCY_SECONDS.observe(latency_s)
    if judge_blocked:
        SAFETY_JUDGE_BLOCKS.inc()
        CHAT_REQUESTS.labels(outcome="blocked_judge").inc()
    _observe_chat_tokens()


def record_chat_error(*, latency_s: float) -> None:
    CHAT_REQUESTS.labels(outcome="error").inc()
    CHAT_LATENCY_SECONDS.observe(latency_s)
    _observe_chat_tokens()


def start_metrics_server(port: Optional[int]) -> None:
    """可选：独立 metrics 端口（与 FastAPI /metrics 共用 Registry）。"""
    global _metrics_started
    if not port or _metrics_started:
        return
    start_http_server(port)
    _metrics_started = True
    logger.info("Prometheus metrics 端口已启动: :%s", port)
