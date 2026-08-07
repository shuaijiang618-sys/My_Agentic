"""年报正文区块切分。"""

from __future__ import annotations

import re
from typing import Any

from quant_research.parse.pdf_text import page_text_by_number


def split_sections(
    pages_text: dict[str, Any],
    section_anchors: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    """按锚点关键词切分正文区块。"""
    anchors: list[dict[str, Any]] = section_anchors.get("sections") or []
    text_by_page = page_text_by_number(pages_text)
    if not text_by_page:
        return {"run_id": run_id, "sections": []}

    hits: list[tuple[int, dict[str, Any], str]] = []
    for page_num, text in sorted(text_by_page.items()):
        for anchor in anchors:
            for kw in anchor.get("keywords") or []:
                if kw in text:
                    hits.append((page_num, anchor, kw))
                    break

    # 同 id 只保留最早命中
    seen: set[str] = set()
    unique_hits: list[tuple[int, dict[str, Any], str]] = []
    for page_num, anchor, kw in sorted(hits, key=lambda x: x[0]):
        sid = anchor["id"]
        if sid in seen:
            continue
        seen.add(sid)
        unique_hits.append((page_num, anchor, kw))

    page_numbers = sorted(text_by_page)
    sections: list[dict[str, Any]] = []

    for idx, (page_start, anchor, kw) in enumerate(unique_hits):
        if idx + 1 < len(unique_hits):
            page_end = unique_hits[idx + 1][0] - 1
        else:
            page_end = page_numbers[-1]
        page_end = max(page_start, page_end)

        chunk_pages = [p for p in page_numbers if page_start <= p <= page_end]
        body = "\n\n".join(text_by_page[p] for p in chunk_pages)
        body = _trim_section_body(body, kw)

        sections.append(
            {
                "id": anchor["id"],
                "title": anchor.get("title") or anchor["id"],
                "title_matched": kw,
                "page_start": page_start,
                "page_end": page_end,
                "text": body,
            }
        )

    return {"run_id": run_id, "sections": sections}


def _trim_section_body(text: str, keyword: str) -> str:
    """从关键词出现处截断页首冗余。"""
    pos = text.find(keyword)
    if pos == -1:
        return text.strip()
    return text[pos:].strip()
