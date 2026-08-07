# -*- coding: utf-8 -*-
"""HTTP API 路由（SKILL §三 / §五）。"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import (
    DOC_EMB_DIR,
    EMBEDDING,
    ENABLE_OBSERVABILITY_LOG,
    MODEL,
    SERVICE_NAME,
    SIMILARITY_TOP_K,
    VERSION,
)
from .observability import aggregate_stats, new_request_id
from .rag import execute_rag_query
from .security import ERROR_CODE_MAP, check_question

logger = logging.getLogger(__name__)
router = APIRouter()
_started_at = time.time()
_index_loaded: Optional[bool] = None


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def api_response(data: Any, request_id: str, message: str = "ok") -> dict[str, Any]:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "timestamp": _iso_timestamp(),
        "request_id": request_id,
    }


def error_body(
    error_code: str,
    message: str,
    request_id: str,
    http_status: int = 400,
) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={
            "errorCode": error_code,
            "message": message,
            "timestamp": _iso_timestamp(),
            "request_id": request_id,
        },
        headers={"X-Request-Id": request_id},
    )


def _friendly_llm_error(exc: Exception) -> tuple[str, str, int]:
    msg = str(exc).lower()
    if "401" in msg or "authentication" in msg or "api key" in msg:
        return "MISSING_API_KEY", "DashScope API 认证失败，请检查 DASHSCOPE_API_KEY", 401
    if "429" in msg or "rate limit" in msg or "too many" in msg:
        return "RATE_LIMITED", "DashScope API 限流，请稍后重试", 429
    if "402" in msg or "insufficient" in msg or "balance" in msg:
        return "LLM_UNAVAILABLE", "DashScope 账户余额不足，请充值后重试", 503
    return "LLM_UNAVAILABLE", f"上游 LLM 不可用: {type(exc).__name__}", 503


def _probe_index() -> bool:
    global _index_loaded
    if not DOC_EMB_DIR.is_dir():
        _index_loaded = False
        return False
    if not os.getenv("DASHSCOPE_API_KEY"):
        _index_loaded = False
        return False
    try:
        from new_zhongyi_agent import get_query_engine

        get_query_engine()
        _index_loaded = True
        return True
    except Exception as e:
        logger.warning("索引探活失败: %s", e)
        _index_loaded = False
        return False


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    top_k: int = Field(default=SIMILARITY_TOP_K, ge=1, le=20)


@router.get("/api/v1/health")
async def health():
    ok = _probe_index()
    return {
        "ok": ok,
        "service": SERVICE_NAME,
        "version": VERSION,
        "index_loaded": bool(_index_loaded),
        "index_path": "doc_emb",
        "llm": MODEL,
        "embedding": EMBEDDING,
        "similarity_top_k": SIMILARITY_TOP_K,
        "observability_log": ENABLE_OBSERVABILITY_LOG,
        "uptime_seconds": int(time.time() - _started_at),
    }


@router.get("/api/v1/stats")
async def stats():
    return aggregate_stats()


@router.post("/api/v1/queries")
async def create_query(body: QueryRequest, request: Request):
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    sec = check_question(body.question)
    if not sec.allowed:
        code = sec.error_code
        status = 400
        if code == "QUESTION_TOO_LONG":
            status = 400
        return error_body(code, sec.response_text or "请求无效", request_id, status)

    if not DOC_EMB_DIR.is_dir():
        return error_body("INDEX_NOT_FOUND", f"索引目录不存在: doc_emb", request_id, 503)

    if not os.getenv("DASHSCOPE_API_KEY"):
        return error_body(
            "MISSING_API_KEY",
            "未设置环境变量 DASHSCOPE_API_KEY",
            request_id,
            401,
        )

    try:
        result = execute_rag_query(
            body.question,
            apply_security=True,
            request_id=request_id,
            session_id=body.session_id,
            top_k=body.top_k,
        )
    except FileNotFoundError:
        return error_body("INDEX_NOT_FOUND", "索引目录不存在", request_id, 503)
    except EnvironmentError as e:
        return error_body("MISSING_API_KEY", str(e), request_id, 401)
    except Exception as e:
        code, message, status = _friendly_llm_error(e)
        logger.exception("queries 失败 request_id=%s", request_id)
        return error_body(code, message, request_id, status)

    meta = result.get("metadata", {})
    if meta.get("blocked") and meta.get("blocked_reason") in ERROR_CODE_MAP:
        err_code = ERROR_CODE_MAP[meta["blocked_reason"]]
        return error_body(err_code, result["answer"], request_id, 400)

    resp = api_response(result, request_id)
    return JSONResponse(content=resp, headers={"X-Request-Id": request_id})
