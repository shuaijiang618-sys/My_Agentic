"""PDF 文本抽取（PyMuPDF）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz


def extract_text(pdf_path: Path, *, run_id: str) -> dict[str, Any]:
    """按页提取纯文本。"""
    pages: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            text = doc.load_page(i).get_text("text")
            pages.append(
                {
                    "page": i + 1,
                    "text": text,
                    "char_count": len(text),
                }
            )

    return {
        "run_id": run_id,
        "total_pages": len(pages),
        "pages": pages,
    }


def page_text_by_number(pages_text: dict[str, Any]) -> dict[int, str]:
    """将 pages 列表转为 {页码: 文本} 映射。"""
    return {p["page"]: p["text"] for p in pages_text.get("pages", [])}
