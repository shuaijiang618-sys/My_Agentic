"""可视化阶段编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_research.common.io import read_json, write_json
from quant_research.visualize.charts import generate_charts


def run_visualize(
    run_dir: Path,
    project_root: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    financials = read_json(run_dir / "financials.json")
    metrics = read_json(run_dir / "metrics.json")

    analysis_path = project_root / "analysis" / run_id / "analysis.json"
    analysis = read_json(analysis_path) if analysis_path.is_file() else None

    charts_dir = run_dir / "charts"
    chart_paths = generate_charts(financials, metrics, analysis, charts_dir)

    manifest = {
        "run_id": run_id,
        "charts": [str(p.relative_to(run_dir)) for p in chart_paths],
        "chart_count": len(chart_paths),
    }
    write_json(run_dir / "charts_manifest.json", manifest)

    return {
        "charts_dir": str(charts_dir),
        "charts_manifest": str(run_dir / "charts_manifest.json"),
        "chart_count": len(chart_paths),
    }
