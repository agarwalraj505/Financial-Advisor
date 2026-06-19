import pandas as pd

from market_data import MarketQuote
from market_research import calculate_market_metrics


def test_market_research_calculates_returns_risk_and_trend():
    index = pd.bdate_range("2025-06-01", periods=252)
    history = pd.DataFrame({"Close": [100 + i * 0.5 for i in range(252)]}, index=index)
    quote = MarketQuote("UP", latest_price=float(history.iloc[-1, 0]), previous_close=float(history.iloc[-2, 0]),
                        currency="EUR", fetched_at="2026-06-19T12:00:00+00:00", histories={"1y": history})
    metrics = calculate_market_metrics(quote)
    assert metrics["return_1d_pct"] > 0
    assert metrics["return_1y_pct"] > 0
    assert metrics["volatility_pct"] >= 0
    assert metrics["max_drawdown_pct"] == 0
    assert metrics["trend_status"] == "strong uptrend"
    assert 0 <= metrics["momentum_score"] <= 10
    assert metrics["research_confidence"] == "High"


def test_missing_history_requires_manual_review():
    metrics = calculate_market_metrics(MarketQuote("MISS", error="offline"))
    assert metrics["trend_status"] == "Manual review required"
    assert metrics["momentum_score"] == 0
    assert metrics["research_confidence"] == "Low"
