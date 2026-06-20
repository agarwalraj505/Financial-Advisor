"""Monthly savings-plan allocation using scores, drift, and an exact budget."""

from __future__ import annotations

import pandas as pd

from scoring import allocation_bucket
from rebalancer_rulebook import SAVINGS_PLAN_RULES
from rulebook_engine import validate_savings_plan_against_rulebook

SAVINGS_COLUMNS = ["Instrument", "ISIN", "Current plan", "New plan", "Action", "Reason", "Score"]


def optimize_savings_plans(plans: pd.DataFrame, scored_assets: pd.DataFrame, drift: pd.DataFrame,
                           monthly_budget: float = SAVINGS_PLAN_RULES["monthly_budget_eur"]) -> pd.DataFrame:
    score_lookup = scored_assets.drop_duplicates("isin").set_index("isin").to_dict("index") if not scored_assets.empty else {}
    drift_lookup = drift.set_index("category").to_dict("index") if not drift.empty else {}
    current_lookup = plans.set_index("isin")["current_plan"].to_dict() if not plans.empty else {}
    locked = {}
    for _, plan in plans.iterrows():
        isin = str(plan.get("isin", ""))
        asset = score_lookup.get(isin)
        if asset is None or bool(asset.get("manual_review_required", False)):
            locked[isin] = float(plan.get("current_plan", 0) or 0)
    locked_total = sum(locked.values())
    if locked_total > monthly_budget and locked_total:
        locked = {isin: round(value * monthly_budget / locked_total, 2) for isin, value in locked.items()}
        first = next(iter(locked))
        locked[first] = round(locked[first] + monthly_budget - sum(locked.values()), 2)
    remaining_budget = max(0.0, monthly_budget - sum(locked.values()))
    eligible = []
    for _, asset in scored_assets.drop_duplicates("isin").iterrows():
        category = allocation_bucket(str(asset.get("category", "")))
        category_status = drift_lookup.get(category, {}).get("status", "On target")
        if (float(asset.get("total_score", 0) or 0) >= 8 and
                not bool(asset.get("manual_review_required", False)) and
                bool(asset.get("savings_plan_available", False)) and category_status != "Overweight" and
                str(asset.get("isin", "")) not in locked):
            underweight = max(1.0, abs(float(drift_lookup.get(category, {}).get("drift_pct_points", 0) or 0)))
            eligible.append((asset, float(asset.get("total_score", 0)) * underweight))
    allocations = locked.copy()
    total_weight = sum(weight for _, weight in eligible)
    for asset, weight in eligible:
        allocations[str(asset.get("isin", ""))] = round(remaining_budget * weight / total_weight, 2) if total_weight else 0.0
    eligible_isins = [str(asset.get("isin", "")) for asset, _ in eligible]
    if eligible_isins:
        best = max(eligible_isins, key=lambda isin: allocations[isin])
        allocations[best] = round(allocations[best] + monthly_budget - sum(allocations.values()), 2)
    rows = []
    all_isins = set(current_lookup) | set(allocations)
    for isin in all_isins:
        asset = score_lookup.get(isin, {})
        current, new = float(current_lookup.get(isin, 0)), float(allocations.get(isin, 0))
        if isin in locked:
            action = "Keep pending manual review"
            reason = "Critical data is incomplete; do not remove or increase this plan without review."
        elif new == 0 and current > 0:
            action = "Remove / pause"
            reason = "Weak, incomplete, or overweight setup; redirect monthly contributions."
        elif current == 0 and new > 0:
            action = "Add new savings plan"
            reason = "High-scoring asset in a useful non-overweight category."
        elif new > current:
            action = "Increase"
            reason = "Raise funding toward a high-scoring underweight exposure."
        elif new < current:
            action = "Reduce"
            reason = "Reduce funding to avoid overfunding or improve score quality."
        else:
            action, reason = "Keep", "Current amount remains aligned with the optimized budget."
        plan_match = plans[plans["isin"] == isin] if not plans.empty else pd.DataFrame()
        instrument = asset.get("instrument") or (plan_match.iloc[0]["instrument"] if not plan_match.empty else isin)
        rows.append({"Instrument": instrument, "ISIN": isin, "Current plan": round(current, 2),
                     "New plan": round(new, 2), "Action": action, "Reason": reason,
                     "Score": round(float(asset.get("total_score", 0) or 0), 2)})
    allocated_total = sum(allocations.values())
    if allocated_total < monthly_budget:
        rows.append({"Instrument": "Unallocated monthly budget", "ISIN": "CASH", "Current plan": 0.0,
                     "New plan": round(monthly_budget - allocated_total, 2), "Action": "Hold unallocated",
                     "Reason": "No candidate meets the quality, score, and allocation rules; do not force investment.", "Score": 0.0})
    result = pd.DataFrame(rows, columns=SAVINGS_COLUMNS).sort_values("New plan", ascending=False).reset_index(drop=True)
    result.attrs["rulebook_validation"] = validate_savings_plan_against_rulebook(result, monthly_budget)
    return result
