"""CLI 入口：五步流水线子命令。"""

from __future__ import annotations

from pathlib import Path

import typer

from quant_research.common.io import read_json, write_json
from quant_research.common.paths import get_project_root
from quant_research.common.pdf_paths import resolve_pdf
from quant_research.ingest.loader import ingest_pdf
from quant_research.orchestration.full_pipeline import run_full_pipeline
from quant_research.orchestration.pipeline import Pipeline
from quant_research.metrics.runner import run_metrics
from quant_research.normalize.runner import run_normalize
from quant_research.parse.runner import run_parse
from quant_research.report.runner import run_report
from quant_research.visualize.runner import run_visualize

app = typer.Typer(
    name="quant-research",
    help="A股年报本地量化投研系统",
    no_args_is_help=True,
)


def _resolve_pdf(pdf: str, project_root: Path) -> Path:
    try:
        return resolve_pdf(pdf, project_root)
    except FileNotFoundError as e:
        raise typer.BadParameter(str(e)) from e


@app.command()
def ingest(
    run_id: str = typer.Argument(..., help="运行 ID，如 600519_2023"),
    pdf: str = typer.Argument(..., help="PDF 路径或 data/input/ 下文件名"),
) -> None:
    """① 接入 PDF，生成 manifest.json。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    run_dir = pipe.ensure_run_dir()
    pdf_path = _resolve_pdf(pdf, root)

    manifest = ingest_pdf(pdf_path, run_dir, run_id=run_id)
    write_json(pipe.manifest_path(), manifest)

    typer.echo(f"✓ ingest 完成 → {pipe.manifest_path()}")
    typer.echo(
        f"  公司: {manifest.get('company_name') or '—'} "
        f"({manifest.get('stock_code') or '—'}) "
        f"{manifest.get('report_year') or '—'}"
    )


@app.command("parse")
def parse_cmd(
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """② 提取文本与表格。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    pipe.require_manifest()
    pdf_path = pipe.require_pdf()
    manifest = read_json(pipe.manifest_path())

    outputs = run_parse(
        pdf_path,
        pipe.run_dir,
        pipe.config_dir,
        run_id=manifest["run_id"],
    )

    typer.echo("✓ parse 完成")
    for name, path in outputs.items():
        typer.echo(f"  {name}: {path}")


@app.command()
def normalize(
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """③ 标准化为 financials.json 并做恒等式自检。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    pipe.require_manifest()
    if not (pipe.run_dir / "raw_tables.json").is_file():
        raise typer.BadParameter("缺少 raw_tables.json，请先运行 parse")

    outputs = run_normalize(pipe.run_dir, pipe.config_dir, run_id=run_id)
    check = read_json(pipe.run_dir / "balance_check.json")

    typer.echo("✓ normalize 完成")
    for name, path in outputs.items():
        typer.echo(f"  {name}: {path}")
    typer.echo(f"  会计恒等式自检: {'通过' if check.get('passed') else '未通过'}")
    for item in check.get("checks", []):
        status = "✓" if item["passed"] else "✗"
        typer.echo(
            f"    {status} {item['formula']} ({item['period']}) "
            f"diff={item.get('diff', 0):.2f}"
        )


@app.command()
def metrics_cmd(
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """③ 计算 metrics.json。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    if not (pipe.run_dir / "financials.json").is_file():
        raise typer.BadParameter("缺少 financials.json，请先运行 normalize")

    outputs = run_metrics(pipe.run_dir, run_id=run_id)
    result = read_json(pipe.run_dir / "metrics.json")
    computable = sum(1 for m in result["metrics"].values() if m["computable"])

    typer.echo("✓ metrics 完成")
    typer.echo(f"  metrics: {outputs['metrics']}")
    typer.echo(f"  可计算指标: {computable}/{len(result['metrics'])}")
    for name, m in result["metrics"].items():
        if not m["computable"]:
            continue
        v = m["value"]
        vp = m.get("value_prior")
        fmt = f"{v:.4f}" if v is not None and abs(v) < 10 else f"{v:,.2f}" if v is not None else "—"
        line = f"    {name}: {fmt}"
        if vp is not None:
            fp = f"{vp:.4f}" if abs(vp) < 10 else f"{vp:,.2f}"
            line += f"  (上期 {fp})"
        typer.echo(line)


app.command(name="metrics")(metrics_cmd)


@app.command()
def visualize_cmd(
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """⑤ 生成图表（若存在 analysis.json 则含风险雷达图）。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    if not (pipe.run_dir / "metrics.json").is_file():
        raise typer.BadParameter("缺少 metrics.json，请先运行 metrics")

    result = run_visualize(pipe.run_dir, root, run_id=run_id)
    typer.echo("✓ visualize 完成")
    typer.echo(f"  charts: {result['charts_dir']} ({result['chart_count']} 张)")
    manifest = read_json(pipe.run_dir / "charts_manifest.json")
    for chart in manifest["charts"]:
        typer.echo(f"    {chart}")


app.command(name="visualize")(visualize_cmd)


@app.command()
def report_cmd(
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """⑥ 渲染 HTML 投研报告（须先完成 analysis/ 研判与 visualize）。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    if not pipe.check_analysis_gate():
        raise typer.BadParameter(
            f"缺少 analysis.json，请先完成人机研判: {pipe.analysis_path()}"
        )
    if not (pipe.run_dir / "charts_manifest.json").is_file():
        raise typer.BadParameter("缺少图表，请先运行 visualize")

    result = run_report(pipe.run_dir, root, run_id=run_id)
    typer.echo("✓ report 完成")
    typer.echo(f"  HTML: {result['report_path']}")
    typer.echo(f"  大小: {result['report_size_kb']} KB")


app.command(name="report")(report_cmd)


@app.command(name="pipeline-data")
def pipeline_data(
    run_id: str = typer.Argument(...),
    pdf: str = typer.Argument(...),
) -> None:
    """①→③：ingest → parse → normalize → metrics。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    run_dir = pipe.ensure_run_dir()
    pdf_path = _resolve_pdf(pdf, root)

    manifest = ingest_pdf(pdf_path, run_dir, run_id=run_id)
    write_json(pipe.manifest_path(), manifest)
    typer.echo(f"✓ ingest → {pipe.manifest_path()}")

    outputs = run_parse(
        pipe.require_pdf(),
        pipe.run_dir,
        pipe.config_dir,
        run_id=run_id,
    )
    typer.echo("✓ parse 完成")
    for name, path in outputs.items():
        typer.echo(f"  {name}: {path}")

    norm_outputs = run_normalize(pipe.run_dir, pipe.config_dir, run_id=run_id)
    check = read_json(pipe.run_dir / "balance_check.json")
    typer.echo("✓ normalize 完成")
    for name, path in norm_outputs.items():
        typer.echo(f"  {name}: {path}")
    typer.echo(f"  会计恒等式自检: {'通过' if check.get('passed') else '未通过'}")

    metrics_outputs = run_metrics(pipe.run_dir, run_id=run_id)
    metrics_result = read_json(pipe.run_dir / "metrics.json")
    computable = sum(1 for m in metrics_result["metrics"].values() if m["computable"])
    typer.echo("✓ metrics 完成")
    typer.echo(f"  metrics: {metrics_outputs['metrics']}")
    typer.echo(f"  可计算指标: {computable}/{len(metrics_result['metrics'])}")


@app.command(name="pipeline-report")
def pipeline_report(
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """⑤→⑥：visualize → report（含研判门禁）。"""
    root = get_project_root()
    pipe = Pipeline(root, run_id)
    if not pipe.check_analysis_gate():
        raise typer.BadParameter(
            f"缺少 analysis.json，请先完成人机研判: {pipe.analysis_path()}"
        )
    if not (pipe.run_dir / "metrics.json").is_file():
        raise typer.BadParameter("缺少 metrics.json，请先运行 metrics")

    viz = run_visualize(pipe.run_dir, root, run_id=run_id)
    typer.echo(f"✓ visualize 完成 ({viz['chart_count']} 张图)")

    result = run_report(pipe.run_dir, root, run_id=run_id)
    typer.echo("✓ report 完成")
    typer.echo(f"  HTML: {result['report_path']}")
    typer.echo(f"  大小: {result['report_size_kb']} KB")


@app.command()
def run(
    pdf: str = typer.Argument(..., help="PDF 文件名或路径（可放在 data/input/）"),
    run_id: str | None = typer.Option(
        None, "--run-id", "-r", help="运行 ID，默认从公司名+年份推导"
    ),
) -> None:
    """一键全流程：解析 → 研判(门禁) → 出图 → HTML 报告。"""
    root = get_project_root()
    typer.echo(f"▶ 开始端到端流水线")
    typer.echo(f"  PDF: {pdf}")

    result = run_full_pipeline(root, pdf, run_id=run_id)
    typer.echo(f"  run_id: {result.run_id}")
    typer.echo("")

    _STAGE_LABELS = {
        "ingest": "① 接入 PDF",
        "parse": "② 解析文本与表格",
        "normalize": "③ 标准化三表",
        "metrics": "④ 计算指标",
        "analysis": "⑤ 研判门禁",
        "visualize": "⑥ 生成图表",
        "report": "⑦ 汇编 HTML",
    }

    for stage in result.stages:
        name = stage["stage"]
        label = _STAGE_LABELS.get(name, name)
        if name == "ingest":
            typer.echo(f"✓ {label} — {stage.get('company')} {stage.get('year')}")
        elif name == "normalize":
            ok = "通过" if stage.get("balance_check_passed") else "未通过"
            typer.echo(f"✓ {label} — 恒等式自检 {ok}")
        elif name == "metrics":
            typer.echo(f"✓ {label} — 可计算 {stage.get('computable')}")
        elif name == "analysis":
            if stage.get("status") == "missing":
                typer.echo(f"⏸ {label} — 缺少研判文件")
            else:
                typer.echo(f"✓ {label}")
        elif name == "visualize":
            typer.echo(f"✓ {label} — {stage.get('chart_count')} 张")
        elif name == "report":
            typer.echo(f"✓ {label} — {stage.get('path')} ({stage.get('size_kb')} KB)")
        else:
            typer.echo(f"✓ {label}")

    typer.echo("")
    if result.status == "needs_analysis":
        typer.echo(f"⚠ {result.message}")
        raise typer.Exit(code=2)

    typer.echo("✅ 全流程完成")
    typer.echo(f"  报告: {result.report_path}")
    typer.echo(f"  打开: open \"{result.report_path}\"")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
