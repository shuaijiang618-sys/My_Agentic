"""年报 PDF 元数据启发式提取。"""

import re
from pathlib import Path
from typing import Any


_STOCK_CODE_LABEL = re.compile(
    r"(?:股票代码|证券代码|代码)[：:\s]*([0-9]{6})",
    re.IGNORECASE,
)
_STOCK_CODE_BARE = re.compile(r"\b([0-9]{6})\b")
_REPORT_YEAR = re.compile(r"(20[0-9]{2})\s*年(?:度)?(?:报告|年报)?")
_COMPANY_LABEL = re.compile(
    r"(?:公司(?:全称|名称|简称)|发行人)[：:\s]*([^\s，,；;]{2,40})",
)
_ANNUAL_KEYWORDS = ("年度报告", "年报")
_SEMI_KEYWORDS = ("半年度报告", "半年报", "中期报告")


def extract_metadata(
    sample_text: str,
    pdf_path: Path,
    *,
    page_count: int,
) -> dict[str, Any]:
    """从首页抽样文本与文件名推断 manifest 元字段。"""
    stock_code = _extract_stock_code(sample_text, pdf_path)
    report_year = _extract_report_year(sample_text, pdf_path)
    company_name = _extract_company_name(sample_text, pdf_path)
    report_type = _detect_report_type(sample_text, pdf_path)

    return {
        "stock_code": stock_code,
        "company_name": company_name,
        "report_year": report_year,
        "report_type": report_type,
        "page_count": page_count,
    }


def _extract_stock_code(text: str, pdf_path: Path) -> str | None:
    m = _STOCK_CODE_LABEL.search(text)
    if m:
        return m.group(1)
    m = _STOCK_CODE_BARE.search(pdf_path.stem)
    if m:
        return m.group(1)
    m = _STOCK_CODE_BARE.search(text[:3000])
    return m.group(1) if m else None


def _extract_report_year(text: str, pdf_path: Path) -> int | None:
    for source in (text[:5000], pdf_path.stem):
        m = _REPORT_YEAR.search(source)
        if m:
            return int(m.group(1))
    return None


def _extract_company_name(text: str, pdf_path: Path) -> str | None:
    m = _COMPANY_LABEL.search(text[:5000])
    if m:
        return m.group(1).strip()
    stem = pdf_path.stem
    stem = re.sub(r"[_\-\s]*[0-9]{6}.*", "", stem)
    stem = re.sub(r"(20[0-9]{2}).*", "", stem)
    stem = stem.strip(" _-")
    return stem if len(stem) >= 2 else None


def _detect_report_type(text: str, pdf_path: Path) -> str:
    combined = text[:8000] + pdf_path.stem
    if any(k in combined for k in _SEMI_KEYWORDS):
        return "semi_annual"
    if any(k in combined for k in _ANNUAL_KEYWORDS):
        return "annual"
    return "annual"
