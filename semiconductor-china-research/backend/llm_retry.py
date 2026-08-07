"""Phase 3 · DeepSeek LLM 调用指数退避(429/503/超时)。"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

from .config import LLM_RETRY_MAX, LLM_RETRY_BASE_SEC

T = TypeVar("T")


def is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "rate limit", "too many", "503", "502", "timeout", "timed out"))


async def run_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int | None = None,
    base_delay: float | None = None,
    label: str = "llm",
) -> T:
    """对 agent.run 等异步调用做指数退避重试。"""
    retries = max_retries if max_retries is not None else LLM_RETRY_MAX
    delay = base_delay if base_delay is not None else LLM_RETRY_BASE_SEC
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            return await fn()
        except Exception as e:
            last = e
            if is_rate_limit_error(e) and attempt < retries - 1:
                wait = delay * (2 ** attempt)
                await asyncio.sleep(wait)
                continue
            raise
    assert last is not None
    raise last
