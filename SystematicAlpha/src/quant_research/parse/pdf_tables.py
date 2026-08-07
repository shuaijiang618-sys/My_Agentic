"""PDF 表格抽取（pdfplumber）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pdfplumber

from quant_research.parse.pdf_text import page_text_by_number

_MAX_SCAN_PAGES = 12


def extract_tables(
    pdf_path: Path,
    anchors: dict[str, Any],
    pages_text: dict[str, Any],
    *,
    run_id: str,
    follow_pages: int = 3,
) -> dict[str, Any]:
    """按锚点定位三大表并抽取表格行列。"""
    del follow_pages  # 改用 end/stop 标记动态确定页范围
    located = _locate_table_pages(pages_text, anchors)
    tables: list[dict[str, Any]] = []
    text_by_page = page_text_by_number(pages_text)

    with pdfplumber.open(pdf_path) as pdf:
        for table_key, info in located.items():
            cfg = anchors[table_key]
            page_range = _resolve_page_range(
                info["page_start"],
                len(pdf.pages),
                text_by_page,
                cfg,
            )
            merged_rows, headers = _extract_merged_rows(
                pdf,
                page_range,
                text_by_page,
                cfg,
            )

            if not merged_rows:
                fb = _fallback_text_table(text_by_page, page_range, cfg)
                if fb:
                    headers, merged_rows = fb

            if headers is None and not merged_rows:
                continue

            tables.append(
                {
                    "table_id": table_key,
                    "title_matched": info["title_matched"],
                    "page_range": page_range,
                    "confidence": info["confidence"],
                    "headers": headers or [],
                    "rows": merged_rows,
                }
            )

    return {"run_id": run_id, "tables": tables}


def _locate_table_pages(
    pages_text: dict[str, Any],
    anchors: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """为每种表找到最优先的首次出现页码。"""
    located: dict[str, dict[str, Any]] = {}
    text_by_page = page_text_by_number(pages_text)

    for table_key, cfg in anchors.items():
        keywords: list[str] = sorted(
            cfg.get("keywords") or [],
            key=len,
            reverse=True,
        )
        excludes: list[str] = cfg.get("exclude") or []
        best: dict[str, Any] | None = None

        for page_num in sorted(text_by_page):
            text = text_by_page[page_num]
            if any(ex in text for ex in excludes) and not any(
                kw in text for kw in keywords
            ):
                continue
            start_markers: list[str] = cfg.get("start_row_markers") or []
            for kw in keywords:
                if kw not in text:
                    continue
                if start_markers and not any(m in text for m in start_markers):
                    continue
                candidate = {
                    "page_start": page_num,
                    "title_matched": kw,
                    "confidence": 0.9 if "合并" in kw else 0.7,
                }
                if best is None or candidate["page_start"] < best["page_start"]:
                    best = candidate
                break

        if best:
            located[table_key] = best

    return located


def _resolve_page_range(
    start: int,
    total_pages: int,
    text_by_page: dict[int, str],
    cfg: dict[str, Any],
) -> list[int]:
    stop_markers: list[str] = cfg.get("stop_page_markers") or []
    end = min(start + _MAX_SCAN_PAGES - 1, total_pages)
    for page_num in range(start + 1, end + 1):
        text = text_by_page.get(page_num, "")
        if any(marker in text for marker in stop_markers):
            return list(range(start, page_num + 1))
    return list(range(start, end + 1))


def _extract_merged_rows(
    pdf: pdfplumber.PDF,
    page_range: list[int],
    text_by_page: dict[int, str],
    cfg: dict[str, Any],
) -> tuple[list[list[str | None]], list[str] | None]:
    end_row_markers: list[str] = cfg.get("end_row_markers") or []
    start_row_markers: list[str] = cfg.get("start_row_markers") or []
    stop_page_markers: list[str] = cfg.get("stop_page_markers") or []
    merged_rows: list[list[str | None]] = []
    headers: list[str] | None = None
    finished = False
    started = not start_row_markers

    for page_num in page_range:
        if finished:
            break
        page_text = text_by_page.get(page_num, "")
        page = pdf.pages[page_num - 1]
        tables = page.extract_tables() or []

        for table_idx, raw in enumerate(tables):
            if finished:
                break
            if table_idx > 0 and any(m in page_text for m in stop_page_markers):
                break

            cleaned = _clean_table(raw)
            if not cleaned:
                continue

            if headers is None:
                headers = cleaned[0]
                body = cleaned[1:]
            else:
                body = _skip_repeated_header(cleaned, headers)

            for row in body:
                label = ""
                if len(row) > 1:
                    label = row[1] or ""
                elif row:
                    label = row[0] or ""
                if not started:
                    if any(m in label for m in start_row_markers):
                        started = True
                    else:
                        continue
                merged_rows.append(row)
                if end_row_markers and any(m in label for m in end_row_markers):
                    finished = True
                    break

    return merged_rows, headers


def _clean_table(rows: list[list[Any]]) -> list[list[str | None]]:
    out: list[list[str | None]] = []
    for row in rows:
        if row is None:
            continue
        cells = [_normalize_cell(c) for c in row]
        if any(c for c in cells):
            out.append(cells)
    return out


def _normalize_cell(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", " ").strip()
    return text or None


def _skip_repeated_header(
    rows: list[list[str | None]],
    headers: list[str],
) -> list[list[str | None]]:
    if not rows or not headers:
        return rows
    first = [c or "" for c in rows[0]]
    header_norm = [h or "" for h in headers]
    if first == header_norm or (
        len(first) > 1 and first[1] in ("项目", "科目", "项 目")
    ):
        return rows[1:]
    return rows


_ROW_SPLIT = re.compile(r"\s{2,}|\t")
_AMOUNT_LINE = re.compile(
    r"^[\s\-−]*(\([\d,\.]+\)|[\d,]+(?:\.\d+)?|\-|\−)\s*$"
)
_NOTE_LINE = re.compile(r"^\d{1,3}$")
_SKIP_LINE = re.compile(
    r"年度报告全文|后附财务报表|附注七|法定代表人|主管会计|（经重述）"
)


def _fallback_text_table(
    text_by_page: dict[int, str],
    page_range: list[int],
    cfg: dict[str, Any] | None = None,
) -> tuple[list[str], list[list[str | None]]] | None:
    """pdfplumber 无表格线时，从文本行解析竖排/简易表。"""
    cfg = cfg or {}
    vertical = _parse_vertical_financial_text(text_by_page, page_range, cfg)
    if vertical:
        return vertical

    lines: list[str] = []
    for page_num in page_range:
        lines.extend(text_by_page.get(page_num, "").splitlines())

    header_idx = -1
    headers: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if "项目" in stripped or "科目" in stripped:
            parts = _ROW_SPLIT.split(stripped)
            if len(parts) >= 2:
                header_idx = i
                headers = parts
                break

    if header_idx < 0:
        return None

    rows: list[list[str | None]] = []
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped:
            if rows:
                break
            continue
        parts = _ROW_SPLIT.split(stripped)
        if len(parts) >= 2:
            rows.append(parts)
        elif rows:
            break

    return (headers, rows) if rows else None


def _parse_vertical_financial_text(
    text_by_page: dict[int, str],
    page_range: list[int],
    cfg: dict[str, Any],
) -> tuple[list[str], list[list[str | None]]] | None:
    """解析竖排布局财报（如比亚迪）：科目名单独成行，金额在后续行。"""
    lines: list[str] = []
    for page_num in page_range:
        for raw in text_by_page.get(page_num, "").splitlines():
            stripped = raw.strip()
            if stripped:
                lines.append(stripped)

    start_markers: list[str] = cfg.get("start_row_markers") or []
    end_markers: list[str] = cfg.get("end_row_markers") or []
    started = not start_markers
    rows: list[list[str | None]] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if _SKIP_LINE.search(line):
            i += 1
            continue

        if not started:
            if any(m in line for m in start_markers):
                started = True
            else:
                i += 1
                continue

        if end_markers and any(m in line for m in end_markers):
            amounts = _collect_amounts_from_line(line)
            if amounts:
                label = line
                for m in end_markers:
                    label = label.replace(m, "").strip()
                if label:
                    rows.append([label] + amounts)
            rows.append([line])
            break

        if re.match(r"^[一二三四五六七八九十]+、\s*$", line) and i + 1 < len(lines):
            line = lines[i + 1]
            i += 1

        label = _normalize_vertical_label(line)
        if not label or _is_noise_label(label):
            i += 1
            continue

        j = i + 1
        if j < len(lines) and _NOTE_LINE.match(lines[j]):
            j += 1

        amounts: list[str] = []
        while j < len(lines) and len(amounts) < 2:
            nxt = lines[j]
            if _SKIP_LINE.search(nxt):
                j += 1
                continue
            if _is_noise_label(nxt) and not _collect_amounts_from_line(nxt):
                break
            line_amounts = _collect_amounts_from_line(nxt)
            if line_amounts:
                amounts.extend(line_amounts)
                j += 1
            else:
                break

        if amounts:
            row: list[str | None] = [label]
            row.extend(amounts[:2])
            rows.append(row)
            i = j
        else:
            i += 1

    headers = ["项目", "本期", "上期"]
    return (headers, rows) if rows else None


def _collect_amounts_from_line(line: str) -> list[str]:
    parts = _ROW_SPLIT.split(line)
    amounts: list[str] = []
    for part in parts:
        p = part.strip()
        if _AMOUNT_LINE.match(p):
            amounts.append(p)
    if not amounts and _AMOUNT_LINE.match(line.strip()):
        amounts.append(line.strip())
    return amounts


def _normalize_vertical_label(line: str) -> str:
    text = re.sub(r"^[一二三四五六七八九十]+、\s*", "", line.strip())
    text = re.sub(r"^\s*[加减]：\s*", "", text)
    return text.strip()


def _is_noise_label(label: str) -> bool:
    if label in {"资产", "负债", "股东权益", "流动资产", "非流动资产", "流动负债", "非流动负债"}:
        return False
    if _AMOUNT_LINE.match(label):
        return True
    if _NOTE_LINE.match(label):
        return True
    if len(label) <= 1:
        return True
    if label.startswith("其中：") and len(label) < 8:
        return False
    return False
