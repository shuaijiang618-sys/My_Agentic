"""Phase 3 · 事实校验 + 合规过滤(M3.1 / M3.2)。"""
from __future__ import annotations

import re
from typing import Any

from .config import ENABLE_FACT_CHECK, ENABLE_COMPLIANCE_FILTER, ENABLE_COMPLIANCE_RESCAN

_URL_RE = re.compile(r"https?://[^\s\)\]\>\"']+")

# 11B · 禁止买卖建议类表述(命中则替换并记录)
_FORBIDDEN_PHRASES = (
    "建议买入", "建议卖出", "强烈推荐", "强烈建议买入", "强烈建议卖出",
    "立即买入", "立即卖出", "马上买入", "马上卖出", "目标价", "必涨", "必跌",
    "稳赚", "抄底", "上车", "梭哈", "All in", "all in",
)

_INVESTMENT_Q_KW = ("估值", "股价", "PE", "pe", "市值", "ipo", "IPO", "贵不贵", "大基金", "市盈率")

# M3.2 · 二次合规扫描(正则,比短语列表更宽)
_RESCAN_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"保证.*(?:涨|赚|收益|翻倍)"), "收益承诺"),
    (re.compile(r"零风险|无风险稳赚|稳赚不赔"), "零风险表述"),
    (re.compile(r"(?:内幕|未公开).{0,6}(?:消息|信息)"), "内幕消息暗示"),
    (re.compile(r"(?:国家机密|涉密).{0,4}(?:泄露|透露)"), "敏感信息暗示"),
)


def _normalize_url(u: str) -> str:
    return u.rstrip(".,;)")


def check_facts(
    brief: str,
    search_log: list[dict[str, Any]],
    snippets: list[str],
    expert_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """11A · 启发式事实校验:未收录 URL、缺日期估值、检索覆盖不足。"""
    if not ENABLE_FACT_CHECK:
        return {"enabled": False, "passed": True, "warnings": []}

    warnings: list[str] = []
    refs_idx = brief.find("## 📎 参考来源")
    body = brief[:refs_idx] if refs_idx >= 0 else brief

    known_hrefs = {_normalize_url(x["href"]) for x in search_log if x.get("href")}
    body_urls = [_normalize_url(u) for u in _URL_RE.findall(body)]
    rogue_urls = [u for u in body_urls if u not in known_hrefs]
    if rogue_urls:
        warnings.append(f"正文含 {len(rogue_urls)} 个未在检索记录中的 URL(可能编造)")

    corpus = " ".join(snippets) + " " + " ".join(
        e.get("output", "") for e in (expert_results or [])
    )
    if search_log and len(corpus.strip()) < 80:
        warnings.append("检索摘要过短,事实依据可能不足")

    if any(k in brief for k in ("PE", "pe", "市盈率", "市值", "股价")):
        has_date = bool(re.search(r"20\d{2}|as_of|报告期|季度|年报", brief))
        if not has_date:
            warnings.append("含估值/股价表述但未见明确日期或报告期")

    passed = len(warnings) == 0
    return {
        "enabled": True,
        "passed": passed,
        "warnings": warnings,
        "rogue_urls": rogue_urls[:5],
        "search_refs": len(known_hrefs),
    }


def apply_compliance(brief: str, query: str = "") -> tuple[str, dict[str, Any]]:
    """11B · 合规过滤 + 投资免责。"""
    flags: list[str] = []
    text = brief

    if ENABLE_COMPLIANCE_FILTER:
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in text:
                flags.append(phrase)
                text = text.replace(phrase, "【表述已合规处理】")

    disclaimer_needed = any(k in query for k in _INVESTMENT_Q_KW) or any(
        k in text for k in ("估值", "股价", "PE", "市值")
    )
    if disclaimer_needed and "不构成投资建议" not in text:
        text = text.rstrip() + "\n\n> 以上内容基于公开资料整理，不构成投资建议。"

    return text, {
        "enabled": ENABLE_COMPLIANCE_FILTER,
        "flags": flags,
        "disclaimer_appended": disclaimer_needed and "不构成投资建议" in text,
    }


def rescan_compliance(brief: str) -> tuple[str, dict[str, Any]]:
    """M3.2 · 二次合规扫描:正则命中 → 替换并记录。"""
    if not ENABLE_COMPLIANCE_RESCAN:
        return brief, {"enabled": False, "hits": []}

    hits: list[str] = []
    text = brief
    for pattern, label in _RESCAN_RULES:
        if pattern.search(text):
            hits.append(label)
            text = pattern.sub("【表述已合规处理】", text)
    return text, {"enabled": True, "hits": hits, "passed": len(hits) == 0}


def postprocess_brief(
    brief: str,
    query: str,
    search_log: list[dict[str, Any]],
    snippets: list[str],
    expert_results: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """合规 → 二次扫描 → 事实校验,返回 (新简报, 质量元数据)。"""
    brief, compliance = apply_compliance(brief, query)
    brief, rescan = rescan_compliance(brief)
    fact = check_facts(brief, search_log, snippets, expert_results)
    return brief, {
        "compliance": compliance,
        "compliance_rescan": rescan,
        "fact_check": fact,
    }
