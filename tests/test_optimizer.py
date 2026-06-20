import pandas as pd

from optimizer import generate_market_aware_recommendations, recommendation_execution_order


SETTINGS = {"direct_trade_minimum": 250, "small_trade_round_trip_fee": 1.98,
            "available_cash_eur": 300}


def test_optimizer_blocks_candidate_with_missing_critical_data():
    candidate = pd.DataFrame([{"instrument": "Incomplete ETF", "isin": "NEW", "ticker_id": "N",
                               "category": "Core", "total_score": 9, "manual_review_required": True,
                               "data_confidence": "Low", "data_source": "Manual", "last_updated": "now"}])
    drift = pd.DataFrame([{"category": "Core", "status": "Underweight", "drift_eur": -500}])
    result = generate_market_aware_recommendations(pd.DataFrame(), candidate, drift, SETTINGS)
    assert result.loc[0, "Action"] == "No trade"
    assert "Market Data Engine" in result.loc[0, "Reason"]


def test_optimizer_sells_weak_overweight_before_buying_strong_candidate():
    current = pd.DataFrame([{"instrument": "Weak ETF", "isin": "OLD", "ticker_id": "O", "category": "Growth",
                             "quantity": 10, "current_value_eur": 1000, "total_score": 5,
                             "data_confidence": "High", "data_source": "Test", "last_updated": "now"}])
    candidate = pd.DataFrame([{"instrument": "Strong ETF", "isin": "NEW", "ticker_id": "N", "category": "Core",
                               "total_score": 9, "manual_review_required": False, "latest_price_eur": 100,
                               "fractional_allowed": False, "savings_plan_available": True,
                               "scalable_compatible": True, "direct_trading_available": True,
                               "data_confidence": "High", "data_source": "Test", "last_updated": "now"}])
    drift = pd.DataFrame([{"category": "Growth", "status": "Overweight", "drift_eur": 500},
                          {"category": "Core", "status": "Underweight", "drift_eur": -500}])
    result = generate_market_aware_recommendations(current, candidate, drift, SETTINGS)
    ordered = recommendation_execution_order(result)
    assert result["Action"].isin(["Sell fully", "Sell partially"]).any()
    assert (result["Action"] == "Buy new asset").any()
    assert ordered.iloc[0]["Action"].startswith("Sell")
    assert set(["Data source", "Timestamp", "Data confidence"]).issubset(result.columns)


def test_incomplete_existing_holding_is_not_sold_on_low_score_alone():
    current = pd.DataFrame([{"instrument": "Needs factsheet", "isin": "OLD", "category": "Growth",
                             "quantity": 10, "current_value_eur": 1000, "total_score": 2,
                             "manual_review_required": True, "data_confidence": "Low"}])
    drift = pd.DataFrame([{"category": "Growth", "status": "Overweight", "drift_eur": 500}])
    result = generate_market_aware_recommendations(current, pd.DataFrame(), drift, SETTINGS)
    assert result.loc[0, "Action"] == "Hold"
    assert "manual review" in result.loc[0, "Reason"].lower()


def test_low_candidate_ter_coverage_blocks_new_etf_buy():
    candidate = pd.DataFrame([{"instrument": "Ready ETF", "isin": "NEW", "ticker_id": "N",
                               "asset_type": "ETF", "category": "Core", "total_score": 9,
                               "recommendation_ready": True, "latest_price_eur": 100,
                               "fractional_allowed": False, "savings_plan_available": True,
                               "scalable_compatible": True, "direct_trading_available": True,
                               "data_confidence": "High", "data_source": "Issuer"}])
    drift = pd.DataFrame([{"category": "Core", "status": "Underweight", "drift_eur": -500}])
    settings = {**SETTINGS, "etf_candidate_ter_coverage": 50}
    result = generate_market_aware_recommendations(pd.DataFrame(), candidate, drift, settings)
    assert result.loc[0, "Action"] == "No trade"
    assert "below 75%" in result.loc[0, "Reason"]
