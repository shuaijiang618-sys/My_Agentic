"""归一化阶段编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_research.common.io import read_json, write_json
from quant_research.normalize.mapper import normalize_tables
from quant_research.normalize.validator import check_balance_equation, validate_financials


def run_normalize(
    run_dir: Path,
    config_dir: Path,
    *,
    run_id: str,
) -> dict[str, str]:
    manifest = read_json(run_dir / "manifest.json")
    raw_tables = read_json(run_dir / "raw_tables.json")
    pages_path = run_dir / "raw_pages.json"
    pages_text = read_json(pages_path) if pages_path.is_file() else None

    financials, normalize_report = normalize_tables(
        raw_tables,
        config_dir / "account_mapping.yaml",
        manifest=manifest,
        pages_text=pages_text,
    )
    financials["run_id"] = run_id

    warnings = validate_financials(financials)
    if warnings:
        financials["provenance"]["warnings"].extend(warnings)

    balance_check = check_balance_equation(financials)

    outputs = {
        "financials": str(run_dir / "financials.json"),
        "normalize_report": str(run_dir / "normalize_report.json"),
        "balance_check": str(run_dir / "balance_check.json"),
    }
    write_json(run_dir / "financials.json", financials)
    write_json(run_dir / "normalize_report.json", normalize_report)
    write_json(run_dir / "balance_check.json", balance_check)

    # 同步一份到 data/ 根下便于查找
    data_root = run_dir.parent.parent
    write_json(data_root / f"{run_id}_financials.json", financials)
    write_json(data_root / f"{run_id}_balance_check.json", balance_check)

    return outputs
