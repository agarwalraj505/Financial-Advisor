import pandas as pd

from scoring import (calculate_cost_score, calculate_portfolio_fit_score,
                     calculate_total_score, score_assets)


def test_weighted_total_score():
    assert calculate_total_score(8, 8, 8, 8, 8) == 8


def test_underweight_category_improves_fit_and_small_trade_hurts_cost():
    asset = {"asset_type": "ETF", "category": "AI", "ter_pct": .2,
             "manual_spread_estimate_pct": .1, "liquidity_score": 8,
             "savings_plan_available": False, "scalable_compatible": True}
    assert calculate_portfolio_fit_score(asset, {"AI": -8}) > calculate_portfolio_fit_score(asset, {"AI": 8})
    assert calculate_cost_score(asset, 100, 250) < calculate_cost_score(asset, 300, 250)


def test_missing_critical_data_forces_manual_review_band():
    assets = pd.DataFrame([{"instrument": "Unknown ETF", "isin": "X", "price_symbol": "X",
                            "asset_type": "ETF", "category": "Core", "ter_pct": None,
                            "fund_size_eur": None, "manual_spread_estimate_pct": None}])
    research = pd.DataFrame([{"price_symbol": "X", "momentum_score": 10,
                              "research_confidence": "High", "data_source": "Test", "last_updated": "now"}])
    drift = pd.DataFrame([{"category": "Core", "drift_pct_points": -10}])
    scored = score_assets(assets, research, drift, {"portfolio_total_eur": 1000,
        "direct_trade_minimum": 250, "max_single_holding_weight": 25,
        "risk_profile": "Aggressive", "max_crypto_weight": 5})
    assert scored.loc[0, "score_band"] == "Data enrichment required before buy/add"
