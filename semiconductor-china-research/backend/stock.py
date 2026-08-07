"""Block 3C · A/H 股行情快照 stock_snapshot。

优先 akshare 拉取最新价/市值/PE(带 as_of 时间戳);失败则返回空串,由 ddgs 兜底。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .config import ENABLE_STOCK_SNAPSHOT, ENABLE_INDUSTRY_KB

_CODE6 = re.compile(r"\b(\d{6})\b")
_MAX_SYMBOLS = 5

# 全市场 spot 缓存(单次请求内复用,避免重复拉取)
_spot_cache: dict[str, Any] = {}


def akshare_available() -> bool:
    try:
        import akshare  # noqa: F401
        return True
    except ImportError:
        return False


def normalize_code6(symbol: str) -> str | None:
    """002371 / 002371.SZ → 6 位代码。"""
    s = (symbol or "").strip().upper()
    if not s:
        return None
    if "." in s:
        s = s.split(".")[0]
    if s.isdigit() and len(s) == 6:
        return s
    m = _CODE6.search(s)
    return m.group(1) if m else None


def resolve_symbols(task: str) -> list[str]:
    """从 task 提取 6 位代码 + KB 公司名映射(最多 5 个)。"""
    found: list[str] = []
    for c in _CODE6.findall(task):
        if c not in found:
            found.append(c)
    if ENABLE_INDUSTRY_KB:
        try:
            from .kb import _match_listed_names  # noqa: WPS433

            for row in _match_listed_names(task):
                c = normalize_code6(row.get("symbol", ""))
                if c and c not in found:
                    found.append(c)
        except Exception:
            pass
    return found[:_MAX_SYMBOLS]


def _as_of() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_a_spot():
    if "a_spot" in _spot_cache:
        return _spot_cache["a_spot"]
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    _spot_cache["a_spot"] = df
    return df


def _load_hk_spot():
    if "hk_spot" in _spot_cache:
        return _spot_cache["hk_spot"]
    import akshare as ak

    df = ak.stock_hk_spot_em()
    _spot_cache["hk_spot"] = df
    return df


def clear_spot_cache() -> None:
    _spot_cache.clear()


def _fetch_a_share(code6: str) -> dict[str, Any] | None:
    try:
        df = _load_a_spot()
        row = df[df["代码"] == code6]
        if row.empty:
            return None
        r = row.iloc[0]
        pe = r.get("市盈率-动态")
        if pe is not None and str(pe) in ("-", "nan", "NaN"):
            pe = None
        return {
            "code": code6,
            "name": str(r.get("名称", "")),
            "price": r.get("最新价"),
            "pe": pe,
            "market_cap": r.get("总市值"),
            "change_pct": r.get("涨跌幅"),
            "market": "A",
            "as_of": _as_of(),
            "source": "akshare/stock_zh_a_spot_em",
        }
    except Exception:
        return None


def _fetch_hk(code: str) -> dict[str, Any] | None:
    """港股 5 位代码,如 00981 / 01347。"""
    try:
        hk = code.lstrip("0") or code
        df = _load_hk_spot()
        # akshare 港股代码列通常为 5 位字符串
        row = df[df["代码"].astype(str).str.lstrip("0") == hk.lstrip("0")]
        if row.empty:
            row = df[df["代码"].astype(str) == code.zfill(5)]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "code": str(r.get("代码", code)),
            "name": str(r.get("名称", "")),
            "price": r.get("最新价"),
            "pe": r.get("市盈率"),
            "market_cap": r.get("总市值"),
            "change_pct": r.get("涨跌幅"),
            "market": "HK",
            "as_of": _as_of(),
            "source": "akshare/stock_hk_spot_em",
        }
    except Exception:
        return None


def _lookup_exchange(code6: str) -> str | None:
    if not ENABLE_INDUSTRY_KB:
        return "A"
    try:
        from .kb import lookup_by_symbol

        rows = lookup_by_symbol(code6)
        if rows:
            ex = rows[0].get("exchange", "")
            return "HK" if ex == "HK" else "A"
    except Exception:
        pass
    return "A"


def fetch_snapshot(code6: str) -> dict[str, Any] | None:
    """单只标的快照;A 股优先,KB 标注 HK 时走港股接口。"""
    if _lookup_exchange(code6) == "HK":
        # KB 中 981.HK → 尝试 981 / 00981
        for hk in (code6.lstrip("0"), code6.zfill(5)):
            snap = _fetch_hk(hk)
            if snap:
                return snap
    return _fetch_a_share(code6)


def fetch_snapshots(codes: list[str]) -> list[dict[str, Any]]:
    clear_spot_cache()
    out: list[dict[str, Any]] = []
    for raw in codes:
        c = normalize_code6(raw)
        if not c:
            continue
        snap = fetch_snapshot(c)
        if snap:
            out.append(snap)
    return out


def format_snapshot_text(snaps: list[dict[str, Any]]) -> str:
    if not snaps:
        return ""
    lines = [
        "【行情快照 · 数据来源 akshare,以下数值须标注 as_of 日期;不构成投资建议】",
    ]
    for s in snaps:
        pe = s.get("pe")
        pe_s = f"{pe}" if pe is not None else "未披露/亏损"
        cap = s.get("market_cap")
        cap_s = f"{cap}" if cap is not None else "—"
        lines.append(
            f"- {s.get('name')} ({s.get('code')}) · 市场:{s.get('market','A')} · "
            f"最新价:{s.get('price')} · PE(动态):{pe_s} · 总市值:{cap_s} · "
            f"涨跌幅:{s.get('change_pct', '—')}% · as_of:{s.get('as_of')}"
        )
    return "\n".join(lines)


def stock_snapshot(symbols: str) -> tuple[str, list[dict[str, Any]]]:
    """symbols: 逗号分隔 6 位代码。返回 (格式化文本, 结构化列表)。"""
    if not ENABLE_STOCK_SNAPSHOT or not akshare_available():
        return "", []
    codes = [normalize_code6(x) for x in symbols.split(",") if normalize_code6(x)]
    snaps = fetch_snapshots(codes)
    return format_snapshot_text(snaps), snaps


def stock_snapshot_for_task(task: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    """按 task 解析代码并拉快照。"""
    if not ENABLE_STOCK_SNAPSHOT or not akshare_available():
        return "", [], []
    if not (needs_stock_context(task) or resolve_symbols(task)):
        return "", [], []
    codes = resolve_symbols(task)
    if not codes:
        return "", [], []
    snaps = fetch_snapshots(codes)
    return format_snapshot_text(snaps), snaps, codes


def needs_stock_context(task: str) -> bool:
    """是否应尝试行情快照(含估值/股价关键词或已解析出代码)。"""
    kw = ("股", "上市", "估值", "PE", "pe", "财报", "市值", "股价", "ipo", "IPO", "贵不贵", "市盈率")
    return any(k in task for k in kw) or bool(_CODE6.search(task))
