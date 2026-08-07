"""run_id 推导。"""

from __future__ import annotations

import re
from pathlib import Path

_COMPANY_SLUG: dict[str, str] = {
    "宁德时代": "catl",
    "贵州茅台": "moutai",
    "比亚迪": "byd",
}


def slugify_company(name: str | None) -> str:
    if not name:
        return "unknown"
    name = name.strip()
    if name in _COMPANY_SLUG:
        return _COMPANY_SLUG[name]
    ascii_part = re.sub(r"[^a-zA-Z0-9]", "", name)
    if ascii_part:
        return ascii_part.lower()[:12]
    return re.sub(r"\s+", "_", name)[:20]


def derive_run_id(
    *,
    company_name: str | None,
    report_year: int | None,
    stock_code: str | None = None,
    pdf_path: Path | None = None,
) -> str:
    """从元数据或文件名推导 run_id，如 catl_2025。"""
    if pdf_path is not None:
        m = re.search(r"(\d{6})[_-]?(\d{4})", pdf_path.stem)
        if m:
            return f"{m.group(1)}_{m.group(2)}"

    slug = stock_code or slugify_company(company_name)
    if report_year:
        return f"{slug}_{report_year}"
    return slug
