"""工具层:web_search + 按专家细化的确定性检索策略(Block 3A)。

【设计原则】
专家不 agentic 自主搜 —— 编排层按 SEARCH_STRATEGY 确定性取数,结果直接塞进 prompt。
检索过程发 search_start / search 事件;SEARCH_BUDGET 每专家每轮 ≤ MAX_SEARCH_PER_EXPERT。
"""
import asyncio
from ddgs import DDGS

from .runtime import EVENT_Q, SEARCH_LOG, SEARCH_SNIPPETS, SEARCH_BUDGET, _ms
from .kb import kb_lookup_for_expert
from .stock import stock_snapshot_for_task, akshare_available
from .config import ENABLE_INDUSTRY_KB, ENABLE_STOCK_SNAPSHOT

MAX_SEARCH_PER_EXPERT = 3
DEFAULT_REGION = "cn-zh"
DEFAULT_TIMELIMIT = "y"

# investment 双 query 触发词
STOCK_KW = ("股", "上市", "估值", "PE", "pe", "财报", "市值", "股价", "ipo", "IPO", "贵不贵", "市盈率")

# 各专家检索策略(单一真相源)
# timelimit: "y"=近一年 | None=不限(tech_roadmap 长期演变)
# primary_extra_region: 首轮额外区域(如 risk_supply 中外双视角)
# retry_region: 无效重搜时使用的区域(equipment/design_ip 补英文技术源)
SEARCH_STRATEGY = {
    "policy_expert": {
        "timelimit": "y",
        "query": lambda task: f"中国半导体 {task} 政策 出口管制 信创 国产化",
    },
    "manufacturing_expert": {
        "timelimit": "y",
        "query": lambda task: f"中国半导体 {task} 晶圆 产能 制程 Foundry OSAT",
    },
    "design_ip_expert": {
        "timelimit": "y",
        "retry_region": "wt-wt",
        "query": lambda task: f"中国半导体 {task} EDA IP Fabless SoC 设计",
        "retry_query": lambda task: f"semiconductor {task} EDA IP design China localization",
    },
    "equipment_materials_expert": {
        "timelimit": "y",
        "retry_region": "wt-wt",
        "query": lambda task: f"中国半导体 {task} 设备 材料 光刻 刻蚀 国产化率",
        "retry_query": lambda task: f"semiconductor equipment materials {task} lithography etch China",
    },
    "competitor_expert": {
        "timelimit": "y",
        "query": lambda task: f"中国半导体 {task} 市场份额 头部企业 竞争格局",
    },
    "tech_roadmap_expert": {
        "timelimit": None,
        "query": lambda task: f"半导体 {task} 技术路线 先进制程 Chiplet AI芯片",
    },
    "risk_supply_expert": {
        "timelimit": "y",
        "primary_extra_region": "wt-wt",
        "primary_extra_query": lambda task: f"semiconductor {task} supply chain sanctions export control",
        "retry_region": "wt-wt",
        "query": lambda task: f"中国半导体 {task} 供应链 断供 国产替代 制裁",
    },
    "investment_expert": {
        "timelimit": "y",
        "dual_query": True,
        "query": lambda task: f"中国半导体 {task} 国家大基金 地方补贴 IPO 产业政策",
        "stock_query": lambda task: f"半导体 {task} 市值 PE 估值 财报 A股",
        "retry_stock_query": lambda task: f"半导体 {task} PE 市值 财报 2025 2026",
        "retry_policy_query": lambda _: "国家集成电路产业投资基金 三期 投向 2024 2025 2026",
    },
}


def needs_stock_search(task: str) -> bool:
    return any(k in task for k in STOCK_KW)


def _strategy(expert: str) -> dict:
    return SEARCH_STRATEGY.get(expert, {"timelimit": DEFAULT_TIMELIMIT, "query": lambda t: t})


def _timelimit(expert: str):
    return _strategy(expert).get("timelimit", DEFAULT_TIMELIMIT)


def _ddgs(query: str, n: int = 4, region: str = DEFAULT_REGION, timelimit=DEFAULT_TIMELIMIT):
    """同步 ddgs 检索 → (纯文本, 条数, 结构化条目)。"""
    try:
        rs = list(DDGS().text(query, max_results=n, region=region, timelimit=timelimit)) if timelimit else []
        if not rs:
            rs = list(DDGS().text(query, max_results=n, region=region))
    except Exception as e:
        return f"(搜索失败: {type(e).__name__}: {e})", 0, []
    items = [
        {"title": r.get("title", ""), "href": r.get("href", ""),
         "body": (r.get("body", "") or "")[:200]}
        for r in rs
    ]
    text = "\n".join(
        f"[{i+1}] {it['title']}\n{it['body']}\n来源: {it['href']}"
        for i, it in enumerate(items)
    )
    return text or "(无结果)", len(items), items


async def web_search(
    tag: str,
    query: str,
    region: str = DEFAULT_REGION,
    timelimit=DEFAULT_TIMELIMIT,
) -> str:
    """单次确定性检索:预算控制 + SSE 事件 + 参考来源记录。"""
    budget = SEARCH_BUDGET.get()
    rec = None
    if budget is not None:
        rec = budget.setdefault(tag, {"n": 0, "last": ""})
        if rec["n"] >= MAX_SEARCH_PER_EXPERT:
            return rec["last"] or "(该维度已多次检索,无更多相关结果)"
        rec["n"] += 1

    q = EVENT_Q.get()
    if q is not None:
        await q.put({
            "event": "search_start", "expert": tag, "query": query,
            "region": region, "timelimit": timelimit, "t": _ms(),
        })

    text, n, items = await asyncio.to_thread(_ddgs, query, 4, region, timelimit)

    if q is not None:
        await q.put({
            "event": "search", "expert": tag, "query": query, "n": n,
            "region": region, "items": items, "t": _ms(),
        })

    log = SEARCH_LOG.get()
    if log is not None:
        for it in items:
            if it.get("href"):
                log.append({"title": it.get("title", ""), "href": it["href"]})

    snippets = SEARCH_SNIPPETS.get()
    if snippets is not None and text and not text.startswith("(搜索失败"):
        snippets.append(text[:800])

    if rec is not None:
        rec["last"] = text
    return text


async def _run_queries(expert: str, queries: list[tuple[str, str, str | None]], labels: list[str] | None = None) -> str:
    """按序执行多条检索并合并(带可选分段标签)。"""
    parts = []
    for i, (query, region, tl) in enumerate(queries):
        block = await web_search(expert, query, region=region, timelimit=tl)
        if labels and i < len(labels) and labels[i]:
            parts.append(f"【{labels[i]}】\n{block}")
        else:
            parts.append(block)
    return "\n\n".join(parts)


async def _maybe_kb_prefix(expert: str, task: str) -> str:
    """Block 3B · 检索前注入本地 KB 摘要(仍走 web_search 补充时效)。"""
    if not ENABLE_INDUSTRY_KB:
        return ""
    block = kb_lookup_for_expert(expert, task)
    if not block:
        return ""
    q = EVENT_Q.get()
    if q is not None:
        await q.put({"event": "kb_hit", "expert": expert, "chars": len(block), "t": _ms()})
    return block + "\n\n"


async def _maybe_stock_snapshot(expert: str, task: str) -> str:
    """Block 3C · investment 等场景注入 akshare 行情快照。"""
    if not ENABLE_STOCK_SNAPSHOT or expert != "investment_expert":
        return ""
    text, snaps, codes = await asyncio.to_thread(stock_snapshot_for_task, task)
    if not text:
        return ""
    q = EVENT_Q.get()
    if q is not None:
        await q.put({
            "event": "stock_snapshot",
            "expert": expert,
            "symbols": codes,
            "count": len(snaps),
            "as_of": snaps[0].get("as_of") if snaps else None,
            "provider": "akshare" if akshare_available() else None,
            "t": _ms(),
        })
    return text + "\n\n"


async def fetch_for_expert(expert: str, task: str) -> str:
    """首轮检索:KB + 行情快照(可选) + 按 SEARCH_STRATEGY 为各专家取数。"""
    kb_block = await _maybe_kb_prefix(expert, task)
    stock_block = await _maybe_stock_snapshot(expert, task)
    prefix = kb_block + stock_block
    st = _strategy(expert)
    tl = st.get("timelimit", DEFAULT_TIMELIMIT)

    if expert == "investment_expert" and st.get("dual_query"):
        queries = [(st["query"](task), DEFAULT_REGION, tl)]
        labels = ["政策/资金检索"]
        if needs_stock_search(task):
            queries.append((st["stock_query"](task), DEFAULT_REGION, tl))
            labels.append("个股/估值检索")
        return prefix + await _run_queries(expert, queries, labels)

    if st.get("primary_extra_region"):
        queries = [
            (st["query"](task), DEFAULT_REGION, tl),
            (st["primary_extra_query"](task), st["primary_extra_region"], tl),
        ]
        return prefix + await _run_queries(expert, queries, ["国内视角", "全球视角"])

    query = st["query"](task) if callable(st.get("query")) else task
    return prefix + await web_search(expert, query, region=DEFAULT_REGION, timelimit=tl)


async def retry_for_expert(expert: str, task: str) -> str:
    """无效结论时的聚焦重搜。"""
    st = _strategy(expert)
    tl = st.get("timelimit", DEFAULT_TIMELIMIT)

    if expert == "investment_expert":
        if needs_stock_search(task):
            q = st["retry_stock_query"](task)
        else:
            q = st["retry_policy_query"](task)
        return await web_search(expert, q, region=DEFAULT_REGION, timelimit=tl)

    region = st.get("retry_region", "wt-wt")
    if callable(st.get("retry_query")):
        query = st["retry_query"](task)
    elif callable(st.get("query")):
        query = st["query"](task)
    else:
        query = task
    return await web_search(expert, query, region=region, timelimit=tl)


def search_strategy_info(expert: str) -> dict:
    """/api/agents 或调试:返回某专家的检索策略摘要。"""
    st = _strategy(expert)
    info = {
        "expert": expert,
        "timelimit": st.get("timelimit", DEFAULT_TIMELIMIT),
        "primary_region": DEFAULT_REGION,
        "max_per_round": MAX_SEARCH_PER_EXPERT,
    }
    if st.get("dual_query"):
        info["mode"] = "dual_query"
        info["stock_trigger"] = list(STOCK_KW)
    elif st.get("primary_extra_region"):
        info["mode"] = "dual_region"
        info["extra_region"] = st["primary_extra_region"]
    elif st.get("retry_region"):
        info["mode"] = "cn-zh_then_retry_wt-wt"
        info["retry_region"] = st["retry_region"]
    else:
        info["mode"] = "cn-zh"
    return info


def list_search_strategies() -> list[dict]:
    """返回全部 8 专家的检索策略摘要(供 /api/search-strategies)。"""
    return [search_strategy_info(k) for k in SEARCH_STRATEGY]
