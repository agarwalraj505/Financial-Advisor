import pandas as pd

from savings_plan_optimizer import optimize_savings_plans


def test_savings_optimizer_adds_strong_assets_removes_weak_and_matches_budget():
    plans = pd.DataFrame([{"instrument": "Weak ETF", "isin": "WEAK", "category": "Growth", "current_plan": 100}])
    assets = pd.DataFrame([
        {"instrument": "Weak ETF", "isin": "WEAK", "category": "Growth", "total_score": 5,
         "manual_review_required": False, "savings_plan_available": True},
        {"instrument": "Strong Core", "isin": "CORE", "category": "Core", "total_score": 9,
         "manual_review_required": False, "savings_plan_available": True},
        {"instrument": "Strong EM", "isin": "EM", "category": "EM", "total_score": 8.5,
         "manual_review_required": False, "savings_plan_available": True}])
    drift = pd.DataFrame([{"category": "Growth", "status": "Overweight", "drift_pct_points": 8},
                          {"category": "Core", "status": "Underweight", "drift_pct_points": -10},
                          {"category": "EM", "status": "Underweight", "drift_pct_points": -5}])
    result = optimize_savings_plans(plans, assets, drift, 300)
    assert result["New plan"].sum() == 300
    assert result.loc[result["ISIN"] == "WEAK", "New plan"].iloc[0] == 0
    assert set(result[result["New plan"] > 0]["ISIN"]) == {"CORE", "EM"}


def test_no_qualified_asset_keeps_budget_unallocated():
    result = optimize_savings_plans(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 300)
    assert result.loc[0, "Instrument"] == "Unallocated monthly budget"
    assert result.loc[0, "New plan"] == 300


def test_incomplete_existing_plan_is_kept_pending_review():
    plans = pd.DataFrame([{"instrument": "Needs review", "isin": "X", "category": "Core", "current_plan": 100}])
    assets = pd.DataFrame([{"instrument": "Needs review", "isin": "X", "category": "Core", "total_score": 1,
                            "manual_review_required": True, "savings_plan_available": True}])
    result = optimize_savings_plans(plans, assets, pd.DataFrame(), 100)
    assert result.loc[result["ISIN"] == "X", "New plan"].iloc[0] == 100
    assert result.loc[result["ISIN"] == "X", "Action"].iloc[0] == "Keep pending manual review"
