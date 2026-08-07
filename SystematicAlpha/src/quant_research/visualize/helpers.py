"""图表数据读取辅助。"""

from __future__ import annotations

from typing import Any


def item(financials: dict[str, Any], stmt: str, key: str, period: str) -> float | None:
    try:
        val = financials["statements"][stmt]["items"][key][period]
        return float(val) if val is not None else None
    except (KeyError, TypeError):
        return None


def yi(value: float | None) -> float:
    """元 → 亿元。"""
    return (value or 0) / 1e8
