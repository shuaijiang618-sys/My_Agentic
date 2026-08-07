"""解析阶段编排：文本 → 表格 → 章节。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_research.common.io import load_yaml, write_json
from quant_research.parse.pdf_tables import extract_tables
from quant_research.parse.pdf_text import extract_text
from quant_research.parse.section_splitter import split_sections


def run_parse(
    pdf_path: Path,
    run_dir: Path,
    config_dir: Path,
    *,
    run_id: str,
) -> dict[str, str]:
    """执行 parse 全流程，写入 raw_pages / raw_tables / raw_sections。"""
    pages_text = extract_text(pdf_path, run_id=run_id)
    table_anchors = load_yaml(config_dir / "table_anchors.yaml")
    section_anchors = load_yaml(config_dir / "section_anchors.yaml")

    raw_tables = extract_tables(
        pdf_path,
        table_anchors,
        pages_text,
        run_id=run_id,
    )
    raw_sections = split_sections(
        pages_text,
        section_anchors,
        run_id=run_id,
    )

    outputs = {
        "raw_pages": str(run_dir / "raw_pages.json"),
        "raw_tables": str(run_dir / "raw_tables.json"),
        "raw_sections": str(run_dir / "raw_sections.json"),
    }
    write_json(run_dir / "raw_pages.json", pages_text)
    write_json(run_dir / "raw_tables.json", raw_tables)
    write_json(run_dir / "raw_sections.json", raw_sections)
    return outputs
