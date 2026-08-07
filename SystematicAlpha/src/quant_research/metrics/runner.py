"""指标计算阶段编排。"""

from __future__ import annotations

from pathlib import Path

from quant_research.common.io import read_json, write_json
from quant_research.metrics.calculators import compute_metrics


def run_metrics(run_dir: Path, *, run_id: str) -> dict[str, str]:
    financials_path = run_dir / "financials.json"
    if not financials_path.is_file():
        raise FileNotFoundError(f"缺少 financials.json: {financials_path}")

    financials = read_json(financials_path)
    result = compute_metrics(financials)
    result["run_id"] = run_id

    out_path = run_dir / "metrics.json"
    write_json(out_path, result)

    data_root = run_dir.parent.parent
    write_json(data_root / f"{run_id}_metrics.json", result)

    return {"metrics": str(out_path)}
