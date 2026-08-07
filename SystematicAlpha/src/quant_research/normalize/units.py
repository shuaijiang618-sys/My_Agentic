"""金额单位与负数表示统一。"""

from __future__ import annotations

import re

_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"单位[：:]\s*万元"), "万元"),
    (re.compile(r"单位[：:]\s*千元"), "千元"),
    (re.compile(r"单位[：:]\s*元"), "元"),
    (re.compile(r"报表的单位为[：:]\s*万元"), "万元"),
    (re.compile(r"报表的单位为[：:]\s*千元"), "千元"),
    (re.compile(r"报表的单位为[：:]\s*元"), "元"),
    (re.compile(r"人民币万元"), "万元"),
    (re.compile(r"人民币千元"), "千元"),
]

_MULTIPLIER = {
    "元": 1.0,
    "千元": 1_000.0,
    "万元": 10_000.0,
}

_AMOUNT_CLEAN = re.compile(r"[,\s]")


def detect_unit(text: str, default: str = "元") -> str:
    """从表头或页眉文本识别金额单位。"""
    for pattern, unit in _UNIT_PATTERNS:
        if pattern.search(text):
            return unit
    return default


def unit_multiplier(unit: str) -> float:
    return _MULTIPLIER.get(unit, 1.0)


def parse_amount(raw: str | None, *, unit: str = "元") -> float | None:
    """解析单元格金额为「元」。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {"—", "-", "－", "— —", "None"}:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    if text.startswith("-"):
        negative = True
        text = text[1:].strip()

    cleaned = _AMOUNT_CLEAN.sub("", text)
    if not cleaned or not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        return None

    value = float(cleaned) * unit_multiplier(unit)
    return -value if negative else value


def normalize_unit(header: str) -> str:
    """从表头识别单位（元/万元/千元）。"""
    return detect_unit(header)
