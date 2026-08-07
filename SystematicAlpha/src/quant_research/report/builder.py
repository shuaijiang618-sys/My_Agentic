"""HTML 报告汇编（Jinja2）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from quant_research.report.context import build_report_context


def build_report(
    run_dir: Path,
    project_root: Path,
    *,
    run_id: str,
    template_dir: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """渲染自包含 HTML 报告（内嵌 CSS 与图表），返回输出路径。"""
    template_dir = template_dir or project_root / "templates"
    output_dir = output_dir or project_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    assets_dir = Path(__file__).resolve().parent / "assets"
    env = Environment(
        loader=FileSystemLoader([str(template_dir), str(assets_dir)]),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )

    context = build_report_context(run_dir, project_root, run_id)
    css_path = assets_dir / "style.css"
    context["styles"] = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    template = env.get_template("report.html.j2")
    html = template.render(**context)

    out_path = output_dir / f"{run_id}_report.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
