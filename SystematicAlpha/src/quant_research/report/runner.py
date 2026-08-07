"""报告阶段编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_research.report.builder import build_report


def run_report(
    run_dir: Path,
    project_root: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    analysis_path = project_root / "analysis" / run_id / "analysis.json"
    if not analysis_path.is_file():
        raise FileNotFoundError(
            f"缺少研判文件 analysis.json，请先完成人机分析: {analysis_path}"
        )
    if not (run_dir / "charts_manifest.json").is_file():
        raise FileNotFoundError(
            f"缺少图表清单，请先运行 visualize: {run_dir / 'charts_manifest.json'}"
        )

    out_path = build_report(run_dir, project_root, run_id=run_id)
    return {
        "report_path": str(out_path),
        "report_size_kb": round(out_path.stat().st_size / 1024, 1),
    }
