"""Phase 3 · 简报导出(Markdown / PDF)。"""
from __future__ import annotations

import io
import re

from . import store

_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_HEAD = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_QUOTE = re.compile(r"^>\s?", re.MULTILINE)


def _get_latest_brief(session: str) -> tuple[str | None, str | None]:
    conv = store.get_conversation(session)
    if not conv:
        return None, None
    last = conv[-1]
    query = last.get("query", "")
    brief = last.get("brief", "") or ""
    if not brief.strip():
        return None, None
    return query, brief


def export_session_markdown(session: str) -> tuple[str | None, dict]:
    """取会话最新一轮简报,生成可下载 Markdown。"""
    query, brief = _get_latest_brief(session)
    if brief is None:
        err = "session not found" if not store.get_conversation(session) else "empty brief"
        return None, {"error": err, "session": session}
    title = query[:60].replace("/", "-")
    md = f"# 半导体产业研究简报\n\n**问题**: {query}\n\n**会话**: `{session}`\n\n---\n\n{brief}\n"
    return md, {"session": session, "query": query, "chars": len(brief), "title": title, "format": "md"}


def _markdown_to_plain(md: str) -> str:
    """Markdown → 纯文本(供 PDF 排版)。"""
    text = md
    text = _MD_LINK.sub(r"\1 (\2)", text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_HEAD.sub("", text)
    text = _MD_QUOTE.sub("", text)
    text = text.replace("---", "—" * 20)
    return text.strip()


def export_session_pdf(session: str) -> tuple[bytes | None, dict]:
    """Markdown 简报 → PDF(reportlab + STSong-Light 中文)。"""
    md, meta = export_session_markdown(session)
    if md is None:
        return None, meta
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError:
        return None, {
            "error": "reportlab 未安装 — pip install reportlab",
            "session": session,
            "format": "pdf",
        }

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    y = height - margin
    line_h = 6 * mm
    c.setFont("STSong-Light", 11)

    plain = _markdown_to_plain(md)
    max_chars = 42
    for para in plain.split("\n"):
        para = para.strip()
        if not para:
            y -= line_h
            continue
        while para:
            chunk = para[:max_chars]
            para = para[max_chars:]
            if y < margin:
                c.showPage()
                c.setFont("STSong-Light", 11)
                y = height - margin
            c.drawString(margin, y, chunk)
            y -= line_h

    c.save()
    pdf_bytes = buf.getvalue()
    meta = {**meta, "format": "pdf", "bytes": len(pdf_bytes)}
    return pdf_bytes, meta
