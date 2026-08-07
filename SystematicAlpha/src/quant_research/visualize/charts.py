"""图表生成（matplotlib）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from quant_research.visualize.helpers import item as _item, yi as _yi
from quant_research.visualize.key_charts import generate_key_indicator_charts
from quant_research.visualize.themes import COLORS, setup_chinese_font

_CHART_LABELS: dict[str, str] = {
    "debt_to_asset": "资产负债率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "gross_margin": "毛利率",
    "operating_margin": "营业利润率",
    "net_margin": "净利率",
    "roe": "ROE",
    "roa": "ROA",
    "ocf_to_net_profit": "经营现金流/净利润",
}


def generate_charts(
    financials: dict[str, Any],
    metrics: dict[str, Any],
    analysis: dict[str, Any] | None,
    output_dir: Path,
) -> list[Path]:
    """生成 charts/*.png，返回文件路径列表。"""
    setup_chinese_font()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    paths.append(_chart_balance_structure(financials, output_dir / "balance_structure.png"))
    paths.append(_chart_revenue_profit(financials, output_dir / "revenue_profit.png"))
    paths.append(_chart_profitability(metrics, output_dir / "profitability.png"))
    paths.append(_chart_cash_flow(financials, output_dir / "cash_flow.png"))
    paths.append(_chart_solvency(metrics, output_dir / "solvency.png"))
    paths.append(_chart_key_metrics(metrics, output_dir / "key_metrics.png"))

    if analysis and analysis.get("chart_overrides", {}).get("risk_radar"):
        paths.append(_chart_risk_radar(analysis, output_dir / "risk_radar.png"))

    paths.extend(generate_key_indicator_charts(financials, metrics, output_dir))

    return paths


def _chart_balance_structure(financials: dict[str, Any], path: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    periods = [("current", "2025"), ("prior", "2024")]

    for ax, (period, label) in zip(axes, periods):
        assets = [
            _yi(_item(financials, "balance_sheet", "current_assets", period)),
            _yi(_item(financials, "balance_sheet", "non_current_assets", period)),
        ]
        liab_eq = [
            _yi(_item(financials, "balance_sheet", "current_liabilities", period)),
            _yi(_item(financials, "balance_sheet", "non_current_liabilities", period)),
            _yi(_item(financials, "balance_sheet", "total_equity", period)),
        ]
        x = np.arange(2)
        width = 0.5
        bottom_a = 0
        for val, color, name in zip(
            assets,
            [COLORS["primary"], COLORS["accent"]],
            ["流动资产", "非流动资产"],
        ):
            ax.bar(0, val, width, bottom=bottom_a, color=color, label=name if period == "current" else "")
            bottom_a += val
        bottom_l = 0
        for val, color, name in zip(
            liab_eq,
            [COLORS["negative"], COLORS["secondary"], COLORS["positive"]],
            ["流动负债", "非流动负债", "所有者权益"],
        ):
            ax.bar(1, val, width, bottom=bottom_l, color=color, label=name if period == "current" else "")
            bottom_l += val
        ax.set_xticks(x)
        ax.set_xticklabels(["资产", "负债+权益"])
        ax.set_ylabel("亿元")
        ax.set_title(label)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("资产负债结构", fontsize=14, y=1.06)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _chart_revenue_profit(financials: dict[str, Any], path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["2024", "2025"]
    revenue = [
        _yi(_item(financials, "income_statement", "revenue", "prior")),
        _yi(_item(financials, "income_statement", "revenue", "current")),
    ]
    profit = [
        _yi(_item(financials, "income_statement", "net_profit", "prior")),
        _yi(_item(financials, "income_statement", "net_profit", "current")),
    ]
    x = np.arange(2)
    w = 0.35
    ax.bar(x - w / 2, revenue, w, label="营业收入", color=COLORS["primary"])
    ax.bar(x + w / 2, profit, w, label="净利润", color=COLORS["positive"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("亿元")
    ax.set_title("营收与净利润对比")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _chart_profitability(metrics: dict[str, Any], path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 5))
    keys = ["gross_margin", "operating_margin", "net_margin", "roe", "roa"]
    labels = [_CHART_LABELS.get(k, k) for k in keys]
    m = metrics.get("metrics", {})
    current = [(m[k]["value"] * 100 if m.get(k, {}).get("value") is not None else 0) for k in keys]
    prior = [
        (m[k]["value_prior"] * 100 if m.get(k, {}).get("value_prior") is not None else 0)
        for k in keys
    ]
    x = np.arange(len(keys))
    w = 0.35
    ax.bar(x - w / 2, prior, w, label="上期", color=COLORS["prior"])
    ax.bar(x + w / 2, current, w, label="本期", color=COLORS["current"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("%")
    ax.set_title("盈利能力指标")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _chart_cash_flow(financials: dict[str, Any], path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    keys = ["cash_from_operations", "cash_from_investing", "cash_from_financing"]
    labels = ["经营活动", "投资活动", "筹资活动"]
    values = [_yi(_item(financials, "cash_flow", k, "current")) for k in keys]
    colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in values]
    ax.bar(labels, values, color=colors)
    ax.axhline(0, color="#ccc", linewidth=0.8)
    ax.set_ylabel("亿元（2025）")
    ax.set_title("现金流量结构")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _chart_solvency(metrics: dict[str, Any], path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    keys = ["debt_to_asset", "current_ratio", "quick_ratio", "cash_ratio"]
    labels = [_CHART_LABELS.get(k, k) for k in keys]
    m = metrics.get("metrics", {})
    current = [m[k]["value"] for k in keys if m.get(k, {}).get("value") is not None]
    labels = labels[: len(current)]
    prior_vals = [
        m[k]["value_prior"] for k in keys[: len(current)]
        if m.get(k, {}).get("value_prior") is not None
    ]
    x = np.arange(len(current))
    w = 0.35
    ax.bar(x - w / 2, prior_vals, w, label="上期", color=COLORS["prior"])
    ax.bar(x + w / 2, current, w, label="本期", color=COLORS["current"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=10, ha="right")
    ax.set_title("偿债能力指标")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _chart_key_metrics(metrics: dict[str, Any], path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 5))
    keys = [
        "receivables_turnover",
        "inventory_turnover",
        "total_asset_turnover",
        "ocf_to_net_profit",
    ]
    labels = ["应收周转", "存货周转", "总资产周转", "现金流/净利润"]
    m = metrics.get("metrics", {})
    values = [m[k]["value"] for k in keys]
    ax.barh(labels, values, color=COLORS["primary"])
    ax.set_title("营运与现金流效率")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _chart_risk_radar(analysis: dict[str, Any], path: Path) -> Path:
    radar = analysis["chart_overrides"]["risk_radar"]
    labels = list(radar.keys())
    values = [radar[k] for k in labels]
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    values_cycle = values + values[:1]
    angles_cycle = angles + angles[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    ax.plot(angles_cycle, values_cycle, "o-", color=COLORS["primary"])
    ax.fill(angles_cycle, values_cycle, alpha=0.2, color=COLORS["primary"])
    ax.set_xticks(angles)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 5)
    ax.set_title("风险雷达图（1=低，5=高）", pad=20)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
