"""
AI-Powered Medical Diagnostics — 医疗导诊与报告解释助手 FastAPI 入口。

流程：安全预检 → 记忆 + RAG 门禁 → Agent → 空内容检验 → Safety Judge → 免责声明 → 审计
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

_ROOT_PATH = pathlib.Path(__file__).parent.parent.resolve()
_ROOT = str(_ROOT_PATH)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field

from core.auth import (
    AuthContext,
    require_admin_auth,
    require_chat_auth,
    require_readonly_auth,
    validate_client_user_id,
)

# 始终从项目根目录加载 .env（避免 uvicorn 工作目录不同导致读不到密钥）
load_dotenv(_ROOT_PATH / ".env", override=False)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BANNER = r"""
   ╔══════════════════════════════════════╗
   ║  AI-Powered Medical Diagnostics v1.0 ║
   ║       医疗导诊 · 报告解释助手         ║
   ╚══════════════════════════════════════╝
"""

_orchestrator = None
_memory = None
_tool_manager = None
_monitor = None
_skill_manager = None
_safety_judge = None
_llm_client = None
_llm_model = ""
_kb = None
_release_id = "medical_kb@0"


def _llm_cfg() -> Dict[str, Any]:
    """支持 DeepSeek（OpenAI 兼容）或 Anthropic 官方 API。"""
    from core.llm_utils import normalize_anthropic_base_url

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    if deepseek_key:
        cfg: Dict[str, Any] = {
            "api_key": deepseek_key,
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        }
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
        if base_url:
            cfg["base_url"] = normalize_anthropic_base_url(base_url)
        return cfg

    if anthropic_key:
        cfg = {
            "api_key": anthropic_key,
            "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip(),
        }
        base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
        if base_url:
            cfg["base_url"] = normalize_anthropic_base_url(base_url)
        return cfg

    raise RuntimeError(
        "未设置 LLM API Key。请在 .env 中配置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _orchestrator, _memory, _tool_manager, _monitor, _skill_manager
    global _safety_judge, _kb, _release_id, _llm_client, _llm_model

    print(BANNER, flush=True)

    from core.auth import auth_enabled
    from core.jwt_auth import jwt_enabled

    if auth_enabled() and jwt_enabled():
        from core.jwt_auth import _import_pyjwt
        _import_pyjwt()
        logger.info("JWT 鉴权已启用（PyJWT OK）")

    from anthropic import AsyncAnthropic
    from agents.agent_orchestrator import AgentOrchestrator
    from core.medical_security import redact_pii
    from core.safety_judge import SafetyJudge
    from core.skill_loader import SkillManager
    from mcp.knowledge_base import KnowledgeBase
    from mcp.tool_manager import MCPToolManager, Tool
    from memory.conversation_memory import MemoryManager
    from monitor.performance_monitor import PerformanceMonitor
    from observability import get_release_id

    cfg = _llm_cfg()
    client = AsyncAnthropic(
        api_key=cfg["api_key"],
        **({"base_url": cfg["base_url"]} if cfg.get("base_url") else {}),
    )
    _llm_client = client
    _llm_model = cfg["model"]

    from core.prompt_registry import init_prompt_registry
    from core import medical_security as med_sec

    _prompt_registry = init_prompt_registry()
    med_sec.sync_templates_from_registry(_prompt_registry)

    skills_dir = os.getenv("ECHOMIND_SKILLS_DIR", str(pathlib.Path(_ROOT) / "skills"))
    _skill_manager = SkillManager(root_dir=skills_dir)
    _skill_manager.load()

    _orchestrator = AgentOrchestrator(
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
        skill_manager=_skill_manager,
    )

    _memory = MemoryManager(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", str(pathlib.Path(_ROOT) / "data/chroma")),
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
    )

    _tool_manager = MCPToolManager(
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
    )
    _kb = KnowledgeBase(
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", str(pathlib.Path(_ROOT) / "data/chroma")),
    )
    _release_id = get_release_id(_kb.doc_count)

    async def kb_handler(params: Dict[str, Any], context: Any) -> List[Dict]:
        return await _kb.search_handler(params, context)

    _tool_manager.register(Tool(
        name="knowledge_search",
        description="搜索医疗科普与导诊知识库",
        handler=kb_handler,
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "doc_type": {"type": "string"},
            },
            "required": ["query"],
        },
        cache_ttl=300.0,
        supports_rerank=True,
    ))

    _safety_judge = SafetyJudge(client, cfg["model"])

    prom_port = int(os.getenv("PROMETHEUS_PORT", "0")) or None
    from monitor.metrics import set_knowledge_chunks, start_metrics_server

    start_metrics_server(prom_port)
    set_knowledge_chunks(_kb.doc_count)

    _monitor = PerformanceMonitor(
        orchestrator=_orchestrator,
        tool_manager=_tool_manager,
        interval_s=float(os.getenv("MONITOR_INTERVAL", "30")),
        prometheus_port=prom_port,
    )
    await _monitor.start()

    from config import PROJECT_NAME

    logger.info("%s 已就绪 | 知识片段: %d | release: %s", PROJECT_NAME, _kb.doc_count, _release_id)
    yield
    await _monitor.stop()


app = FastAPI(
    title="AI-Powered Medical Diagnostics",
    version="1.0.0",
    description="医疗导诊与报告解释助手（非诊断系统）",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/metrics", make_asgi_app())


class SourceItem(BaseModel):
    title: str = ""
    content: str = ""
    doc_type: str = ""
    source: str = ""
    score: float = 0.0


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    user_id: str = "anonymous"
    conv_id: Optional[str] = None


class ChatResponse(BaseModel):
    conv_id: str
    response: str
    intent: str
    agent_type: str
    escalated: bool
    emergency: bool
    blocked: bool
    hitl_required: bool
    safety_passed: bool
    disclaimer: str
    sources: List[SourceItem]
    knowledge_used: bool
    latency_ms: float
    request_id: str


class DocInput(BaseModel):
    title: str
    content: str
    doc_type: str = "popular_science"
    source: str = "upload"


class BatchDocInput(BaseModel):
    documents: List[DocInput]


class KnowledgeImportInput(BaseModel):
    """从本地目录批量导入（服务端路径，默认 data/medical_knowledge）。"""
    directory: Optional[str] = None
    recursive: bool = True


@app.get("/knowledge/stats")
async def knowledge_stats(auth: AuthContext = Depends(require_readonly_auth)):
    if _kb is None:
        raise HTTPException(503, "知识库未就绪")
    stats = _kb.stats()
    from core.auth import auth_enabled
    if auth_enabled():
        stats["auth"] = {"tenant_id": auth.tenant_id, "role": auth.role}
    return stats


@app.get("/", include_in_schema=False)
async def root():
    """浏览器访问根路径时跳转到交互式 API 文档。"""
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    from core.auth import auth_enabled
    from observability import aggregate_stats
    if _orchestrator is None:
        raise HTTPException(503, "服务未就绪")
    return {
        "status": "ok",
        "product": "AI-Powered Medical Diagnostics",
        "auth_enabled": auth_enabled(),
        "agents": _orchestrator.get_stats(),
        "knowledge_chunks": _kb.doc_count if _kb else 0,
        "release_id": _release_id,
        "audit": aggregate_stats(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    auth: AuthContext = Depends(require_chat_auth),
):
    from agents.agent_orchestrator import Request as OrcReq
    from core.medical_security import (
        DISCLAIMER,
        append_disclaimer,
        check_empty_agent_response,
        check_knowledge_gate,
        check_question_async,
        redact_pii,
    )
    from memory.conversation_memory import MsgRole
    from observability import (
        blocked_outcome,
        chat_outcome,
        log_run,
        new_request_id,
        response_preview_for_log,
    )

    if _orchestrator is None or _memory is None or _safety_judge is None:
        raise HTTPException(503, "服务未就绪")

    validate_client_user_id(auth, req.user_id)
    effective_user_id = auth.effective_user_id(req.user_id)
    tenant_id = auth.tenant_id

    t0 = time.monotonic()
    request_id = new_request_id()
    conv_id = req.conv_id or str(uuid.uuid4())

    from core.token_usage import reset_token_tracker

    reset_token_tracker(rag_mode="none")

    rag_queried = False
    rag_hit = False

    def _blocked_response(
        sec,
        *,
        knowledge_used: bool = False,
        sources: Optional[List] = None,
        metrics_stage: str = "input",
        rag_queried_flag: Optional[bool] = None,
        rag_hit_flag: Optional[bool] = None,
    ) -> ChatResponse:
        latency = round((time.monotonic() - t0) * 1000, 1)
        from monitor.metrics import record_chat_blocked, record_chat_business_kpis

        emergency = getattr(sec, "emergency", False)
        rq = rag_queried if rag_queried_flag is None else rag_queried_flag
        rh = rag_hit if rag_hit_flag is None else rag_hit_flag
        hitl = emergency or sec.hitl_required
        record_chat_blocked(
            stage=metrics_stage,
            reason=sec.blocked_reason or "unknown",
            latency_s=latency / 1000.0,
        )
        record_chat_business_kpis(
            rag_queried=rq,
            rag_hit=rh,
            effective_answer=False,
            hitl=hitl,
        )
        log_run(
            request_id=request_id,
            query=redact_pii(req.message),
            session_id=conv_id,
            blocked=True,
            blocked_reason=sec.blocked_reason,
            hitl_required=sec.hitl_required,
            emergency=emergency,
            release_id=_release_id,
            duration_ms=int(latency),
            source_count=len(sources or []),
            response_preview=response_preview_for_log(sec.response_text or ""),
            outcome=blocked_outcome(metrics_stage=metrics_stage, emergency=emergency),
            rag_queried=rq,
            rag_hit=rh,
            effective_answer=False,
            hitl_escalated=hitl,
        )
        return ChatResponse(
            conv_id=conv_id,
            response=sec.response_text or "",
            intent="emergency" if emergency else (sec.blocked_reason or "blocked"),
            agent_type="emergency" if emergency else "security",
            escalated=emergency or sec.hitl_required,
            emergency=emergency,
            blocked=True,
            hitl_required=sec.hitl_required,
            safety_passed=True,
            disclaimer=DISCLAIMER,
            sources=[SourceItem(**s) for s in (sources or [])],
            knowledge_used=knowledge_used,
            latency_ms=latency,
            request_id=request_id,
        )

    try:
        sec = await check_question_async(
            req.message,
            llm_client=_llm_client,
            llm_model=_llm_model,
        )
        if not sec.allowed:
            return _blocked_response(sec)

        evidence_required = _requires_knowledge_evidence(req.message)
        knowledge_text, sources, knowledge_used, top_score = await _build_knowledge_context(
            req.message, tenant_id=tenant_id,
        )
        rag_queried = True
        rag_hit = len(sources) > 0

        rag_gate = check_knowledge_gate(
            req.message,
            evidence_required=evidence_required,
            source_count=len(sources),
            top_score=top_score,
        )
        if not rag_gate.allowed:
            logger.info(
                "RAG 门禁拦截: reason=%s score=%s sources=%d",
                rag_gate.blocked_reason, top_score, len(sources),
            )
            return _blocked_response(
                rag_gate,
                knowledge_used=knowledge_used,
                sources=sources,
                metrics_stage="rag",
                rag_queried_flag=True,
                rag_hit_flag=rag_hit,
            )

        mem_ctx = await _memory.get_context(effective_user_id, conv_id, query=req.message)
        history = [
            {"role": m.role.value, "content": m.content}
            for m in mem_ctx.recent_messages[-5:]
        ] if mem_ctx.recent_messages else None

        context_parts = [mem_ctx.to_prompt_text()]
        if knowledge_text:
            context_parts.append(knowledge_text)
        full_context = "\n\n".join(p for p in context_parts if p)

        orch_req = OrcReq(
            message=req.message,
            user_id=effective_user_id,
            conv_id=conv_id,
            context=full_context,
            history=history,
        )
        result = await _orchestrator.run(orch_req)

        empty_sec = check_empty_agent_response(result.response)
        if empty_sec is not None:
            logger.warning("Agent 空内容拦截")
            return _blocked_response(
                empty_sec,
                knowledge_used=knowledge_used,
                sources=sources,
                metrics_stage="agent",
                rag_queried_flag=True,
                rag_hit_flag=rag_hit,
            )

        verdict = await _safety_judge.judge(req.message, result.response)
        if verdict.passed:
            final_response = append_disclaimer(result.response)
            safety_passed = True
        else:
            final_response = verdict.safe_response
            safety_passed = False
            logger.warning("Safety Judge 拦截: %s", verdict.reasons)

        await _memory.add_message(effective_user_id, conv_id, MsgRole.USER, req.message)
        await _memory.add_message(effective_user_id, conv_id, MsgRole.ASSISTANT, final_response)
        asyncio.create_task(_memory.update_profile(effective_user_id, conv_id))

        latency = round((time.monotonic() - t0) * 1000, 1)
        from monitor.metrics import record_chat_business_kpis, record_chat_llm_failed, record_chat_success

        outcome = chat_outcome(
            safety_passed=safety_passed,
            agent_success=result.agent_success,
        )
        effective = result.agent_success and safety_passed
        hitl = result.escalated or not safety_passed or result.emergency
        record_chat_business_kpis(
            rag_queried=True,
            rag_hit=rag_hit,
            effective_answer=effective,
            hitl=hitl,
        )
        if result.agent_success:
            record_chat_success(latency_s=latency / 1000.0, judge_blocked=not safety_passed)
        else:
            record_chat_llm_failed(latency_s=latency / 1000.0, judge_blocked=not safety_passed)
        log_run(
            request_id=request_id,
            query=redact_pii(req.message),
            session_id=conv_id,
            duration_ms=int(latency),
            source_count=len(sources),
            blocked=False,
            hitl_required=result.escalated or not safety_passed,
            emergency=result.emergency,
            intent=result.intent.value if result.intent else None,
            agent_type=result.agent_type.value,
            safety_passed=safety_passed,
            release_id=_release_id,
            response_preview=response_preview_for_log(final_response),
            outcome=outcome,
            rag_queried=True,
            rag_hit=rag_hit,
            effective_answer=effective,
            hitl_escalated=hitl,
        )

        return ChatResponse(
            conv_id=conv_id,
            response=final_response,
            intent=result.intent.value if result.intent else "other",
            agent_type=result.agent_type.value,
            escalated=result.escalated or not safety_passed,
            emergency=result.emergency,
            blocked=False,
            hitl_required=result.escalated or not safety_passed,
            safety_passed=safety_passed,
            disclaimer=DISCLAIMER,
            sources=[SourceItem(**s) for s in sources],
            knowledge_used=knowledge_used,
            latency_ms=latency,
            request_id=request_id,
        )
    except HTTPException:
        raise
    except Exception as ex:
        latency = round((time.monotonic() - t0) * 1000, 1)
        from monitor.metrics import record_chat_business_kpis, record_chat_error

        record_chat_error(latency_s=latency / 1000.0)
        record_chat_business_kpis(
            rag_queried=rag_queried,
            rag_hit=rag_hit,
            effective_answer=False,
            hitl=False,
        )
        log_run(
            request_id=request_id,
            query=redact_pii(req.message),
            session_id=conv_id,
            duration_ms=int(latency),
            blocked=False,
            safety_passed=False,
            release_id=_release_id,
            outcome="error",
            error=str(ex),
            exception_type=type(ex).__name__,
            exception_message=str(ex),
            rag_queried=rag_queried,
            rag_hit=rag_hit,
            effective_answer=False,
            hitl_escalated=False,
        )
        logger.exception("Chat 请求失败 request_id=%s", request_id)
        raise HTTPException(500, "服务处理失败，请稍后重试") from ex


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _rag_lite_enabled() -> bool:
    """仅向量检索，跳过查询改写与 LLM 重排。"""
    return _env_bool("RAG_LITE", default=False)


def _rag_preflight_enabled() -> bool:
    return _env_bool("RAG_PREFLIGHT_ENABLED", default=True)


def _pack_rag_hits(
    hits: List[Dict[str, Any]], top_k: int,
) -> tuple[str, List[Dict[str, Any]], bool, Optional[float]]:
    """将检索命中列表转为 (prompt, sources, knowledge_used, top_score)。"""
    from core.prompt_registry import get_registry
    from monitor.metrics import record_rag_empty

    rag_items: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    top_score: Optional[float] = None
    for item in hits[:top_k]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "未命名"))
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        score = float(item.get("score", 0) or 0)
        if top_score is None or score > top_score:
            top_score = score
        rag_items.append({
            "title": title,
            "content": content,
            "doc_type": str(item.get("doc_type", "")),
            "source": str(item.get("source", "")),
            "score": score,
        })
        sources.append({
            "title": title,
            "content": content[:400],
            "doc_type": str(item.get("doc_type", "")),
            "source": str(item.get("source", "")),
            "score": score,
        })
    if not sources:
        record_rag_empty()
        return "", [], False, None
    prompt_text = get_registry().format_rag_context(rag_items)
    return prompt_text, sources, True, top_score


async def _direct_knowledge_hits(
    message: str,
    top_k: int,
    *,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """RAG_LITE：仅向量检索（走 tool 缓存，不触发 rewrite/rerank LLM）。"""
    rag_ctx = {"tenant_id": tenant_id} if tenant_id else None
    if _tool_manager is None:
        return []
    result = await _tool_manager.call(
        "knowledge_search",
        {"query": message, "top_k": top_k, "tenant_id": tenant_id},
        context=rag_ctx,
        use_cache=True,
        rerank_top_k=0,
    )
    if result.success and isinstance(result.data, list):
        return result.data
    if _kb is not None:
        return _kb.search(message, top_k=top_k, tenant_id=tenant_id)
    return []


async def _build_knowledge_context(
    message: str,
    top_k: int = 3,
    *,
    tenant_id: Optional[str] = None,
) -> tuple[str, List[Dict[str, Any]], bool, Optional[float]]:
    """
    返回 (prompt_text, sources, knowledge_used, top_score)。

    Token 优化：
      - RAG_LITE：仅向量检索，无改写/重排 LLM
      - 否则预检 Top-1，未达阈值则跳过 rewrite/rerank
    """
    if _tool_manager is None or not _requires_knowledge_evidence(message):
        return "", [], False, None
    try:
        from core.medical_security import MIN_RETRIEVAL_SCORE
        from core.token_usage import set_rag_mode
        from monitor.metrics import record_rag_empty

        if _rag_lite_enabled():
            set_rag_mode("lite")
            hits = await _direct_knowledge_hits(message, top_k, tenant_id=tenant_id)
            if not hits:
                logger.info("RAG_LITE：无命中")
                record_rag_empty()
                return "", [], False, None
            top_score: Optional[float] = None
            for h in hits:
                if not isinstance(h, dict):
                    continue
                s = float(h.get("score", 0) or 0)
                if top_score is None or s > top_score:
                    top_score = s
            if top_score is None or top_score < MIN_RETRIEVAL_SCORE:
                logger.info(
                    "RAG_LITE：未达阈值 score=%s < %.2f",
                    top_score, MIN_RETRIEVAL_SCORE,
                )
                record_rag_empty()
                return "", [], False, top_score
            return _pack_rag_hits(hits, top_k)

        if _rag_preflight_enabled() and _kb is not None:
            set_rag_mode("full")
            probe = _kb.search(message, top_k=1, tenant_id=tenant_id)
            if not probe:
                logger.info("RAG 预检：无命中，跳过改写/重排")
                record_rag_empty()
                return "", [], False, None
            probe_score = float(probe[0].get("score", 0) or 0)
            if probe_score < MIN_RETRIEVAL_SCORE:
                logger.info(
                    "RAG 预检未达阈值 score=%.4f < %.2f，跳过改写/重排",
                    probe_score, MIN_RETRIEVAL_SCORE,
                )
                record_rag_empty()
                return "", [], False, probe_score

        set_rag_mode("full")
        rag_ctx = {"tenant_id": tenant_id} if tenant_id else None
        result = await _tool_manager.search_with_rewrite(
            "knowledge_search", message, top_k=top_k, context=rag_ctx,
        )
        if not result.success or not isinstance(result.data, list) or not result.data:
            record_rag_empty()
            return "", [], False, None

        return _pack_rag_hits(result.data, top_k)
    except Exception as ex:
        logger.warning("RAG 构建失败: %s", ex)
        return "", [], False, None


def _requires_knowledge_evidence(message: str) -> bool:
    """需要知识库依据才允许 Agent 生成（Evidence-first）。"""
    msg = (message or "").strip().lower()
    if not msg:
        return False
    greetings = {"你好", "您好", "hi", "hello", "嗨"}
    if msg in greetings:
        return False
    keywords = [
        "症状", "挂", "科", "科室", "导诊", "报告", "指标", "体检", "化验",
        "alt", "ast", "血压", "血糖", "偏高", "偏低", "异常", "检查", "挂号",
    ]
    return len(msg) >= 4 or any(kw in msg for kw in keywords)


@app.get("/eval/safety")
async def eval_safety(auth: AuthContext = Depends(require_readonly_auth)):
    """本地安全回归（规则层，不调用 LLM）。"""
    from evaluation.safety_runner import run_all
    return run_all()


@app.get("/monitor")
async def monitor_summary(auth: AuthContext = Depends(require_readonly_auth)):
    if _monitor is None:
        raise HTTPException(503, "Monitor 未就绪")
    return _monitor.summary()


@app.post("/search")
async def search(
    query: str,
    top_k: int = 5,
    auth: AuthContext = Depends(require_chat_auth),
):
    if _tool_manager is None:
        raise HTTPException(503, "服务未就绪")
    tenant_id = auth.tenant_id
    rag_ctx = {"tenant_id": tenant_id}
    if _rag_lite_enabled():
        hits = await _direct_knowledge_hits(query, top_k, tenant_id=tenant_id)
        return {"query": query, "results": hits, "reranked": False, "mode": "lite", "tenant_id": tenant_id}
    result = await _tool_manager.search_with_rewrite(
        "knowledge_search", query, top_k=top_k, context=rag_ctx,
    )
    return {
        "query": query,
        "results": result.data or [],
        "reranked": result.reranked,
        "mode": "full",
        "tenant_id": tenant_id,
    }


@app.post("/knowledge/add")
async def add_knowledge(
    body: BatchDocInput,
    auth: AuthContext = Depends(require_admin_auth),
):
    global _release_id
    if _kb is None:
        raise HTTPException(503, "知识库未就绪")
    docs = [d.model_dump() for d in body.documents]
    tenant_id = auth.tenant_id
    count = _kb.add_documents(docs, tenant_id=tenant_id)
    from observability import get_release_id
    from monitor.metrics import set_knowledge_chunks

    _release_id = get_release_id(_kb.doc_count)
    set_knowledge_chunks(_kb.doc_count)
    return {
        "added_chunks": count,
        "total": _kb.doc_count,
        "release_id": _release_id,
        "tenant_id": tenant_id,
    }


@app.post("/knowledge/import")
async def import_knowledge(
    body: KnowledgeImportInput,
    auth: AuthContext = Depends(require_admin_auth),
):
    """批量导入目录下的 md/txt/json/jsonl 到向量库。"""
    global _release_id
    if _kb is None:
        raise HTTPException(503, "知识库未就绪")

    from config import KNOWLEDGE_DIR, ROOT

    raw_dir = body.directory or str(KNOWLEDGE_DIR)
    dir_path = pathlib.Path(raw_dir)
    if not dir_path.is_absolute():
        dir_path = (ROOT / dir_path).resolve()
    if not dir_path.is_dir():
        raise HTTPException(400, f"目录不存在: {dir_path}")

    result = _kb.import_from_directory(str(dir_path), recursive=body.recursive, tenant_id=auth.tenant_id)
    from observability import get_release_id
    from monitor.metrics import set_knowledge_chunks

    _release_id = get_release_id(_kb.doc_count)
    set_knowledge_chunks(_kb.doc_count)
    result["release_id"] = _release_id
    result["directory"] = str(dir_path)
    return result


@app.get("/prompts")
async def prompts_summary(auth: AuthContext = Depends(require_readonly_auth)):
    from core.prompt_registry import get_registry
    return get_registry().summary()


@app.post("/prompts/reload")
async def reload_prompts(auth: AuthContext = Depends(require_admin_auth)):
    from core.prompt_registry import reload_registry
    return reload_registry().summary()


@app.get("/skills")
async def skills_summary(auth: AuthContext = Depends(require_readonly_auth)):
    if _skill_manager is None:
        raise HTTPException(503, "Skills 未初始化")
    return _skill_manager.summary()


@app.post("/skills/reload")
async def reload_skills(auth: AuthContext = Depends(require_admin_auth)):
    if _skill_manager is None or _orchestrator is None:
        raise HTTPException(503, "Skills 未初始化")
    _skill_manager.reload()
    _orchestrator.set_skill_manager(_skill_manager)
    return _skill_manager.summary()


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8010")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
