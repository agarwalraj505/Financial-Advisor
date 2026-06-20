"""Rulebook validation, formatting, ordering, and skip-condition helpers."""

from __future__ import annotations

from copy import deepcopy
from math import isclose

import pandas as pd

from rebalancer_rulebook import (ALLOWED_TRADE_PURPOSES, BASE_TARGET_ALLOCATION,
                                 CONFIRMED_BASELINE_HOLDINGS, CONFIRMED_SAVINGS_PLAN,
                                 CURRENT_RULEBOOK, DIRECT_TRADE_RULES,
                                 REGIONS_REQUIRED_FOR_REVIEW, REQUIRED_REBALANCE_SECTIONS,
                                 SAVINGS_PLAN_RULES, THEMES_REQUIRED_FOR_REVIEW)

IMMEDIATE_COLUMNS = ["Action", "Purpose", "Instrument", "ISIN", "Ticker / ID",
                     "Quantity", "Est. value", "Fee issue", "Reason"]
SAVINGS_COLUMNS = ["Instrument", "ISIN", "Current plan", "New plan", "Action"]
ALLOCATION_COLUMNS = ["Category", "Current weight", "Target weight", "Status"]


def get_current_rulebook() -> dict:
    return deepcopy(CURRENT_RULEBOOK.as_dict())


def get_confirmed_baseline_holdings() -> pd.DataFrame:
    return pd.DataFrame(deepcopy(CONFIRMED_BASELINE_HOLDINGS))


def get_confirmed_savings_plan() -> pd.DataFrame:
    return pd.DataFrame(deepcopy(CONFIRMED_SAVINGS_PLAN))


def get_base_target_allocation() -> dict[str, float]:
    return dict(BASE_TARGET_ALLOCATION)


def normalize_trade_purpose(value: str) -> str:
    text = str(value or "").lower()
    if str(value) in ALLOWED_TRADE_PURPOSES:
        return str(value)
    if any(word in text for word in ("reduce", "risk", "overweight", "sell")): return "Risk reduction"
    if any(word in text for word in ("hedge", "gold", "commodity")): return "Hedge"
    if any(word in text for word in ("trend", "momentum", "monitor")): return "Trend"
    if any(word in text for word in ("tactical", "defence", "cyber")): return "Tactical"
    if any(word in text for word in ("growth", "underweight", "new exposure", "add")): return "Growth"
    if any(word in text for word in ("manual", "data", "compatibility", "fee", "cleanup")): return "Cleanup"
    return "Core"


def validate_trade_against_rulebook(trade: dict, context: dict | None = None) -> dict:
    context = context or {}; warnings = []
    action = str(trade.get("Action") or trade.get("action") or "")
    direct = any(token in action.lower() for token in ("buy", "sell", "liquidate", "reduce"))
    value = float(trade.get("Est. value", trade.get("estimated_value_eur", 0)) or 0)
    quantity = trade.get("Quantity", trade.get("quantity", 0))
    justified = bool(trade.get("strongly_justified") or context.get("strongly_justified"))
    if direct and 0 < value < DIRECT_TRADE_RULES["minimum_efficient_trade_eur"] and not justified:
        warnings.append("Direct trade below €250 is fee-inefficient and must not be forced.")
    if direct and action != DIRECT_TRADE_RULES["fractional_liquidation_instruction"]:
        try:
            if not float(quantity).is_integer(): warnings.append("Direct trade quantity must be a whole number.")
        except (TypeError, ValueError):
            warnings.append("Direct trade quantity must be a whole number.")
    if "buy" in action.lower() and not bool(trade.get("scalable_compatible", context.get("scalable_compatible", True))):
        warnings.append("Candidate buy/add blocked until Scalable compatibility is confirmed.")
    if trade.get("sell_only_because_red"): warnings.append("Selling only because the position is red is prohibited.")
    if trade.get("buy_only_because_popular"): warnings.append("Buying only because a theme is popular is prohibited.")
    return {"valid": not warnings, "blocked": bool(warnings), "warnings": warnings,
            "purpose": normalize_trade_purpose(trade.get("Purpose", trade.get("purpose", "")))}


def validate_savings_plan_against_rulebook(plans, monthly_budget: float | None = None) -> dict:
    frame = plans if isinstance(plans, pd.DataFrame) else pd.DataFrame(plans)
    budget = float(monthly_budget if monthly_budget is not None else SAVINGS_PLAN_RULES["monthly_budget_eur"])
    column = "New plan" if "New plan" in frame else "new_plan" if "new_plan" in frame else "current_plan"
    values = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors="coerce").fillna(0)
    total = round(float(values.sum()), 2)
    warnings = []
    if not isclose(total, budget, abs_tol=.01): warnings.append(f"Savings-plan total €{total:.2f} does not equal budget €{budget:.2f}.")
    if (values < 0).any(): warnings.append("Savings-plan amounts cannot be negative.")
    return {"valid": not warnings, "total_eur": total, "budget_eur": budget, "warnings": warnings}


def build_required_rebalance_sections() -> list[str]:
    return list(REQUIRED_REBALANCE_SECTIONS)


def format_immediate_buy_sell_table(recommendations) -> pd.DataFrame:
    frame = recommendations.copy() if isinstance(recommendations, pd.DataFrame) else pd.DataFrame(recommendations)
    if frame.empty:
        return pd.DataFrame([["No immediate rebalance needed", "Cleanup", "Portfolio", "", "", 0, 0.0,
                              "No order", "No sufficiently justified fee-efficient direct trade."]], columns=IMMEDIATE_COLUMNS)
    ticker = "Ticker / ID" if "Ticker / ID" in frame else "Ticker/ID"
    output = pd.DataFrame({"Action": frame.get("Action", ""),
                           "Purpose": frame.get("Purpose", "").map(normalize_trade_purpose),
                           "Instrument": frame.get("Instrument", ""), "ISIN": frame.get("ISIN", ""),
                           "Ticker / ID": frame.get(ticker, ""), "Quantity": frame.get("Quantity", 0),
                           "Est. value": frame.get("Est. value", 0), "Fee issue": frame.get("Fee issue", ""),
                           "Reason": frame.get("Reason", "")})
    direct = output["Action"].astype(str).str.contains("buy|sell|liquidate|reduce", case=False, regex=True)
    output = output[direct].reset_index(drop=True)
    return output if not output.empty else format_immediate_buy_sell_table(pd.DataFrame())


def format_savings_plan_table(plans) -> pd.DataFrame:
    frame = plans.copy() if isinstance(plans, pd.DataFrame) else pd.DataFrame(plans)
    aliases = {"instrument": "Instrument", "isin": "ISIN", "current_plan": "Current plan",
               "new_plan": "New plan", "action": "Action"}
    frame = frame.rename(columns=aliases)
    for column in SAVINGS_COLUMNS:
        if column not in frame: frame[column] = 0.0 if "plan" in column.lower() else ""
    return frame[SAVINGS_COLUMNS]


def format_allocation_table(current_allocations, target_allocations: dict | None = None) -> pd.DataFrame:
    targets = target_allocations or get_base_target_allocation()
    frame = current_allocations.copy() if isinstance(current_allocations, pd.DataFrame) else pd.DataFrame(current_allocations)
    frame = frame.rename(columns={"category": "Category", "current_weight": "Current weight",
                                  "target_weight": "Target weight", "status": "Status"})
    if "Category" not in frame: frame["Category"] = list(targets)
    if "Target weight" not in frame: frame["Target weight"] = frame["Category"].map(targets).fillna(0)
    if "Current weight" not in frame: frame["Current weight"] = 0.0
    if "Status" not in frame:
        drift = pd.to_numeric(frame["Current weight"], errors="coerce").fillna(0) - pd.to_numeric(frame["Target weight"], errors="coerce").fillna(0)
        frame["Status"] = drift.map(lambda value: "Overweight" if value > 1 else "Underweight" if value < -1 else "On target")
    return frame[ALLOCATION_COLUMNS]


def create_skip_conditions(context: dict | None = None) -> list[str]:
    context = context or {}; conditions = [
        "Skip if Scalable live buy/sell prices or availability cannot be checked.",
        "Skip fee-inefficient direct trades below €250 unless the reason is unusually strong and documented.",
        "Skip when market data, FX, or critical candidate metadata is missing or stale.",
        "Skip when the trade is driven only by a red day, recent popularity, or available cash.",
        "Skip when taxes, spread, or liquidity make the expected benefit unclear.",
        "Skip when no candidate offers a clearly better portfolio fit or risk/reward outcome.",
    ]
    if context.get("price_coverage", 100) < 90: conditions.append("Defer new buys while price coverage remains below 90%.")
    return conditions


def create_execution_order(sells, buys, savings_changes=None) -> pd.DataFrame:
    def records(value): return value.to_dict("records") if isinstance(value, pd.DataFrame) else list(value or [])
    rows = []
    for stage, values in (("Sell first", sells), ("Buy after funded sells", buys),
                          ("Update savings plans manually", savings_changes)):
        for item in records(values): rows.append({"Stage": stage, **item})
    for index, row in enumerate(rows, 1): row["Step"] = index
    return pd.DataFrame(rows)


def validate_rebalance_guardrails(context: dict) -> dict:
    trades = list(context.get("trades") or [])
    trade_checks = [validate_trade_against_rulebook(trade, context) for trade in trades]
    considered = set(context.get("themes_considered") or [])
    regions = set(context.get("regions_considered") or [])
    checks = [
        ("Last recommendation not assumed implemented", not context.get("last_recommendation_assumed_implemented", False), "Re-evaluate from the confirmed holdings."),
        ("Latest confirmed baseline or newer user data used", bool(context.get("baseline_source")), str(context.get("baseline_source", "Missing"))),
        ("Market data and news refreshed", bool(context.get("market_data_refreshed") and context.get("news_refreshed")), "Both evidence sets are required."),
        ("Sectors beyond AI/semiconductors compared", bool(considered - {"AI infrastructure", "Semiconductors"}), "Broad comparison required."),
        ("Regions beyond US/Europe considered", bool(regions - {"United States", "Europe"}), "Include EM and Asian regions."),
        ("Required themes checked", set(THEMES_REQUIRED_FOR_REVIEW).issubset(considered), "Review the complete rulebook theme list."),
        ("Themes considered separated from themes bought", "themes_bought" in context and "themes_watchlisted" in context, "Keep considered/bought/watchlisted distinct."),
        ("No forced trades below €250", all(check["valid"] or not any("below €250" in warning for warning in check["warnings"]) for check in trade_checks), "Use savings plans for small allocations."),
        ("Whole quantities for direct trades", all(not any("whole number" in warning for warning in check["warnings"]) for check in trade_checks), "No fractional direct orders."),
        ("Savings plans used for gradual/fractional allocation", bool(context.get("savings_plan_reviewed", False)), "Monthly plan reviewed."),
        ("Every trade has a current reason", all(str(trade.get("Reason", trade.get("reason", ""))).strip() for trade in trades), "Explain why now."),
        ("Skip conditions included", bool(context.get("skip_conditions") or create_skip_conditions(context)), "Execution may be deferred."),
        ("Scalable live prices required", bool(context.get("scalable_price_check_required", True)), "Public prices are estimates."),
        ("No emotional red-day selling", not context.get("emotional_selling", False), "Red performance alone is not a sell reason."),
        ("No popularity-only buying", not context.get("popularity_only_buying", False), "Popularity alone is not a buy reason."),
    ]
    return {"passed": all(item[1] for item in checks),
            "checks": [{"check_name": name, "passed": passed, "notes": notes} for name, passed, notes in checks],
            "trade_checks": trade_checks}


def create_rebalance_checklist(context: dict) -> dict:
    guardrails = validate_rebalance_guardrails(context)
    return {"guardrails": guardrails, "skip_conditions": create_skip_conditions(context),
            "execution_warning": "Check live Scalable price before execution.",
            "can_execute": guardrails["passed"]}
