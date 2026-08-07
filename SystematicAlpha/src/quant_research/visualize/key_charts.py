"""报告关键指标：趋势图与结构图。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from quant_research.visualize.helpers import item as _item, yi as _yi
from quant_research.visualize.themes import COLORS


def _years(financials: dict[str, Any]) -> tuple[str, str]:
    y = financials.get("period", {}).get("report_year", 2025)
    return str(y - 1), str(y)


def _growth_pct(current: float | None, prior: float | None) -> str:
    if current is None or prior is None or prior == 0:
        return ""
    pct = (current - prior) / prior * 100
    return f"{pct:+.1f}%"


def _annotate_bars(ax: plt.Axes, bars, labels: list[str]) -> None:
    for bar, label in zip(bars, labels):
        h = bar.get_height()
        if h == 0:
            continue
        ax.annotate(
            label,
            xy=(bar.get_x() + bar.get_width() / 2, h),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            color=COLORS["secondary"],
        )


def chart_key_indicators_trend(
    financials: dict[str, Any],
    metrics: dict[str, Any],
    path: Path,
) -> Path:
    """六宫格：营收、净利润、经营现金流、存货、应收账款、毛利率。"""
    y0, y1 = _years(financials)
    m = metrics.get("metrics", {})

    specs = [
        ("income_statement", "revenue", "营业收入（亿元）", False),
        ("income_statement", "net_profit", "净利润（亿元）", False),
        ("cash_flow", "cash_from_operations", "经营现金流（亿元）", False),
        ("balance_sheet", "inventory", "存货（亿元）", False),
        ("balance_sheet", "accounts_receivable", "应收账款（亿元）", False),
        (None, None, "毛利率（%）", True),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    axes_flat = axes.flatten()

    for ax, spec in zip(axes_flat, specs):
        stmt, key, title, is_margin = spec
        if is_margin:
            prior_v = (m.get("gross_margin", {}).get("value_prior") or 0) * 100
            curr_v = (m.get("gross_margin", {}).get("value") or 0) * 100
            vals = [prior_v, curr_v]
        else:
            vals = [
                _yi(_item(financials, stmt, key, "prior")),
                _yi(_item(financials, stmt, key, "current")),
            ]
        bars = ax.bar([y0, y1], vals, color=[COLORS["prior"], COLORS["current"]], width=0.55)
        if not is_margin:
            raw = [
                _item(financials, stmt, key, "prior"),
                _item(financials, stmt, key, "current"),
            ]
            growth = _growth_pct(raw[1], raw[0])
            _annotate_bars(ax, bars, ["", growth])
        else:
            growth = _growth_pct(vals[1], vals[0])
            _annotate_bars(ax, bars, ["", growth])
        ax.set_title(title, fontsize=11)
        ax.set_ylabel("%" if is_margin else "亿元")
        ax.grid(axis="y", alpha=0.3)

    entity = financials.get("entity", {}).get("company_name", "")
    fig.suptitle(f"{entity} 关键指标同比趋势", fontsize=14, y=1.01)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_margin_trend(
    financials: dict[str, Any],
    metrics: dict[str, Any],
    path: Path,
) -> Path:
    """毛利率、净利率、营业利润率趋势。"""
    y0, y1 = _years(financials)
    m = metrics.get("metrics", {})
    keys = ["gross_margin", "net_margin", "operating_margin"]
    labels = ["毛利率", "净利率", "营业利润率"]
    x = np.arange(len(keys))
    w = 0.35

    prior = [(m.get(k, {}).get("value_prior") or 0) * 100 for k in keys]
    curr = [(m.get(k, {}).get("value") or 0) * 100 for k in keys]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w / 2, prior, w, label=y0, color=COLORS["prior"])
    ax.bar(x + w / 2, curr, w, label=y1, color=COLORS["current"])
    for i, (p, c) in enumerate(zip(prior, curr)):
        if p:
            ax.text(i - w / 2, p + 0.3, _growth_pct(c / 100, p / 100), ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("%")
    ax.set_title("盈利能力比率趋势")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_working_capital_trend(financials: dict[str, Any], path: Path) -> Path:
    """营运资本相关：应收、存货、合同负债、预付款。"""
    y0, y1 = _years(financials)
    items = [
        ("accounts_receivable", "应收账款"),
        ("inventory", "存货"),
        ("contract_liabilities", "合同负债"),
        ("prepayments", "预付款项"),
    ]
    x = np.arange(len(items))
    w = 0.35
    prior, curr = [], []
    for key, _ in items:
        prior.append(_yi(_item(financials, "balance_sheet", key, "prior")))
        curr.append(_yi(_item(financials, "balance_sheet", key, "current")))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - w / 2, prior, w, label=y0, color=COLORS["prior"])
    ax.bar(x + w / 2, curr, w, label=y1, color=COLORS["current"])
    ax.set_xticks(x)
    ax.set_xticklabels([lb for _, lb in items])
    ax.set_ylabel("亿元")
    ax.set_title("营运资本科目趋势")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_income_structure(financials: dict[str, Any], path: Path) -> Path:
    """收入结构：营收 vs 营业成本 vs 毛利（亿元）。"""
    y0, y1 = _years(financials)
    years = [y0, y1]
    revenue = [
        _yi(_item(financials, "income_statement", "revenue", "prior")),
        _yi(_item(financials, "income_statement", "revenue", "current")),
    ]
    cost = [
        _yi(_item(financials, "income_statement", "operating_cost", "prior")),
        _yi(_item(financials, "income_statement", "operating_cost", "current")),
    ]
    gross = [r - c for r, c in zip(revenue, cost)]

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(2)
    w = 0.5
    ax.bar(x, cost, w, label="营业成本", color=COLORS["secondary"])
    ax.bar(x, gross, w, bottom=cost, label="毛利", color=COLORS["positive"])
    ax.plot(x, revenue, "o--", color=COLORS["primary"], label="营业收入", linewidth=2, markersize=8)
    for i, r in enumerate(revenue):
        ax.text(i, r + 30, f"{r:.0f}亿", ha="center", fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(years)
    ax.set_ylabel("亿元")
    ax.set_title("收入与成本结构（堆叠毛利）")
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_asset_composition(financials: dict[str, Any], path: Path) -> Path:
    """2025 资产结构饼图。"""
    y1 = _years(financials)[1]
    slices = [
        ("current_assets", "流动资产"),
        ("non_current_assets", "非流动资产"),
    ]
    values, labels = [], []
    for key, label in slices:
        v = _yi(_item(financials, "balance_sheet", key, "current"))
        if v > 0:
            values.append(v)
            labels.append(f"{label}\n{v:.0f}亿")

    fig, ax = plt.subplots(figsize=(6, 6))
    colors = [COLORS["primary"], COLORS["accent"]]
    ax.pie(values, labels=labels, autopct="%1.1f%%", colors=colors, startangle=90)
    ax.set_title(f"{y1} 资产结构")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_liability_equity_composition(financials: dict[str, Any], path: Path) -> Path:
    """2025 负债与权益结构饼图。"""
    y1 = _years(financials)[1]
    values = [
        _yi(_item(financials, "balance_sheet", "total_liabilities", "current")),
        _yi(_item(financials, "balance_sheet", "total_equity", "current")),
    ]
    labels = [
        f"负债合计\n{values[0]:.0f}亿",
        f"所有者权益\n{values[1]:.0f}亿",
    ]
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        colors=[COLORS["negative"], COLORS["positive"]],
        startangle=90,
    )
    ax.set_title(f"{y1} 负债与权益结构")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_cash_profit_comparison(financials: dict[str, Any], path: Path) -> Path:
    """净利润 vs 经营现金流对比（利润质量）。"""
    y0, y1 = _years(financials)
    metrics_data = [
        ("净利润", "income_statement", "net_profit"),
        ("经营现金流", "cash_flow", "cash_from_operations"),
    ]
    x = np.arange(2)
    w = 0.35
    fig, ax = plt.subplots(figsize=(8, 5))

    for i, (name, stmt, key) in enumerate(metrics_data):
        prior = _yi(_item(financials, stmt, key, "prior"))
        curr = _yi(_item(financials, stmt, key, "current"))
        offset = (i - 0.5) * w
        ax.bar(x + offset - w / 2, [prior, curr], w * 0.9, label=name)

    ax.set_xticks(x)
    ax.set_xticklabels([y0, y1])
    ax.set_ylabel("亿元")
    ax.set_title("净利润与经营现金流对比")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def generate_key_indicator_charts(
    financials: dict[str, Any],
    metrics: dict[str, Any],
    output_dir: Path,
) -> list[Path]:
    """生成报告用关键指标图表集。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    charts = [
        (chart_key_indicators_trend, "key_indicators_trend.png"),
        (chart_margin_trend, "margin_trend.png"),
        (chart_working_capital_trend, "working_capital_trend.png"),
        (chart_income_structure, "income_structure.png"),
        (chart_asset_composition, "asset_composition.png"),
        (chart_liability_equity_composition, "liability_equity_composition.png"),
        (chart_cash_profit_comparison, "cash_profit_comparison.png"),
    ]
    paths: list[Path] = []
    for fn, name in charts:
        out = output_dir / name
        if fn is chart_key_indicators_trend or fn is chart_margin_trend:
            fn(financials, metrics, out)
        else:
            fn(financials, out)
        paths.append(out)
    return paths
