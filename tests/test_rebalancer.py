import pandas as pd

from rebalancer import (calculate_allocation, calculate_drift, calculate_total_value,
                        fee_warning, recommend_savings_plans)


def test_total_portfolio_value():
    holdings = pd.DataFrame({"current_value": [100.0, 50.25, 0.75]})
    assert calculate_total_value(holdings) == 151.0


def test_old_value_column_remains_supported():
    assert calculate_total_value(pd.DataFrame({"value": [100.0, 25.0]})) == 125.0


def test_category_weights():
    holdings = pd.DataFrame({"category": ["Core", "Growth", "Growth"], "current_value": [25, 25, 50]})
    allocation = calculate_allocation(holdings).set_index("category")
    assert allocation.loc["Core", "current_weight"] == 25
    assert allocation.loc["Growth", "current_weight"] == 75


def test_drift_calculation():
    holdings = pd.DataFrame({"category": ["Core", "Growth"], "current_value": [60, 40]})
    drift = calculate_drift(holdings, {"Core": 50, "Growth": 50}).set_index("category")
    assert drift.loc["Core", "drift_pct_points"] == 10
    assert drift.loc["Growth", "drift_eur"] == -10
    assert drift.loc["Growth", "status"] == "Underweight"


def test_fee_warning_for_trades_below_250():
    warning = fee_warning(249.99)
    assert "Below €250" in warning
    assert "€0.99" in warning
    assert "€250+" in fee_warning(250)


def test_savings_plan_recommendation_logic():
    plans = pd.DataFrame({"instrument": ["Core ETF", "Growth ETF", "Gold"], "isin": ["C", "G", "X"],
                          "category": ["Core", "Growth", "Commodities"], "current_plan": [100, 100, 100]})
    drift = pd.DataFrame({"category": ["Core", "Growth", "Commodities"],
                          "status": ["Underweight", "Overweight", "On target"]})
    result = recommend_savings_plans(plans, drift).set_index("Instrument")
    assert result.loc["Core ETF", "New plan"] == 125
    assert result.loc["Growth ETF", "New plan"] == 50
    assert result.loc["Gold", "New plan"] == 100
