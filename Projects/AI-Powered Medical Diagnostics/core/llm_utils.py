"""LLM response helpers shared by Anthropic-compatible providers."""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def extract_text_content(content: Iterable[Any]) -> str:
    """Return text blocks from Anthropic-style response content."""
    texts: List[str] = []
    for block in content or []:
        if isinstance(block, str):
            texts.append(block)
            continue

        block_type = getattr(block, "type", None)
        text = getattr(block, "text", None)
        if isinstance(block, dict):
            block_type = block.get("type", block_type)
            text = block.get("text", text)

        if isinstance(text, str) and (block_type in (None, "text")):
            texts.append(text)

    return "\n".join(t for t in texts if t)


def normalize_anthropic_base_url(base_url: str) -> str:
    """
    Anthropic SDK 请求路径为 {base_url}/v1/messages。

    - DeepSeek：Anthropic 兼容面在 https://api.deepseek.com/anthropic（非根域名）
    - 勿配置 …/v1 后缀，否则会 …/v1/v1/messages → 404
    """
    url = (base_url or "").strip().rstrip("/")
    if url.endswith("/v1"):
        url = url.rstrip("/")[:-3]
    url = url.rstrip("/")
    if "deepseek.com" in url.lower() and "/anthropic" not in url.lower():
        url = f"{url}/anthropic"
    return url


def llm_timeout_s() -> float:
    return max(1.0, float(os.getenv("LLM_TIMEOUT_S", "60")))


def llm_max_retries() -> int:
    return max(0, int(os.getenv("LLM_MAX_RETRIES", "1")))


def llm_retry_enabled() -> bool:
    return os.getenv("LLM_RETRY_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def llm_retry_backoff_s() -> float:
    return max(0.0, float(os.getenv("LLM_RETRY_BACKOFF_S", "0.5")))


def classify_llm_error(exc: BaseException) -> Tuple[str, bool, Optional[int]]:
    """
    返回 (reason, retryable, status_code)。
    reason: timeout | rate_limit | server_error | network | client_error | unknown
    """
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout", True, None

    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)

    if status is not None:
        code = int(status)
        if code == 429:
            return "rate_limit", True, code
        if code >= 500:
            return "server_error", True, code
        if code >= 400:
            return "client_error", False, code

    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "timeout", True, None
    if "429" in text or "rate limit" in text or "rate_limit" in text:
        return "rate_limit", True, 429
    if any(k in name for k in ("connect", "network", "connection")):
        return "network", True, None
    if any(k in text for k in ("connection reset", "connection refused", "connect error")):
        return "network", True, None

    return "unknown", False, None


async def create_message(
    client: Any,
    *,
    stage: str,
    request_scoped: bool = True,
    allow_retry: bool = True,
    **kwargs: Any,
):
    """
    统一 LLM 调用：超时、可配置重试、Token 与错误指标。

    重试条件：timeout / 429 / 5xx / 网络类错误（LLM_RETRY_ENABLED=true）。
    4xx（除 429）不重试；Judge 等仍 fail-closed，但可受益于超时/5xx 重试。
    """
    from core.token_usage import record_llm_attempt, record_llm_error, record_llm_response, record_llm_retry

    timeout_s = llm_timeout_s()
    max_retries = llm_max_retries() if allow_retry and llm_retry_enabled() else 0
    backoff_s = llm_retry_backoff_s()
    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        record_llm_attempt(stage, request_scoped=request_scoped)
        if attempt > 0:
            record_llm_retry(stage, request_scoped=request_scoped)
            delay = backoff_s * (1.0 + random.random())
            logger.info(
                "LLM 重试 stage=%s attempt=%d/%d delay=%.2fs",
                stage, attempt, max_retries, delay,
            )
            await asyncio.sleep(delay)

        try:
            resp = await asyncio.wait_for(
                client.messages.create(**kwargs),
                timeout=timeout_s,
            )
            record_llm_response(
                stage,
                resp,
                request_kwargs=kwargs,
                request_scoped=request_scoped,
            )
            return resp
        except Exception as exc:
            last_exc = exc
            reason, retryable, status_code = classify_llm_error(exc)
            record_llm_error(
                stage,
                reason,
                request_scoped=request_scoped,
                status_code=status_code,
            )
            can_retry = retryable and attempt < max_retries
            logger.warning(
                "LLM 调用失败 stage=%s reason=%s status=%s retryable=%s attempt=%d/%d err=%s",
                stage,
                reason,
                status_code,
                retryable,
                attempt + 1,
                max_retries + 1,
                exc,
            )
            if not can_retry:
                raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("LLM 调用失败且无异常信息")
