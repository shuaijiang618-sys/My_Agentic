# -*- coding: utf-8 -*-
"""RAG 网关：复用 new_zhongyi_agent.get_query_engine()，统一安全 / 证据 / 审计（SKILL §七）。"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import DOC_EMB_DIR, MODEL, SIMILARITY_TOP_K
from .observability import get_release_id, log_run, new_request_id
from .security import check_question, check_retrieval_score

logger = logging.getLogger(__name__)


def extract_sources(response, snippet_max: int = 400) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    sources: List[Dict[str, Any]] = []
    top_score: Optional[float] = None
    if not hasattr(response, "source_nodes") or not response.source_nodes:
        return sources, top_score
    for i, sn in enumerate(response.source_nodes):
        score = getattr(sn, "score", None)
        if i == 0 and score is not None:
            top_score = float(score)
        node = sn.node
        snippet = ""
        if hasattr(node, "get_content"):
            snippet = node.get_content()[:snippet_max]
        elif hasattr(node, "text"):
            snippet = node.text[:snippet_max]
        meta = getattr(node, "metadata", {}) or {}
        doc_ref = meta.get("file_path") or meta.get("filename") or meta.get("source") or "doc_emb"
        sources.append({
            "chunk_id": getattr(node, "node_id", None) or f"chunk-{i}",
            "snippet": snippet,
            "score": round(float(score), 4) if score is not None else None,
            "doc_ref": str(doc_ref),
        })
    return sources, top_score


def format_answer_with_citations(answer: str, sources: List[Dict[str, Any]]) -> str:
    if not sources:
        return answer
    lines = [answer, "", "---", "**参考依据（检索片段）**："]
    for i, src in enumerate(sources[:5], 1):
        score_txt = f"（相似度 {src['score']}）" if src.get("score") is not None else ""
        ref = src.get("doc_ref", "")
        lines.append(f"{i}. {src.get('snippet', '')}{score_txt}")
        if ref:
            lines.append(f"   来源：`{ref}`")
    return "\n".join(lines)


def execute_rag_query(
    question: str,
    *,
    query_engine=None,
    apply_security: bool = True,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    top_k: Optional[int] = None,
) -> Dict[str, Any]:
    """安全门禁 → 检索生成 → sources[] + JSONL 审计。"""
    if query_engine is None:
        from new_zhongyi_agent import get_query_engine

        query_engine = get_query_engine()

    rid = request_id or new_request_id()
    release_id = get_release_id(DOC_EMB_DIR)
    k = top_k or SIMILARITY_TOP_K
    t0 = time.perf_counter()

    def _finish(
        answer: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        blocked: bool = False,
        blocked_reason: Optional[str] = None,
        hitl_required: bool = False,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        srcs = sources or []
        log_run(
            request_id=rid,
            query=question,
            duration_ms=duration_ms,
            source_count=len(srcs),
            top_k=k,
            session_id=session_id,
            blocked=blocked,
            blocked_reason=blocked_reason,
            hitl_required=hitl_required,
            error=error,
            release_id=release_id,
        )
        return {
            "answer": answer,
            "sources": srcs,
            "metadata": {
                "model": MODEL,
                "duration_ms": duration_ms,
                "release_id": release_id,
                "request_id": rid,
                "blocked": blocked,
                "blocked_reason": blocked_reason,
                "hitl_required": hitl_required,
                "top_k": k,
            },
        }

    if apply_security:
        sec = check_question(question)
        if not sec.allowed:
            return _finish(
                sec.response_text or "",
                blocked=True,
                blocked_reason=sec.blocked_reason,
                hitl_required=sec.hitl_required,
            )

    try:
        response = query_engine.query(question)
        sources, top_score = extract_sources(response)
        if apply_security:
            low = check_retrieval_score(top_score, question)
            if not low.allowed:
                return _finish(
                    low.response_text or "",
                    sources=sources,
                    blocked=True,
                    blocked_reason=low.blocked_reason,
                    hitl_required=low.hitl_required,
                )
        return _finish(str(response), sources=sources)
    except Exception as e:
        logger.exception("RAG 查询失败 request_id=%s", rid)
        return _finish(
            f"处理问题时出错: {type(e).__name__}: {e}",
            blocked=True,
            blocked_reason="internal_error",
            error=str(e),
        )
