"""报告上下文构建：结构化数据 → HTML 片段。"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown
import yaml

from quant_research.common.io import read_json

_METRIC_LABELS: dict[str, str] = {
    "debt_to_asset": "资产负债率",
    "debt_to_equity": "产权比率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "cash_ratio": "现金比率",
    "gross_margin": "毛利率",
    "operating_margin": "营业利润率",
    "net_margin": "净利率",
    "roe": "ROE",
    "roa": "ROA",
    "receivables_turnover": "应收账款周转率",
    "inventory_turnover": "存货周转率",
    "total_asset_turnover": "总资产周转率",
    "ocf_to_net_profit": "经营现金流/净利润",
}

_CHART_TITLES: dict[str, str] = {
    "key_indicators_trend.png": "关键指标同比趋势",
    "margin_trend.png": "盈利能力比率趋势",
    "working_capital_trend.png": "营运资本科目趋势",
    "income_structure.png": "收入与成本结构",
    "asset_composition.png": "资产结构",
    "liability_equity_composition.png": "负债与权益结构",
    "cash_profit_comparison.png": "净利润 vs 经营现金流",
    "balance_structure.png": "资产负债结构",
    "revenue_profit.png": "营收与净利润",
    "profitability.png": "盈利能力指标",
    "cash_flow.png": "现金流量结构",
    "solvency.png": "偿债能力指标",
    "key_metrics.png": "营运与现金流效率",
    "risk_radar.png": "风险雷达图",
}

_RISK_LEVEL: dict[str, str] = {
    "low": "低",
    "medium": "中",
    "medium-high": "中高",
    "high": "高",
}

_SEVERITY_CLASS: dict[str, str] = {
    "high": "severity-high",
    "medium-high": "severity-medium-high",
    "medium": "severity-medium",
    "low-medium": "severity-low-medium",
    "low": "severity-low",
    "info": "severity-info",
}


def _yi(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 1e8


def _pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%"


def _growth(current: float | None, prior: float | None) -> str:
    if current is None or prior is None or prior == 0:
        return "—"
    return f"{(current - prior) / prior * 100:+.1f}%"


def _item(financials: dict[str, Any], stmt: str, key: str, period: str) -> float | None:
    try:
        val = financials["statements"][stmt]["items"][key][period]
        return float(val) if val is not None else None
    except (KeyError, TypeError):
        return None


def _md_to_html(text: str) -> str:
    return markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br"],
    )


def _embed_image(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def _risk_badge_class(level: str) -> str:
    mapping = {"low": "risk-low", "medium": "risk-medium", "high": "risk-high"}
    return mapping.get(level, "risk-medium")


def build_report_context(
    run_dir: Path,
    project_root: Path,
    run_id: str,
) -> dict[str, Any]:
    financials = read_json(run_dir / "financials.json")
    metrics_doc = read_json(run_dir / "metrics.json")
    analysis = read_json(project_root / "analysis" / run_id / "analysis.json")

    cross_path = project_root / "analysis" / run_id / "cross_validation.json"
    cross_validation = read_json(cross_path) if cross_path.is_file() else None

    manifest_path = run_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}

    year = financials.get("period", {}).get("report_year") or manifest.get("report_year") or "—"
    prior_year = int(year) - 1 if isinstance(year, int) else "—"
    company = financials.get("entity", {}).get("company_name") or manifest.get("company_name") or "—"
    stock_code = financials.get("entity", {}).get("stock_code") or manifest.get("stock_code") or "—"

    highlights = _build_highlights(financials, metrics_doc, year, prior_year)
    metrics_rows = _build_metrics_rows(metrics_doc)
    charts = _build_charts(run_dir)
    narratives = _load_narratives(project_root, run_id, analysis, cross_validation)

    return {
        "run_id": run_id,
        "company_name": company,
        "stock_code": stock_code,
        "report_year": year,
        "prior_year": prior_year,
        "generated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "analyst": analysis.get("analyst", "—"),
        "analyzed_at": analysis.get("analyzed_at", "—"),
        "overall_risk_level": analysis.get("overall_risk_level", "medium"),
        "overall_risk_label": _RISK_LEVEL.get(analysis.get("overall_risk_level", ""), "中"),
        "overall_risk_summary": analysis.get("overall_risk_summary", ""),
        "risk_badge_class": _risk_badge_class(analysis.get("overall_risk_level", "medium")),
        "key_findings": analysis.get("key_findings", []),
        "red_flags": analysis.get("red_flags", []),
        "risk_dimensions": analysis.get("risk_dimensions", []),
        "implicit_risk_signals": analysis.get("implicit_risk_signals", []),
        "cross_validation": cross_validation,
        "cross_summary": (
            cross_validation.get("summary")
            if cross_validation
            else analysis.get("cross_statement_checks", {}).get("summary", "")
        ),
        "highlights": highlights,
        "metrics_rows": metrics_rows,
        "charts": charts,
        "narratives": narratives,
    }


def _build_highlights(
    financials: dict[str, Any],
    metrics_doc: dict[str, Any],
    year: Any,
    prior_year: Any,
) -> list[dict[str, str]]:
    specs = [
        ("income_statement", "revenue", "营业收入", True),
        ("income_statement", "net_profit", "净利润", True),
        (None, "gross_margin", "毛利率", False),
        ("cash_flow", "cash_from_operations", "经营现金流", True),
        ("balance_sheet", "inventory", "存货", True),
        ("balance_sheet", "accounts_receivable", "应收账款", True),
    ]
    m = metrics_doc.get("metrics", {})
    rows: list[dict[str, str]] = []
    for stmt, key, label, is_amount in specs:
        if is_amount:
            curr = _item(financials, stmt, key, "current")
            prior = _item(financials, stmt, key, "prior")
            rows.append(
                {
                    "label": label,
                    "current": f"{_yi(curr):.1f}亿" if curr is not None else "—",
                    "prior": f"{_yi(prior):.1f}亿" if prior is not None else "—",
                    "change": _growth(curr, prior),
                    "year": str(year),
                    "prior_year": str(prior_year),
                }
            )
        else:
            curr = m.get(key, {}).get("value")
            prior = m.get(key, {}).get("value_prior")
            rows.append(
                {
                    "label": label,
                    "current": _pct(curr),
                    "prior": _pct(prior),
                    "change": _growth(curr, prior) if curr and prior else "—",
                    "year": str(year),
                    "prior_year": str(prior_year),
                }
            )
    return rows


def _build_metrics_rows(metrics_doc: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, m in metrics_doc.get("metrics", {}).items():
        if not m.get("computable"):
            continue
        val = m.get("value")
        prior = m.get("value_prior")
        is_ratio = key in {
            "debt_to_asset",
            "gross_margin",
            "operating_margin",
            "net_margin",
            "roe",
            "roa",
            "ocf_to_net_profit",
        }
        if is_ratio and val is not None and abs(val) <= 1:
            fmt = lambda v: _pct(v) if v is not None else "—"
        else:
            fmt = lambda v: f"{v:.2f}" if v is not None else "—"
        rows.append(
            {
                "name": _METRIC_LABELS.get(key, key),
                "current": fmt(val),
                "prior": fmt(prior),
                "formula": m.get("formula", ""),
                "category": m.get("category", ""),
            }
        )
    return rows


def _build_charts(run_dir: Path) -> list[dict[str, str]]:
    charts_dir = run_dir / "charts"
    manifest_path = run_dir / "charts_manifest.json"
    chart_files: list[str] = []
    if manifest_path.is_file():
        chart_files = read_json(manifest_path).get("charts", [])
    elif charts_dir.is_dir():
        chart_files = [f"charts/{p.name}" for p in sorted(charts_dir.glob("*.png"))]

    priority = list(_CHART_TITLES.keys())
    ordered: list[str] = []
    for name in priority:
        rel = f"charts/{name}"
        if rel in chart_files:
            ordered.append(rel)
    for rel in chart_files:
        if rel not in ordered:
            ordered.append(rel)

    charts: list[dict[str, str]] = []
    for rel in ordered:
        path = run_dir / rel
        if not path.is_file():
            continue
        fname = path.name
        charts.append(
            {
                "id": fname.replace(".png", ""),
                "title": _CHART_TITLES.get(fname, fname),
                "src": _embed_image(path),
            }
        )
    return charts


def _load_narratives(
    project_root: Path,
    run_id: str,
    analysis: dict[str, Any],
    cross_validation: dict[str, Any] | None,
) -> dict[str, str]:
    narrative_dir = project_root / "analysis" / run_id / "narrative"
    sections_path = project_root / "config" / "report_sections.yaml"
    section_defs: list[dict[str, str]] = []
    if sections_path.is_file():
        cfg = yaml.safe_load(sections_path.read_text(encoding="utf-8"))
        section_defs = cfg.get("sections", [])

    result: dict[str, str] = {}
    for sec in section_defs:
        sid = sec["id"]
        source = sec.get("source", "")
        if not source.endswith(".md"):
            continue
        md_path = narrative_dir / Path(source).name
        if md_path.is_file():
            result[sid] = _md_to_html(md_path.read_text(encoding="utf-8"))
        elif sid == "summary":
            result[sid] = _auto_summary_html(analysis)
        elif sid == "risks":
            result[sid] = _auto_risks_html(analysis)
        elif sid == "conclusion":
            result[sid] = _auto_conclusion_html(analysis, cross_validation)

    return result


def _auto_summary_html(analysis: dict[str, Any]) -> str:
    parts = [f"<p>{analysis.get('overall_risk_summary', '')}</p>", "<ul>"]
    for item in analysis.get("key_findings", []):
        parts.append(f"<li>{item}</li>")
    parts.append("</ul>")
    return "\n".join(parts)


def _auto_risks_html(analysis: dict[str, Any]) -> str:
    parts = ["<h3>红旗信号</h3><ul class='flag-list'>"]
    for flag in analysis.get("red_flags", []):
        parts.append(f"<li>{flag}</li>")
    parts.append("</ul>")
    return "\n".join(parts)


def _auto_conclusion_html(
    analysis: dict[str, Any],
    cross_validation: dict[str, Any] | None,
) -> str:
    conclusion = ""
    if cross_validation:
        conclusion = cross_validation.get("overall_conclusion", "")
    parts = [f"<p>{conclusion}</p>"]
    level = analysis.get("overall_risk_level", "medium")
    parts.append(
        f"<p><strong>综合风险评级：</strong>"
        f"<span class='risk-badge {_risk_badge_class(level)}'>"
        f"{_RISK_LEVEL.get(level, level)}</span></p>"
    )
    return "\n".join(parts)
