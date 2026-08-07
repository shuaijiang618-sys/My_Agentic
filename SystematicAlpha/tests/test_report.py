"""报告层测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_research.report.runner import run_report


def test_run_report(project_root: Path) -> None:
    run_dir = project_root / "data" / "runs" / "catl_2025"
    analysis = project_root / "analysis" / "catl_2025" / "analysis.json"
    if not analysis.is_file():
        pytest.skip("需要先完成 catl_2025 研判")
    if not (run_dir / "charts_manifest.json").is_file():
        pytest.skip("需要先运行 visualize")

    result = run_report(run_dir, project_root, run_id="catl_2025")
    report_path = Path(result["report_path"])
    assert report_path.is_file()
    assert report_path.suffix == ".html"
    content = report_path.read_text(encoding="utf-8")
    assert "宁德时代" in content
    assert "三表勾稽" in content
    assert "data:image/png;base64," in content
    assert result["report_size_kb"] > 100
