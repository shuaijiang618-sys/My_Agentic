"""PDF 接入：校验、元数据提取、manifest 生成。"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from quant_research.common.metadata import extract_metadata


def peek_pdf_metadata(pdf_path: Path) -> dict[str, Any]:
    """轻量探测 PDF 元数据（不写入 run 目录）。"""
    page_count, sample_text, text_extractable = _probe_pdf(pdf_path)
    meta = extract_metadata(sample_text, pdf_path, page_count=page_count)
    meta["text_extractable"] = text_extractable
    return meta


def ingest_pdf(
    pdf_path: Path,
    run_dir: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    """接入 PDF：校验、复制归档、生成 manifest.json。"""
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"非 PDF 文件: {pdf_path}")

    run_dir.mkdir(parents=True, exist_ok=True)
    archived = run_dir / "source.pdf"
    if pdf_path != archived.resolve():
        shutil.copy2(pdf_path, archived)

    sha256 = _file_sha256(archived)
    page_count, sample_text, text_extractable = _probe_pdf(archived)

    meta = extract_metadata(sample_text, pdf_path, page_count=page_count)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "source_pdf": str(pdf_path),
        "archived_pdf": "source.pdf",
        "sha256": sha256,
        "stock_code": meta["stock_code"],
        "company_name": meta["company_name"],
        "report_year": meta["report_year"],
        "report_type": meta["report_type"],
        "page_count": page_count,
        "text_extractable": text_extractable,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return manifest


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_pdf(pdf_path: Path) -> tuple[int, str, bool]:
    """返回 (页数, 首页抽样文本, 是否可提取文本)。"""
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        samples: list[str] = []
        for i in range(min(5, page_count)):
            samples.append(doc.load_page(i).get_text("text"))
        sample_text = "\n".join(samples)
        char_count = sum(len(doc.load_page(i).get_text("text")) for i in range(min(3, page_count)))
        text_extractable = char_count >= 80
        return page_count, sample_text, text_extractable
