"""确定性财务指标计算。"""

from __future__ import annotations

from typing import Any

Period = str  # "current" | "prior"


def compute_metrics(financials: dict[str, Any]) -> dict[str, Any]:
    """基于 financials.json 计算 metrics.json。"""
    bs = financials["statements"]["balance_sheet"]["items"]
    is_ = financials["statements"]["income_statement"]["items"]
    cf = financials["statements"]["cash_flow"]["items"]

    metrics: dict[str, Any] = {}

    def add(name: str, result: dict[str, Any]) -> None:
        metrics[name] = result

    # --- 偿债能力 ---
    add("debt_to_asset", _ratio_metric(
        bs, "total_liabilities", "total_assets",
        formula="total_liabilities / total_assets",
        category="solvency",
    ))
    add("debt_to_equity", _ratio_metric(
        bs, "total_liabilities", "total_equity",
        formula="total_liabilities / total_equity",
        category="solvency",
    ))
    add("current_ratio", _ratio_metric(
        bs, "current_assets", "current_liabilities",
        formula="current_assets / current_liabilities",
        category="solvency",
    ))
    add("quick_ratio", _quick_ratio(bs))
    add("cash_ratio", _ratio_metric(
        bs, "cash", "current_liabilities",
        formula="cash / current_liabilities",
        category="solvency",
    ))

    # --- 盈利能力 ---
    add("gross_margin", _margin(is_, "revenue", "operating_cost", invert_subtrahend=True))
    add("operating_margin", _ratio_metric(
        is_, "operating_profit", "revenue",
        formula="operating_profit / revenue",
        category="profitability",
    ))
    add("net_margin", _ratio_metric(
        is_, "net_profit", "revenue",
        formula="net_profit / revenue",
        category="profitability",
    ))
    add("roe", _roe(is_, bs))
    add("roa", _roa(is_, bs))

    # --- 现金流质量 ---
    add("ocf_to_net_profit", _cross_ratio(
        cf, "cash_from_operations",
        is_, "net_profit",
        formula="cash_from_operations / net_profit",
        category="cash_flow",
    ))
    add("ocf_to_revenue", _cross_ratio(
        cf, "cash_from_operations",
        is_, "revenue",
        formula="cash_from_operations / revenue",
        category="cash_flow",
    ))

    # --- 营运能力（用期初期末均值）---
    add("receivables_turnover", _turnover(is_, bs, "revenue", "accounts_receivable"))
    add("inventory_turnover", _turnover(is_, bs, "operating_cost", "inventory"))
    add("total_asset_turnover", _turnover(is_, bs, "revenue", "total_assets"))

    return {
        "run_id": financials.get("run_id"),
        "entity": financials.get("entity"),
        "period": financials.get("period"),
        "metrics": metrics,
    }


def _get(items: dict[str, Any], key: str, period: Period) -> float | None:
    item = items.get(key)
    if not item:
        return None
    val = item.get(period)
    return float(val) if val is not None else None


def _avg(current: float | None, prior: float | None) -> float | None:
    if current is not None and prior is not None:
        return (current + prior) / 2
    return current if current is not None else prior


def _metric_result(
    *,
    value: float | None,
    value_prior: float | None,
    formula: str,
    inputs: dict[str, Any],
    category: str,
    computable: bool,
) -> dict[str, Any]:
    return {
        "value": round(value, 6) if value is not None else None,
        "value_prior": round(value_prior, 6) if value_prior is not None else None,
        "formula": formula,
        "category": category,
        "inputs": inputs,
        "computable": computable,
    }


def _ratio_metric(
    items: dict[str, Any],
    num_key: str,
    den_key: str,
    *,
    formula: str,
    category: str = "general",
) -> dict[str, Any]:
    inputs: dict[str, Any] = {"current": {}, "prior": {}}
    values: dict[str, float | None] = {}

    for period in ("current", "prior"):
        num = _get(items, num_key, period)
        den = _get(items, den_key, period)
        inputs[period] = {num_key: num, den_key: den}
        if num is not None and den is not None and den != 0:
            values[period] = num / den
        else:
            values[period] = None

    computable = values["current"] is not None
    return _metric_result(
        value=values["current"],
        value_prior=values["prior"],
        formula=formula,
        inputs=inputs,
        category=category,
        computable=computable,
    )


def _cross_ratio(
    left: dict[str, Any],
    left_key: str,
    right: dict[str, Any],
    right_key: str,
    *,
    formula: str,
    category: str,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {"current": {}, "prior": {}}
    values: dict[str, float | None] = {}

    for period in ("current", "prior"):
        num = _get(left, left_key, period)
        den = _get(right, right_key, period)
        inputs[period] = {left_key: num, right_key: den}
        if num is not None and den is not None and den != 0:
            values[period] = num / den
        else:
            values[period] = None

    return _metric_result(
        value=values["current"],
        value_prior=values["prior"],
        formula=formula,
        inputs=inputs,
        category=category,
        computable=values["current"] is not None,
    )


def _quick_ratio(bs: dict[str, Any]) -> dict[str, Any]:
    formula = "(current_assets - inventory) / current_liabilities"
    inputs: dict[str, Any] = {"current": {}, "prior": {}}
    values: dict[str, float | None] = {}

    for period in ("current", "prior"):
        ca = _get(bs, "current_assets", period)
        inv = _get(bs, "inventory", period)
        cl = _get(bs, "current_liabilities", period)
        inputs[period] = {
            "current_assets": ca,
            "inventory": inv,
            "current_liabilities": cl,
        }
        if ca is not None and inv is not None and cl is not None and cl != 0:
            values[period] = (ca - inv) / cl
        else:
            values[period] = None

    return _metric_result(
        value=values["current"],
        value_prior=values["prior"],
        formula=formula,
        inputs=inputs,
        category="solvency",
        computable=values["current"] is not None,
    )


def _margin(
    is_: dict[str, Any],
    revenue_key: str,
    cost_key: str,
    *,
    invert_subtrahend: bool = False,
) -> dict[str, Any]:
    formula = f"({revenue_key} - {cost_key}) / {revenue_key}"
    inputs: dict[str, Any] = {"current": {}, "prior": {}}
    values: dict[str, float | None] = {}

    for period in ("current", "prior"):
        rev = _get(is_, revenue_key, period)
        cost = _get(is_, cost_key, period)
        inputs[period] = {revenue_key: rev, cost_key: cost}
        if rev is not None and cost is not None and rev != 0:
            gross = rev - cost if invert_subtrahend else rev - cost
            values[period] = gross / rev
        else:
            values[period] = None

    return _metric_result(
        value=values["current"],
        value_prior=values["prior"],
        formula=formula,
        inputs=inputs,
        category="profitability",
        computable=values["current"] is not None,
    )


def _roe(is_: dict[str, Any], bs: dict[str, Any]) -> dict[str, Any]:
    formula = "net_profit_parent / avg(equity_attributable_to_parent)"
    inputs: dict[str, Any] = {"current": {}, "prior": {}}
    values: dict[str, float | None] = {}

    for period in ("current", "prior"):
        profit = _get(is_, "net_profit_parent", period)
        eq_c = _get(bs, "equity_attributable_to_parent", "current")
        eq_p = _get(bs, "equity_attributable_to_parent", "prior")
        if period == "current":
            avg_eq = _avg(eq_c, eq_p)
        else:
            # 上期 ROE 需上上期权益，单份年报通常不可得
            avg_eq = None
        inputs[period] = {
            "net_profit_parent": profit,
            "avg_equity_attributable_to_parent": avg_eq,
        }
        if profit is not None and avg_eq is not None and avg_eq != 0:
            values[period] = profit / avg_eq
        else:
            values[period] = None

    return _metric_result(
        value=values["current"],
        value_prior=values["prior"],
        formula=formula,
        inputs=inputs,
        category="profitability",
        computable=values["current"] is not None,
    )


def _roa(is_: dict[str, Any], bs: dict[str, Any]) -> dict[str, Any]:
    formula = "net_profit / avg(total_assets)"
    inputs: dict[str, Any] = {"current": {}, "prior": {}}
    values: dict[str, float | None] = {}

    for period in ("current", "prior"):
        profit = _get(is_, "net_profit", period)
        ta_c = _get(bs, "total_assets", "current")
        ta_p = _get(bs, "total_assets", "prior")
        avg_ta = _avg(ta_c, ta_p) if period == "current" else None
        inputs[period] = {"net_profit": profit, "avg_total_assets": avg_ta}
        if profit is not None and avg_ta is not None and avg_ta != 0:
            values[period] = profit / avg_ta
        else:
            values[period] = None

    return _metric_result(
        value=values["current"],
        value_prior=values["prior"],
        formula=formula,
        inputs=inputs,
        category="profitability",
        computable=values["current"] is not None,
    )


def _turnover(
    is_: dict[str, Any],
    bs: dict[str, Any],
    flow_key: str,
    stock_key: str,
) -> dict[str, Any]:
    formula = f"{flow_key} / avg({stock_key})"
    inputs: dict[str, Any] = {"current": {}, "prior": {}}
    values: dict[str, float | None] = {}

    for period in ("current", "prior"):
        flow = _get(is_, flow_key, period)
        s_c = _get(bs, stock_key, "current")
        s_p = _get(bs, stock_key, "prior")
        avg_stock = _avg(s_c, s_p) if period == "current" else None
        inputs[period] = {flow_key: flow, f"avg_{stock_key}": avg_stock}
        if flow is not None and avg_stock is not None and avg_stock != 0:
            values[period] = flow / avg_stock
        else:
            values[period] = None

    return _metric_result(
        value=values["current"],
        value_prior=values["prior"],
        formula=formula,
        inputs=inputs,
        category="efficiency",
        computable=values["current"] is not None,
    )
