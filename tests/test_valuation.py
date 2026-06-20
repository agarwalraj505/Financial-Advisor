from datetime import datetime, timezone

import pandas as pd

from insights import generate_insights
from market_data import MarketQuote
from valuation import (calculate_category_allocation, calculate_current_value, calculate_historical_gains,
                       calculate_pl, calculate_portfolio_totals, create_valuation_snapshot,
                       calculate_position_value, valuate_holdings)


def holding(**overrides):
    row = {"instrument": "Example", "price_symbol": "TEST", "asset_type": "ETF", "category": "Core",
           "quantity": 2, "manual_current_price": 40, "currency": "EUR", "fx_rate_to_eur": 1,
           "current_value_eur": 80, "buy_in_value_eur": 70}
    row.update(overrides)
    return pd.DataFrame([row])


def test_calculating_live_value_from_quantity_and_price():
    quote = MarketQuote("TEST", latest_price=50, previous_close=48, currency="EUR")
    valued = valuate_holdings(holding(), {"TEST": quote}, {"EUR": 1})
    assert calculate_position_value(2, 50) == 100
    assert valued.loc[0, "current_value_eur"] == 100
    assert valued.loc[0, "price_source"] == "Live market data"


def test_manual_price_fallback():
    quote = MarketQuote("TEST", error="offline")
    valued = valuate_holdings(holding(), {"TEST": quote}, {"EUR": 1})
    assert valued.loc[0, "current_value_eur"] == 80
    assert valued.loc[0, "price_source"] == "Manual fallback"


def test_stale_cached_live_price_defers_to_manual_fallback():
    valued = valuate_holdings(holding(live_current_price=11, manual_current_price=9), {}, {"EUR": 1})
    assert valued.loc[0, "current_value_eur"] == 18
    assert valued.loc[0, "price_source"] == "Manual fallback"
    assert bool(valued.loc[0, "price_stale"]) is True


def test_non_eur_conversion_logic():
    quote = MarketQuote("TEST", latest_price=50, currency="USD")
    valued = valuate_holdings(holding(currency="USD"), {"TEST": quote}, {"USD": 0.8})
    assert valued.loc[0, "current_value_eur"] == 80
    assert valued.loc[0, "fx_rate_to_eur"] == 0.8


def test_gbx_pence_conversion_uses_one_hundredth_of_gbp_rate():
    quote = MarketQuote("TEST", latest_price=100, currency="GBp")
    valued = valuate_holdings(holding(currency="GBX"), {"TEST": quote}, {"GBP": 1.18})
    assert valued.loc[0, "fx_rate_to_eur"] == 0.0118
    assert valued.loc[0, "current_value_eur"] == 2.36


def test_scalable_screenshot_price_precedes_manual_fallback():
    valued = valuate_holdings(holding(current_price_eur=45, source="Scalable screenshot",
                                      user_confirmed=True, manual_current_price=40), {}, {"EUR": 1})
    assert valued.loc[0, "current_value_eur"] == 90
    assert valued.loc[0, "price_source"] == "Scalable screenshot"


def test_live_price_precedes_screenshot_and_manual_prices():
    quote = MarketQuote("TEST", latest_price=50, currency="EUR")
    valued = valuate_holdings(holding(current_price_eur=45, source="Scalable screenshot",
                                      manual_current_price=40), {"TEST": quote}, {"EUR": 1})
    assert valued.loc[0, "current_value_eur"] == 100
    assert valued.loc[0, "price_source"] == "Live market data"


def test_expired_cached_quote_falls_back_and_is_marked_stale():
    quote = MarketQuote("TEST", latest_price=50, currency="EUR", stale=True)
    valued = valuate_holdings(holding(), {"TEST": quote}, {"EUR": 1})
    assert valued.loc[0, "current_value_eur"] == 80
    assert valued.loc[0, "price_source"] == "Manual fallback"
    assert bool(valued.loc[0, "price_stale"]) is True


def test_missing_price_is_explicit_and_does_not_invent_value():
    valued = valuate_holdings(holding(manual_current_price=0, current_value_eur=0), {}, {"EUR": 1})
    assert valued.loc[0, "current_value_eur"] == 0
    assert valued.loc[0, "price_source"] == "Missing"
    assert "Price missing" in valued.loc[0, "price_error"]


def test_profit_and_loss_fields_are_recalculated_from_eur_value():
    quote = MarketQuote("TEST", latest_price=50, currency="EUR")
    valued = valuate_holdings(holding(buy_in_value_eur=80), {"TEST": quote}, {"EUR": 1})
    assert valued.loc[0, "pl_eur"] == 20
    assert valued.loc[0, "pl_percent"] == 25


def test_daily_weekly_monthly_yearly_gains():
    history = pd.DataFrame({
        "timestamp": ["2026-06-18T12:00:00+00:00", "2026-06-12T12:00:00+00:00",
                      "2026-05-20T12:00:00+00:00", "2025-06-19T12:00:00+00:00"],
        "total_value_eur": [110, 90, 80, 50]})
    gains = calculate_historical_gains(120, history, datetime(2026, 6, 19, 18, tzinfo=timezone.utc))
    assert gains["daily"] == {"eur": 10.0, "pct": 9.09}
    assert gains["weekly"]["eur"] == 30
    assert gains["monthly"]["eur"] == 40
    assert gains["yearly"]["eur"] == 70


def test_missing_history_behavior():
    gains = calculate_historical_gains(100, pd.DataFrame())
    assert all(value is None for value in gains.values())


def test_public_valuation_helpers_and_snapshot_creation():
    holdings = pd.DataFrame([{"category": "Core", "current_value_eur": 120, "buy_in_value_eur": 100},
                             {"category": "Cash", "current_value_eur": 30, "buy_in_value_eur": 30}])
    assert calculate_current_value(2, 50, .8) == 80
    assert calculate_pl(120, 100) == {"pl_eur": 20.0, "pl_percent": 20.0}
    assert calculate_category_allocation(holdings)["weight_percent"].sum() == 100
    totals = calculate_portfolio_totals(holdings)
    assert totals["total_value_eur"] == 150
    assert totals["cash_eur"] == 30
    snapshot = create_valuation_snapshot(holdings, pd.DataFrame(), datetime(2026, 6, 19, tzinfo=timezone.utc))
    assert snapshot["date"] == "2026-06-19"
    assert snapshot["daily_gain_eur"] is None


def test_insight_generation():
    rows = pd.concat([
        holding(instrument="Large Core", current_value_eur=800, daily_gain_eur=20, price_source="Live"),
        holding(instrument="Small Growth", price_symbol="", category="Growth", current_value_eur=100,
                daily_gain_eur=-10, price_source="Manual fallback"),
        holding(instrument="Cash", price_symbol="", category="Cash", current_value_eur=100,
                daily_gain_eur=0, price_source="Manual fallback")], ignore_index=True)
    drift = pd.DataFrame({"category": ["Core", "Growth"], "drift_pct_points": [30, -20]})
    text = " ".join(generate_insights(rows, drift, fee_threshold=250, cash_max_pct=2))
    assert "Largest holding: Large Core" in text
    assert "Concentration warning" in text
    assert "Largest daily loser: Small Growth" in text
    assert "Missing live price symbols: Small Growth" in text
    assert "Cash warning" in text
    assert "Small-position fee warning" in text
