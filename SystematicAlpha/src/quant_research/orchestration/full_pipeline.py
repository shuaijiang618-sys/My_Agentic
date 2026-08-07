"""端到端流水线：解析 → 研判门禁 → 出图 → HTML 报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quant_research.common.io import read_json, write_json
from quant_research.common.pdf_paths import resolve_pdf
from quant_research.ingest.loader import ingest_pdf, peek_pdf_metadata
from quant_research.metrics.runner import run_metrics
from quant_research.normalize.runner import run_normalize
from quant_research.orchestration.pipeline import Pipeline
from quant_research.orchestration.run_id import derive_run_id
from quant_research.parse.runner import run_parse
from quant_research.report.runner import run_report
from quant_research.visualize.runner import run_visualize


@dataclass
class PipelineResult:
    run_id: str
    stages: list[dict[str, Any]] = field(default_factory=list)
    report_path: str | None = None
    status: str = "success"
    message: str = ""

    def add_stage(self, name: str, **kwargs: Any) -> None:
        self.stages.append({"stage": name, **kwargs})


def run_full_pipeline(
    project_root: Path,
    pdf: str,
    *,
    run_id: str | None = None,
) -> PipelineResult:
    """
    一键跑通：
    ingest → parse → normalize → metrics → [analysis 门禁] → visualize → report
    """
    pdf_path = resolve_pdf(pdf, project_root)

    if not run_id:
        meta = peek_pdf_metadata(pdf_path)
        run_id = derive_run_id(
            company_name=meta.get("company_name"),
            report_year=meta.get("report_year"),
            stock_code=meta.get("stock_code"),
            pdf_path=pdf_path,
        )

    pipe = Pipeline(project_root, run_id)
    run_dir = pipe.ensure_run_dir()
    result = PipelineResult(run_id=run_id)

    # ── ① ingest ──
    manifest = ingest_pdf(pdf_path, run_dir, run_id=run_id)
    write_json(pipe.manifest_path(), manifest)
    result.add_stage(
        "ingest",
        company=manifest.get("company_name"),
        year=manifest.get("report_year"),
        manifest=str(pipe.manifest_path()),
    )

    # ── ② parse ──
    parse_outputs = run_parse(
        pipe.require_pdf(),
        pipe.run_dir,
        pipe.config_dir,
        run_id=run_id,
    )
    result.add_stage("parse", outputs=parse_outputs)

    # ── ③ normalize ──
    norm_outputs = run_normalize(pipe.run_dir, pipe.config_dir, run_id=run_id)
    check = read_json(pipe.run_dir / "balance_check.json")
    result.add_stage(
        "normalize",
        outputs=norm_outputs,
        balance_check_passed=check.get("passed"),
    )

    # ── ④ metrics ──
    metrics_outputs = run_metrics(pipe.run_dir, run_id=run_id)
    metrics_doc = read_json(pipe.run_dir / "metrics.json")
    computable = sum(1 for m in metrics_doc["metrics"].values() if m["computable"])
    result.add_stage(
        "metrics",
        outputs=metrics_outputs,
        computable=f"{computable}/{len(metrics_doc['metrics'])}",
    )

    # ── ⑤ analysis 门禁 ──
    analysis_path = pipe.analysis_path()
    if not pipe.check_analysis_gate():
        result.status = "needs_analysis"
        result.message = (
            f"数据管道已完成，但缺少研判文件: {analysis_path}\n"
            f"请由 Agent 完成 analysis.json 与 narrative/ 后，"
            f"执行: python -m quant_research.cli pipeline-report {run_id}"
        )
        result.add_stage("analysis", status="missing", path=str(analysis_path))
        return result
    result.add_stage("analysis", status="ok", path=str(analysis_path))

    # ── ⑥ visualize ──
    viz = run_visualize(pipe.run_dir, project_root, run_id=run_id)
    result.add_stage(
        "visualize",
        charts_dir=viz["charts_dir"],
        chart_count=viz["chart_count"],
    )

    # ── ⑦ report ──
    report = run_report(pipe.run_dir, project_root, run_id=run_id)
    result.report_path = report["report_path"]
    result.add_stage(
        "report",
        path=report["report_path"],
        size_kb=report["report_size_kb"],
    )

    return result
