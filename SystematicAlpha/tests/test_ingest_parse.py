"""ingest → parse 集成测试。"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from quant_research.common.io import read_json
from quant_research.ingest.loader import ingest_pdf
from quant_research.parse.runner import run_parse

_CJK_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
]


def _cjk_font() -> Path:
    for path in _CJK_FONT_CANDIDATES:
        if path.is_file():
            return path
    pytest.skip("本机无可用中文字体，跳过 ingest/parse 集成测试")


def _insert(doc_page: fitz.Page, point: tuple[float, float], text: str, font_path: Path) -> None:
    doc_page.insert_font(fontfile=str(font_path), fontname="cjk")
    doc_page.insert_text(point, text, fontname="cjk", fontsize=11)


def _make_sample_pdf(path: Path) -> None:
    font = _cjk_font()
    doc = fitz.open()
    p1 = doc.new_page()
    _insert(
        p1,
        (50, 80),
        "贵州茅台酒股份有限公司\n2023年年度报告\n股票代码：600519",
        font,
    )
    p2 = doc.new_page()
    _insert(p2, (50, 60), "管理层讨论与分析\n公司经营情况良好。", font)
    p3 = doc.new_page()
    _insert(p3, (50, 60), "合并资产负债表", font)
    _insert(p3, (50, 100), "项目  2023年12月31日  2022年12月31日", font)
    _insert(p3, (50, 120), "货币资金  100  90", font)
    _insert(p3, (50, 140), "资产总计  1000  900", font)
    p4 = doc.new_page()
    _insert(p4, (50, 60), "合并利润表", font)
    _insert(p4, (50, 100), "项目  2023年度  2022年度", font)
    _insert(p4, (50, 120), "营业收入  500  450", font)
    p5 = doc.new_page()
    _insert(p5, (50, 60), "合并现金流量表", font)
    _insert(p5, (50, 100), "项目  2023年度  2022年度", font)
    _insert(p5, (50, 120), "经营活动产生的现金流量净额  200  180", font)
    doc.save(path)
    doc.close()


@pytest.fixture
def sample_run(tmp_path: Path) -> tuple[Path, Path, str]:
    run_id = "600519_2023"
    run_dir = tmp_path / "runs" / run_id
    pdf_path = tmp_path / "600519_2023年报.pdf"
    _make_sample_pdf(pdf_path)
    return pdf_path, run_dir, run_id


def test_ingest_manifest(sample_run: tuple[Path, Path, str]) -> None:
    pdf_path, run_dir, run_id = sample_run
    manifest = ingest_pdf(pdf_path, run_dir, run_id=run_id)

    assert manifest["run_id"] == run_id
    assert manifest["stock_code"] == "600519"
    assert manifest["report_year"] == 2023
    assert manifest["text_extractable"] is True
    assert (run_dir / "source.pdf").is_file()


def test_parse_pipeline(sample_run: tuple[Path, Path, str], project_root: Path) -> None:
    pdf_path, run_dir, run_id = sample_run
    ingest_pdf(pdf_path, run_dir, run_id=run_id)

    outputs = run_parse(
        run_dir / "source.pdf",
        run_dir,
        project_root / "config",
        run_id=run_id,
    )

    pages = read_json(Path(outputs["raw_pages"]))
    tables = read_json(Path(outputs["raw_tables"]))
    sections = read_json(Path(outputs["raw_sections"]))

    assert pages["total_pages"] == 5
    assert len(tables["tables"]) >= 1
    section_ids = {s["id"] for s in sections["sections"]}
    assert "mdna" in section_ids
