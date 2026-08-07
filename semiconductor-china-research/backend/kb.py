"""Block 3B · 本地产业知识库 industry_kb.db。

四表:
  listed_semiconductor  ~30 只 A/H 股半导体标的
  fund_events           大基金/地方基金事件
  facilities            晶圆厂/产线(示例)
  policy_events         产业政策/制裁事件(示例)

检索前注入结构化摘要,仍走 ddgs 补充时效信息。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from .config import INDUSTRY_KB_DB, ENABLE_INDUSTRY_KB

_STOCK_CODE = re.compile(r"\b(\d{6})\b")
_SEGMENT_KW = {
    "foundry": ("晶圆", "代工", "foundry", "制造"),
    "osat": ("封测", "osat", "长电", "通富"),
    "equipment": ("设备", "光刻", "刻蚀", "北方华创", "中微"),
    "material": ("材料", "硅片", "光刻胶", "靶材"),
    "eda": ("eda", "EDA", "华大九天", "概伦"),
    "fabless": ("fabless", "设计", "芯片设计"),
    "fabless_ai": ("ai芯片", "寒武纪", "算力芯片"),
    "ip": ("ip核", "IP核", "芯原"),
    "idm": ("idm", "IDM", "华润微"),
    "power_idm": ("士兰微", "功率"),
    "sic": ("sic", "SiC", "碳化硅", "天岳"),
    "power_module": ("模块", "宏微"),
}
_FUND_KW = ("大基金", "产业基金", "引导基金", "集成电路基金", "国家集成电路")


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(INDUSTRY_KB_DB)
    c.row_factory = sqlite3.Row
    return c


def init_schema(conn: sqlite3.Connection | None = None) -> None:
    """建表(幂等)。"""
    own = conn is None
    c = conn or _db()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS listed_semiconductor(
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            exchange TEXT NOT NULL,
            segment TEXT NOT NULL,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_listed_segment ON listed_semiconductor(segment);
        CREATE INDEX IF NOT EXISTS idx_listed_name ON listed_semiconductor(name);

        CREATE TABLE IF NOT EXISTS fund_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            fund_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            amount TEXT,
            target TEXT,
            summary TEXT,
            source_url TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_fund_date ON fund_events(event_date DESC);

        CREATE TABLE IF NOT EXISTS facilities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            facility_name TEXT NOT NULL,
            location TEXT,
            process_node TEXT,
            capacity TEXT,
            status TEXT,
            source_url TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_facilities_company ON facilities(company);

        CREATE TABLE IF NOT EXISTS policy_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_date TEXT NOT NULL,
            title TEXT NOT NULL,
            issuer TEXT,
            category TEXT,
            summary TEXT,
            source_url TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_policy_date ON policy_events(policy_date DESC);
    """)
    if own:
        c.commit()
        c.close()


def kb_stats() -> dict[str, int]:
    """各表行数统计。"""
    if not ENABLE_INDUSTRY_KB:
        return {"enabled": False}
    try:
        c = _db()
        stats = {
            "enabled": True,
            "listed_semiconductor": c.execute("SELECT COUNT(*) FROM listed_semiconductor").fetchone()[0],
            "fund_events": c.execute("SELECT COUNT(*) FROM fund_events").fetchone()[0],
            "facilities": c.execute("SELECT COUNT(*) FROM facilities").fetchone()[0],
            "policy_events": c.execute("SELECT COUNT(*) FROM policy_events").fetchone()[0],
        }
        c.close()
        return stats
    except Exception:
        return {"enabled": True, "error": "db_unavailable"}


def _rows_to_lines(rows: list[sqlite3.Row], fmt) -> list[str]:
    return [fmt(r) for r in rows]


def lookup_by_symbol(code: str) -> list[dict[str, Any]]:
    """6 位代码 → 上市信息(含 .SH/.SZ 后缀匹配)。"""
    c = _db()
    rows = c.execute(
        """SELECT symbol, name, exchange, segment, notes FROM listed_semiconductor
           WHERE symbol LIKE ? OR symbol LIKE ? OR symbol LIKE ?
           ORDER BY symbol LIMIT 5""",
        (f"{code}.%", f"%.{code}", code),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def lookup_by_name(name: str, limit: int = 5) -> list[dict[str, Any]]:
    c = _db()
    rows = c.execute(
        """SELECT symbol, name, exchange, segment, notes FROM listed_semiconductor
           WHERE name LIKE ? ORDER BY name LIMIT ?""",
        (f"%{name}%", limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def lookup_by_segment(segment: str, limit: int = 10) -> list[dict[str, Any]]:
    c = _db()
    rows = c.execute(
        """SELECT symbol, name, exchange, segment FROM listed_semiconductor
           WHERE segment=? ORDER BY name LIMIT ?""",
        (segment, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def lookup_fund_events(limit: int = 5) -> list[dict[str, Any]]:
    c = _db()
    rows = c.execute(
        """SELECT event_date, fund_name, event_type, amount, target, summary, source_url
           FROM fund_events ORDER BY event_date DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def lookup_policy_events(keyword: str = "", limit: int = 5) -> list[dict[str, Any]]:
    c = _db()
    if keyword:
        rows = c.execute(
            """SELECT policy_date, title, issuer, category, summary, source_url
               FROM policy_events
               WHERE title LIKE ? OR summary LIKE ? OR category LIKE ?
               ORDER BY policy_date DESC LIMIT ?""",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()
    else:
        rows = c.execute(
            """SELECT policy_date, title, issuer, category, summary, source_url
               FROM policy_events ORDER BY policy_date DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def lookup_facilities(company: str = "", limit: int = 5) -> list[dict[str, Any]]:
    c = _db()
    if company:
        rows = c.execute(
            """SELECT company, facility_name, location, process_node, capacity, status, source_url
               FROM facilities WHERE company LIKE ? ORDER BY company LIMIT ?""",
            (f"%{company}%", limit),
        ).fetchall()
    else:
        rows = c.execute(
            """SELECT company, facility_name, location, process_node, capacity, status, source_url
               FROM facilities ORDER BY company LIMIT ?""",
            (limit,),
        ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _match_segments(task: str) -> list[str]:
    t = task.lower()
    return [seg for seg, kws in _SEGMENT_KW.items() if any(k.lower() in t or k in task for k in kws)]


def _match_listed_names(task: str) -> list[dict[str, Any]]:
    """任务文本中命中 KB 公司名。"""
    c = _db()
    all_rows = c.execute("SELECT symbol, name, exchange, segment FROM listed_semiconductor").fetchall()
    c.close()
    hits = []
    for r in all_rows:
        if r["name"] and r["name"] in task:
            hits.append(dict(r))
    return hits[:8]


def kb_investment_lookup(task: str) -> str:
    """investment_expert 检索前注入。"""
    parts: list[str] = []

    for code in _STOCK_CODE.findall(task):
        rows = lookup_by_symbol(code)
        if rows:
            parts.append(f"【代码 {code}】")
            for r in rows:
                parts.append(f"- {r['name']} ({r['symbol']}) · {r['exchange']} · segment={r['segment']}")

    for r in _match_listed_names(task):
        parts.append(f"- {r['name']} ({r['symbol']}) · segment={r['segment']}")

    if any(k in task for k in _FUND_KW):
        funds = lookup_fund_events(5)
        if funds:
            parts.append("【大基金/产业基金事件(本地 KB,需联网核实最新动态)】")
            for f in funds:
                parts.append(
                    f"- {f['event_date']} {f['fund_name']} · {f['event_type']} · "
                    f"规模/金额:{f['amount'] or '未披露'} · 投向:{f['target'] or '—'}"
                )

    segs = _match_segments(task)
    for seg in segs[:2]:
        listed = lookup_by_segment(seg, 8)
        if listed:
            parts.append(f"【segment={seg} 上市标的(本地 KB)】")
            parts.extend(f"- {x['name']} ({x['symbol']})" for x in listed)

    if not parts:
        return ""
    return "【本地知识库 · 结构化产业数据(静态种子,时效信息请以下方联网检索为准)】\n" + "\n".join(parts)


def kb_lookup_for_expert(expert: str, task: str) -> str:
    """按专家类型选取 KB 片段。"""
    if not ENABLE_INDUSTRY_KB:
        return ""
    try:
        if expert == "investment_expert":
            return kb_investment_lookup(task)
        if expert == "competitor_expert":
            hits = _match_listed_names(task)
            segs = _match_segments(task)
            parts = []
            if hits:
                parts.append("【本地 KB · 命中企业】")
                parts.extend(f"- {h['name']} ({h['symbol']}) · {h['segment']}" for h in hits)
            for seg in segs[:1]:
                listed = lookup_by_segment(seg, 6)
                if listed:
                    parts.append(f"【segment={seg} 同业列表】")
                    parts.extend(f"- {x['name']} ({x['symbol']})" for x in listed)
            return "\n".join(parts) if parts else ""
        if expert == "policy_expert":
            kws = [k for k in ("出口管制", "制裁", "信创", "补贴", "国产化") if k in task]
            rows = lookup_policy_events(kws[0] if kws else "", 5)
            if not rows:
                return ""
            parts = ["【本地 KB · 政策/监管事件(示例种子)】"]
            for p in rows:
                parts.append(f"- {p['policy_date']} {p['title']} · {p['issuer'] or ''} · {p['summary'] or ''}")
            return "\n".join(parts)
        if expert == "manufacturing_expert":
            companies = [h["name"] for h in _match_listed_names(task)]
            facs = []
            for co in companies[:2]:
                facs.extend(lookup_facilities(co, 3))
            if not facs and any(k in task for k in ("产能", "晶圆", "产线", "制造")):
                facs = lookup_facilities("", 5)
            if not facs:
                listed = lookup_by_segment("foundry", 6) + lookup_by_segment("osat", 4)
                if listed:
                    parts = ["【本地 KB · 制造/封测标的】"]
                    parts.extend(f"- {x['name']} ({x['symbol']})" for x in listed[:8])
                    return "\n".join(parts)
                return ""
            parts = ["【本地 KB · 产线/产能(示例种子)】"]
            for f in facs:
                parts.append(
                    f"- {f['company']} {f['facility_name']} · {f['location'] or ''} · "
                    f"制程:{f['process_node'] or '—'} · 产能:{f['capacity'] or '—'}"
                )
            return "\n".join(parts)
        if expert == "equipment_materials_expert":
            segs = _match_segments(task) or (["equipment"] if "设备" in task else [])
            if "材料" in task and "material" not in segs:
                segs.append("material")
            parts = []
            for seg in segs[:2] or ["equipment"]:
                listed = lookup_by_segment(seg, 8)
                if listed:
                    parts.append(f"【segment={seg}】")
                    parts.extend(f"- {x['name']} ({x['symbol']})" for x in listed)
            return "\n".join(parts) if parts else ""
        if expert == "design_ip_expert":
            parts = []
            for seg in ("eda", "fabless", "fabless_ai", "ip"):
                if seg in _match_segments(task) or seg == "eda" and "eda" in task.lower():
                    listed = lookup_by_segment(seg, 6)
                    if listed:
                        parts.append(f"【segment={seg}】")
                        parts.extend(f"- {x['name']} ({x['symbol']})" for x in listed)
            return "\n".join(parts) if parts else ""
        return ""
    except Exception:
        return ""


def knowledge_search(q: str = "", segment: str = "", limit: int = 20) -> dict[str, Any]:
    """/api/knowledge 查询入口。"""
    result: dict[str, Any] = {"query": q, "segment": segment}
    if segment:
        result["listed"] = lookup_by_segment(segment, limit)
    elif q:
        q = q.strip()
        if _STOCK_CODE.fullmatch(q) or (q.isdigit() and len(q) == 6):
            result["listed"] = lookup_by_symbol(q)
        elif any(k in q for k in _FUND_KW):
            result["fund_events"] = lookup_fund_events(limit)
        else:
            result["listed"] = lookup_by_name(q, limit)
            if not result["listed"]:
                result["policy_events"] = lookup_policy_events(q, limit)
    else:
        result["stats"] = kb_stats()
        c = _db()
        segs = [r[0] for r in c.execute(
            "SELECT DISTINCT segment FROM listed_semiconductor ORDER BY segment"
        ).fetchall()]
        c.close()
        result["segments"] = segs
    return result
