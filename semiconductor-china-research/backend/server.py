"""接口层:所有 HTTP API 路由(APIRouter,由 app.py 主入口挂载)。

简单查询型接口(health / agents / conversations / 删除)都是一行转发给 store 或 agent。
重点是 /api/run —— 一次研究编排的流式 SSE 编排,下面详注。
"""
import time
import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .config import (
    MODEL, BASE_URL, PORT, ENABLE_INDUSTRY_KB, ENABLE_STOCK_SNAPSHOT,
    ENABLE_FACT_CHECK, ENABLE_COMPLIANCE_FILTER, ENABLE_COMPLIANCE_RESCAN,
    ENABLE_PDF_EXPORT, ENABLE_OBSERVABILITY_LOG, LLM_RETRY_MAX,
)
from .runtime import EVENT_Q, T0, SEARCH_LOG, SEARCH_SNIPPETS, SEARCH_BUDGET, EXPERT_RESULTS, _ms, sse
from .agent import (
    WORKERS, supervisor, synthesizer, agent_info_supervisor, agent_info_worker,
    SUP_INSTRUCTIONS, REPORT_TEMPLATE,
)
from .prompts import EXPERT_TOOLS, load_prompt
from .tool import list_search_strategies, MAX_SEARCH_PER_EXPERT
from .kb import kb_stats, knowledge_search
from .stock import stock_snapshot, akshare_available
from .llm_retry import run_with_retry
from .quality import postprocess_brief
from .export import export_session_markdown, export_session_pdf
from .observability import new_request_id, log_run, recent_runs, aggregate_stats
from . import store

router = APIRouter()


def _friendly_api_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "401" in msg or "authentication" in msg or "invalid api key" in msg:
        return "DeepSeek API 认证失败:请检查 .env 中 DEEPSEEK_API_KEY 是否有效"
    if "429" in msg or "rate limit" in msg or "too many" in msg:
        return "DeepSeek API 限流(429):请稍后重试或减少并行专家数量"
    if "402" in msg or "insufficient" in msg or "balance" in msg:
        return "DeepSeek 账户余额不足:请在 platform.deepseek.com 充值"
    return f"{type(exc).__name__}: {exc}"


@router.get("/api/health")
async def health():
    """健康检查 + 暴露这套 demo 的关键参数(框架/模型/专家数)。"""
    return {"ok": True, "pattern": "supervisor-as-tool", "framework": "Microsoft Agent Framework 1.8",
            "provider": "deepseek", "model": MODEL, "base_url": BASE_URL, "port": PORT,
            "experts": len(WORKERS), "memory": True,
            "memory_turn_limit": store.MEMORY_TURN_LIMIT,
            "search": "ddgs", "search_budget_per_expert": MAX_SEARCH_PER_EXPERT, "exec": "parallel",
            "knowledge_base": ENABLE_INDUSTRY_KB,
            "kb_stats": kb_stats() if ENABLE_INDUSTRY_KB else None,
            "stock_snapshot": ENABLE_STOCK_SNAPSHOT,
            "stock_provider": "akshare" if (ENABLE_STOCK_SNAPSHOT and akshare_available()) else None,
            "fact_check": ENABLE_FACT_CHECK,
            "compliance_filter": ENABLE_COMPLIANCE_FILTER,
            "compliance_rescan": ENABLE_COMPLIANCE_RESCAN,
            "pdf_export": ENABLE_PDF_EXPORT,
            "observability_log": ENABLE_OBSERVABILITY_LOG,
            "llm_retry_max": LLM_RETRY_MAX,
            "sse_events": [
                "start", "tool_call", "kb_hit", "stock_snapshot",
                "search_start", "search", "tool_done",
                "fact_check", "compliance", "compliance_rescan", "final", "error",
            ]}


@router.get("/api/prompts")
async def prompts_index():
    """Block 7 · 提示词文件索引(不含全文,防过大)。"""
    return {
        "supervisor": "prompts/supervisor.md",
        "synthesizer": "prompts/synthesizer.md",
        "report_template": "prompts/report_template.md",
        "experts": [f"prompts/{t}.md" for t in EXPERT_TOOLS],
        "supervisor_chars": len(SUP_INSTRUCTIONS),
        "report_template_chars": len(REPORT_TEMPLATE),
    }


@router.get("/api/prompts/{name}")
async def prompt_detail(name: str):
    """返回单个提示词全文(supervisor / synthesizer / report_template / 专家 tool 名)。"""
    allowed = {"supervisor", "synthesizer", "report_template", *EXPERT_TOOLS}
    if name not in allowed:
        return {"error": f"unknown prompt: {name}", "allowed": sorted(allowed)}
    return {"name": name, "content": load_prompt(name)}


@router.get("/api/search-strategies")
async def search_strategies():
    """返回 8 专家检索策略摘要(Block 3A · SEARCH_STRATEGY)。"""
    return {"strategies": list_search_strategies()}


@router.get("/api/knowledge")
async def knowledge(q: str = "", segment: str = "", limit: int = 20):
    """Block 3B · 本地产业知识库查询(预览/调试)。

    - 无参数: 返回 stats + segments 列表
    - ?segment=equipment: 按产业链环节查上市标的
    - ?q=北方华创 / 002371 / 大基金: 模糊查询
    """
    if not ENABLE_INDUSTRY_KB:
        return {"enabled": False, "message": "ENABLE_INDUSTRY_KB=false"}
    return {"enabled": True, **knowledge_search(q=q, segment=segment, limit=min(limit, 50))}


@router.get("/api/stock-snapshot")
async def stock_snapshot_api(symbols: str = ""):
    """Block 3C · 行情快照(akshare)。symbols=002371,688981"""
    if not ENABLE_STOCK_SNAPSHOT:
        return {"enabled": False, "message": "ENABLE_STOCK_SNAPSHOT=false"}
    if not akshare_available():
        return {"enabled": True, "ok": False, "message": "akshare 未安装 — pip install akshare"}
    if not symbols.strip():
        return {"enabled": True, "ok": False, "message": "请提供 symbols=002371,688981"}
    text, snaps = stock_snapshot(symbols)
    return {
        "enabled": True,
        "ok": bool(snaps),
        "symbols": symbols,
        "snapshots": snaps,
        "text": text,
        "provider": "akshare",
    }


@router.get("/api/export")
async def export_report(session: str, format: str = "md"):
    """Phase 3 · 导出会话最新简报。format=md|pdf"""
    fmt = (format or "md").lower()
    if fmt == "pdf":
        if not ENABLE_PDF_EXPORT:
            return {"error": "ENABLE_PDF_EXPORT=false", "session": session}
        pdf, meta = export_session_pdf(session)
        if pdf is None:
            return meta
        from fastapi.responses import Response
        filename = f"research-{session[:16]}.pdf"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    md, meta = export_session_markdown(session)
    if md is None:
        return meta
    from fastapi.responses import Response
    filename = f"research-{session[:16]}.md"
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/stats")
async def stats():
    """Phase 3 M3.3 · 运维观测: DB + JSONL 汇总。"""
    return {
        "db": store.db_stats(),
        "observability": aggregate_stats(),
        "recent": recent_runs(limit=10),
    }


@router.get("/api/agents")
async def agents():
    """前端点节点时,查看总管 / 各专家的系统提示词 + 工具列表。"""
    return {"supervisor": agent_info_supervisor(),
            "workers": [agent_info_worker(w) for w in WORKERS]}


@router.get("/api/conversations")
async def conversations():
    """历史对话列表(左侧下拉)。"""
    return store.list_conversations()


@router.get("/api/conversation/{session}")
async def conversation(session: str):
    """某个会话的全部轮次(含事件流,供前端复现动画)。"""
    return store.get_conversation(session)


@router.delete("/api/conversation/{session}")
async def delete_conversation(session: str):
    """删除某个历史会话。"""
    return {"ok": True, "deleted": session, "rows": store.delete_conversation(session)}


@router.get("/api/run")
async def run(query: str, session: str = "default"):
    """一次研究编排,以 SSE 流式返回全过程事件(Block 4 · 生产者-消费者)。"""
    query = (query or "").strip()
    if not query:
        async def empty_err():
            yield sse("error", {"message": "query 不能为空", "t": 0})
        return StreamingResponse(empty_err(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    session = (session or "default").strip() or "default"

    async def gen():
        request_id = new_request_id()
        # 初始化本次请求的"隐式上下文"(见 runtime.py):起点时间 / 事件队列 / 参考来源收集器
        T0.set(time.time())
        q = asyncio.Queue()
        EVENT_Q.set(q)
        SEARCH_LOG.set([])
        SEARCH_SNIPPETS.set([])
        SEARCH_BUDGET.set({})
        EXPERT_RESULTS.set([])  # 收集各专家完整结论(综合正文缺失时做兜底综合)
        events = []   # 同时留一份完整事件,结束后落库供"历史复现"
        run_error: str | None = None

        async def producer():
            nonlocal run_error
            try:
                # 第一帧:告诉前端开跑了 + 有哪些专家(画初始的节点网格)
                await q.put({
                    "event": "start", "query": query, "supervisor": "research_supervisor",
                    "workers": WORKERS, "session": session, "request_id": request_id, "t": 0,
                })

                # ── 多轮记忆:从 SQLite 重建上下文(不靠进程内存 → 服务重启也不丢)──
                # 把该会话前几轮的「问题 + 结论摘要」拼到本轮问题前面,总管就能理解追问。
                model_input = query
                hist = store.load_history(session)
                if hist:
                    ctx = ("【与你之前几轮对话的回顾(供追问参考;其中的「它们/其中/哪个」指这些讨论过的对象,不是你的工具)】\n"
                           + "\n".join(
                               f"{i+1}. 我问过「{qq}」,你给的结论摘要:{store.brief_summary(b or '')}"
                               for i, (qq, b) in enumerate(hist)
                           ))
                    model_input = ctx + "\n\n【现在的新问题】" + query

                # ── 跑总管:它内部会并行调用选中的专家(各专家的事件在此期间陆续 put 进队列)──
                # max_iterations=3:1 轮并行派发 + (可选)对"结论无效"的专家补派 1 轮 + 1 轮综合。
                result = await run_with_retry(
                    lambda: supervisor.run(
                        model_input,
                        options={"temperature": 0.5},
                        function_invocation_kwargs={"max_iterations": 3},
                    ),
                    label="supervisor",
                )
                brief = getattr(result, "text", None) or str(result)

                # ── 确定性兜底:pro 偶发"思考吃掉综合正文"(text 为空/极短)。
                ers = EXPERT_RESULTS.get() or []
                if len(brief.strip()) < 200 and ers:
                    joined = "\n\n".join(f"【{e['tool']}】\n{e['output']}" for e in ers)

                    async def _synth():
                        return await synthesizer.run(
                            f"用户的问题:{query}\n\n各专家的研究结论:\n{joined}\n\n请直接回答用户的问题(开头先给结论)。",
                            options={"temperature": 0.5},
                        )

                    r2 = await run_with_retry(_synth, label="synthesizer")
                    b2 = getattr(r2, "text", None) or ""
                    if len(b2.strip()) > len(brief.strip()):
                        brief = b2

                # ── 给简报追加「参考来源」──
                # 不让模型自己编 URL(它会瞎编),而是用各专家真实检索命中的网页,按 href 去重后确定性追加。
                log = SEARCH_LOG.get() or []
                seen, refs = set(), []
                for it in log:
                    h = it.get("href")
                    if h and h not in seen:
                        seen.add(h)
                        refs.append(it)
                if refs:
                    lines = "\n".join(f"{i+1}. [{(it['title'] or it['href'])}]({it['href']})" for i, it in enumerate(refs))
                    brief = brief.rstrip() + "\n\n---\n\n## 📎 参考来源\n\n" + lines

                brief, quality_meta = postprocess_brief(
                    brief, query,
                    log,
                    SEARCH_SNIPPETS.get() or [],
                    EXPERT_RESULTS.get() or [],
                )
                await q.put({
                    "event": "fact_check",
                    **quality_meta["fact_check"],
                    "t": _ms(),
                })
                await q.put({
                    "event": "compliance",
                    **quality_meta["compliance"],
                    "t": _ms(),
                })
                await q.put({
                    "event": "compliance_rescan",
                    **quality_meta["compliance_rescan"],
                    "t": _ms(),
                })

                await q.put({
                    "event": "final",
                    "brief": brief,
                    "duration_ms": _ms(),
                    "request_id": request_id,
                    "quality": quality_meta,
                    "t": _ms(),
                })
            except Exception as e:
                run_error = _friendly_api_error(e)
                await q.put({"event": "error", "message": run_error, "request_id": request_id, "t": _ms()})
            finally:
                await q.put(None)   # None = 哨兵,通知消费者"没有更多事件了"

        # 启动生产者(后台跑),消费者在这循环把事件 yield 成 SSE
        asyncio.create_task(producer())
        while True:
            d = await q.get()
            if d is None:           # 收到哨兵 → 结束
                break
            events.append(d)
            # 发给前端:event 字段单独做 SSE 的事件名,其余字段做 data 体
            yield sse(d["event"], {k: v for k, v in d.items() if k != "event"})

        # 整轮结束,落库(供历史列表 / 复现 / 多轮记忆重建)
        final_ev = next((e for e in events if e["event"] == "final"), None)
        brief = final_ev["brief"] if final_ev else ""
        duration_ms = final_ev.get("duration_ms") if final_ev else _ms()
        quality = final_ev.get("quality") if final_ev else None
        experts = list({e["name"] for e in events if e.get("event") == "tool_call" and e.get("name")})
        run_id = store.save_run(
            session, query, events, brief,
            request_id=request_id, duration_ms=duration_ms,
        )
        log_run(
            request_id=request_id,
            session=session,
            query=query,
            duration_ms=duration_ms,
            run_id=run_id,
            quality=quality,
            experts=experts,
            error=run_error,
        )

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
