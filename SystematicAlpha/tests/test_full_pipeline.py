"""端到端流水线测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_research.orchestration.run_id import derive_run_id


def test_derive_run_id_catl() -> None:
    assert derive_run_id(company_name="宁德时代", report_year=2025) == "catl_2025"


def test_derive_run_id_from_filename() -> None:
    assert derive_run_id(
        company_name=None,
        report_year=None,
        pdf_path=Path("300750_2025半年报.pdf"),
    ) == "300750_2025"


def test_full_pipeline_catl(project_root: Path) -> None:
    pdf = project_root / "data" / "input" / "宁德时代2025年年度报告.pdf"
    analysis = project_root / "analysis" / "catl_2025" / "analysis.json"
    if not pdf.is_file():
        pytest.skip("需要 data/input/宁德时代2025年年度报告.pdf")
    if not analysis.is_file():
        pytest.skip("需要 catl_2025 研判")

    from quant_research.orchestration.full_pipeline import run_full_pipeline

    result = run_full_pipeline(project_root, "宁德时代2025年年度报告.pdf", run_id="catl_2025")
    assert result.status == "success"
    assert result.report_path
    assert Path(result.report_path).is_file()
