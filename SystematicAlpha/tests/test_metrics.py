"""指标层测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_research.common.io import read_json
from quant_research.metrics.calculators import compute_metrics
from quant_research.metrics.runner import run_metrics


@pytest.fixture
def catl_financials(project_root: Path) -> dict:
    path = project_root / "data" / "runs" / "catl_2025" / "financials.json"
    if not path.is_file():
        pytest.skip("需要先跑通 catl_2025 解析流水线")
    return read_json(path)


def test_compute_metrics_keys(catl_financials: dict) -> None:
    result = compute_metrics(catl_financials)
    metrics = result["metrics"]

    expected = {
        "debt_to_asset",
        "current_ratio",
        "gross_margin",
        "net_margin",
        "roe",
        "roa",
        "ocf_to_net_profit",
    }
    assert expected.issubset(metrics.keys())
    assert metrics["debt_to_asset"]["computable"] is True
    assert 0 < metrics["debt_to_asset"]["value"] < 1


def test_debt_to_asset_value(catl_financials: dict) -> None:
    metrics = compute_metrics(catl_financials)["metrics"]
    # 603,801,220 / 974,827,544 ≈ 0.6194
    assert metrics["debt_to_asset"]["value"] == pytest.approx(0.6194, rel=1e-3)


def test_run_metrics_writes_file(project_root: Path, catl_financials: dict) -> None:
    run_dir = project_root / "data" / "runs" / "catl_2025"
    outputs = run_metrics(run_dir, run_id="catl_2025")
    assert Path(outputs["metrics"]).is_file()
    saved = read_json(Path(outputs["metrics"]))
    assert saved["run_id"] == "catl_2025"
    assert len(saved["metrics"]) >= 10
