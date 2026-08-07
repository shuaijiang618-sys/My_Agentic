"""科目映射与三大表归一化。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from quant_research.common.io import load_yaml
from quant_research.normalize.units import detect_unit, parse_amount

_TABLE_TO_STATEMENT = {
    "balance_sheet": "balance_sheet",
    "income_statement": "income_statement",
    "cash_flow": "cash_flow",
}


def normalize_tables(
    raw_tables: dict[str, Any],
    mapping_path: Path,
    *,
    manifest: dict[str, Any],
    pages_text: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 (financials.json 内容, normalize_report.json 内容)。"""
    mapping_cfg = load_yaml(mapping_path)
    alias_to_key = _build_alias_index(mapping_cfg.get("mappings") or {})

    statements: dict[str, Any] = {}
    warnings: list[str] = []
    unmapped: list[str] = []
    unit = "元"
    report_unit = "元"

    for table in raw_tables.get("tables") or []:
        table_id = table["table_id"]
        stmt_key = _TABLE_TO_STATEMENT.get(table_id)
        if not stmt_key:
            warnings.append(f"未知 table_id: {table_id}")
            continue

        if pages_text:
            sample = _sample_text_for_unit(pages_text, table.get("page_range") or [])
            report_unit = detect_unit(sample, default=report_unit)

        unit = report_unit
        items, table_unmapped = _rows_to_items(
            table.get("headers") or [],
            table.get("rows") or [],
            alias_to_key,
            unit=unit,
        )
        unmapped.extend(table_unmapped)
        statements[stmt_key] = {
            "consolidated": True,
            "table_id": table_id,
            "page_range": table.get("page_range"),
            "items": items,
        }

    entity = {
        "stock_code": manifest.get("stock_code"),
        "company_name": manifest.get("company_name"),
    }
    report_year = manifest.get("report_year")

    financials: dict[str, Any] = {
        "run_id": raw_tables.get("run_id"),
        "entity": entity,
        "period": {
            "report_year": report_year,
            "currency": "CNY",
            "unit": "元",
            "report_unit": unit,
        },
        "statements": statements,
        "provenance": {
            "mapping_version": mapping_cfg.get("version", "unknown"),
            "warnings": warnings,
            "unmapped_labels": sorted(set(unmapped)),
        },
    }

    normalize_report = {
        "run_id": raw_tables.get("run_id"),
        "tables_processed": list(statements.keys()),
        "unit_detected": unit,
        "warnings": warnings,
        "unmapped_count": len(set(unmapped)),
        "unmapped_labels": sorted(set(unmapped)),
    }

    return financials, normalize_report


def _build_alias_index(mappings: dict[str, list[str]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for key, aliases in mappings.items():
        for alias in aliases:
            index[alias] = key
    return index


def _sample_text_for_unit(pages_text: dict[str, Any], page_range: list[int]) -> str:
    chunks: list[str] = []
    page_map = {p["page"]: p["text"] for p in pages_text.get("pages", [])}
    for pn in page_range[:3]:
        chunks.append(page_map.get(pn, ""))
    return "\n".join(chunks)


def _rows_to_items(
    headers: list[Any],
    rows: list[list[Any]],
    alias_to_key: dict[str, str],
    *,
    unit: str,
) -> tuple[dict[str, Any], list[str]]:
    del headers  # 列位置不固定，按行解析
    items: dict[str, Any] = {}
    unmapped: list[str] = []
    pending_label = ""

    for row in rows:
        label, current, prior, has_amount = _parse_row(row, unit=unit)

        if label and not has_amount:
            pending_label = _merge_label(pending_label, label)
            continue

        if not label and pending_label and has_amount:
            label = pending_label
            pending_label = ""

        if not label:
            pending_label = ""
            continue

        if _is_section_header(label):
            pending_label = ""
            continue

        if current is None and prior is None:
            pending_label = _merge_label(pending_label, label)
            continue

        pending_label = ""
        std_key = _resolve_std_key(label, alias_to_key)
        if std_key is None:
            std_key = _slugify_label(label)
            unmapped.append(label)

        items[std_key] = {
            "label": label,
            "current": current,
            "prior": prior,
        }

    return items, unmapped


def _parse_row(
    row: list[Any],
    *,
    unit: str,
) -> tuple[str | None, float | None, float | None, bool]:
    """从一行提取科目名与金额（兼容科目列偏移）。"""
    texts: list[str] = []
    for cell in row:
        if cell is None:
            continue
        text = str(cell).strip()
        if text:
            texts.append(text)

    if not texts:
        return None, None, None, False

    label_parts: list[str] = []
    amounts: list[float] = []
    for text in texts:
        val = parse_amount(text, unit=unit)
        if val is not None and not _looks_like_label(text):
            amounts.append(val)
        elif not amounts:
            label_parts.append(text)

    label = "".join(label_parts) if label_parts else None
    current = amounts[0] if len(amounts) > 0 else None
    prior = amounts[1] if len(amounts) > 1 else None
    return label, current, prior, bool(amounts)


def _looks_like_label(text: str) -> bool:
    """区分「一、营业总收入」类科目与纯金额。"""
    if any(ch in text for ch in "一二三四五六七八九十、（）%"):
        return True
    return not re.fullmatch(r"[\d,\.\-]+", text.replace(" ", ""))


def _cell(row: list[Any], index: int) -> str | None:
    if index >= len(row):
        return None
    val = row[index]
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def _merge_label(previous: str, current: str) -> str:
    if not previous:
        return current
    if current in previous:
        return previous
    if previous in current:
        return current
    return previous + current


def _is_section_header(label: str) -> bool:
    if label in {"项目", "科目"}:
        return True
    return label.endswith("：") and not any(ch.isdigit() for ch in label)


def _resolve_std_key(label: str, alias_to_key: dict[str, str]) -> str | None:
    if label in alias_to_key:
        return alias_to_key[label]
    normalized = re.sub(r"^[一二三四五六七八九十]+、\s*", "", label.strip())
    normalized = re.sub(r"^\s*[加减]：\s*", "", normalized)
    if normalized in alias_to_key:
        return alias_to_key[normalized]
    return None


def _slugify_label(label: str) -> str:
    slug = re.sub(r"\s+", "_", label.strip())
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "", slug)
    return slug or "unknown"
