"""financials 契约校验与会计恒等式自检。"""

from __future__ import annotations

from typing import Any


def validate_financials(data: dict[str, Any], schema_path: str | None = None) -> list[str]:
    """校验 financials 结构，返回 warnings。"""
    warnings: list[str] = []
    for stmt in ("balance_sheet", "income_statement", "cash_flow"):
        if stmt not in data.get("statements", {}):
            warnings.append(f"缺少报表: {stmt}")
    return warnings


def check_balance_equation(financials: dict[str, Any]) -> dict[str, Any]:
    """
    会计恒等式：资产总计 = 负债合计 + 所有者权益合计
    或 资产总计 = 负债和所有者权益总计
    """
    items = financials["statements"]["balance_sheet"]["items"]
    unit = financials["period"]["unit"]

    def _vals(key: str) -> tuple[float | None, float | None]:
        item = items.get(key, {})
        return item.get("current"), item.get("prior")

    assets_c, assets_p = _vals("total_assets")
    liab_c, liab_p = _vals("total_liabilities")
    equity_c, equity_p = _vals("total_equity")
    le_c, le_p = _vals("total_liabilities_and_equity")

    results: list[dict[str, Any]] = []

    if assets_c is not None and liab_c is not None and equity_c is not None:
        rhs_c = liab_c + equity_c
        diff_c = assets_c - rhs_c
        results.append(
            {
                "formula": "total_assets = total_liabilities + total_equity",
                "period": "current",
                "lhs": assets_c,
                "rhs": rhs_c,
                "diff": diff_c,
                "passed": abs(diff_c) < 1.0,
            }
        )

    if assets_p is not None and liab_p is not None and equity_p is not None:
        rhs_p = liab_p + equity_p
        diff_p = assets_p - rhs_p
        results.append(
            {
                "formula": "total_assets = total_liabilities + total_equity",
                "period": "prior",
                "lhs": assets_p,
                "rhs": rhs_p,
                "diff": diff_p,
                "passed": abs(diff_p) < 1.0,
            }
        )

    if assets_c is not None and le_c is not None:
        diff_c2 = assets_c - le_c
        results.append(
            {
                "formula": "total_assets = total_liabilities_and_equity",
                "period": "current",
                "lhs": assets_c,
                "rhs": le_c,
                "diff": diff_c2,
                "passed": abs(diff_c2) < 1.0,
            }
        )

    if assets_p is not None and le_p is not None:
        diff_p2 = assets_p - le_p
        results.append(
            {
                "formula": "total_assets = total_liabilities_and_equity",
                "period": "prior",
                "lhs": assets_p,
                "rhs": le_p,
                "diff": diff_p2,
                "passed": abs(diff_p2) < 1.0,
            }
        )

    all_passed = all(r["passed"] for r in results) if results else False

    return {
        "run_id": financials.get("run_id"),
        "unit": unit,
        "checks": results,
        "passed": all_passed,
    }
