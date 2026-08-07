"""可视化层测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_research.visualize.runner import run_visualize


def test_run_visualize(project_root: Path) -> None:
    run_dir = project_root / "data" / "runs" / "catl_2025"
    if not (run_dir / "metrics.json").is_file():
        pytest.skip("需要先跑通 catl_2025 metrics")

    result = run_visualize(run_dir, project_root, run_id="catl_2025")
    charts_dir = Path(result["charts_dir"])
    assert charts_dir.is_dir()
    assert result["chart_count"] >= 13
    assert (charts_dir / "balance_structure.png").is_file()
    assert (charts_dir / "risk_radar.png").is_file()
    assert (charts_dir / "key_indicators_trend.png").is_file()
    assert (charts_dir / "income_structure.png").is_file()
