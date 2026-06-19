"""Market metrics derived only from supplied price history."""

from __future__ import annotations

from math import sqrt

import pandas as pd

from market_data import MarketQuote


RESEARCH_COLUMNS = ["price_symbol", "latest_price", "return_1d_pct", "return_1w_pct",
                    "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct",
                    "return_ytd_pct", "volatility_pct", "max_drawdown_pct",
                    "price_vs_50d_ma_pct", "price_vs_200d_ma_pct", "trend_status",
                    "momentum_score", "data_source", "last_updated", "research_confidence"]


def _return(close: pd.Series, periods: int | None = None, base_value: float | None = None) -> float | None:
    if close.empty:
        return None
    base = base_value if base_value is not None else (float(close.iloc[-periods - 1]) if periods and len(close) > periods else None)
    return None if not base else round((float(close.iloc[-1]) / base - 1) * 100, 2)


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def momentum_score(metrics: dict) -> float:
    """Transparent 0–10 score from multiple horizons, moving averages, and volatility."""
    scales = {"return_1w_pct": 5, "return_1m_pct": 10, "return_3m_pct": 20,
              "return_6m_pct": 30, "return_1y_pct": 40}
    weights = {"return_1w_pct": .10, "return_1m_pct": .20, "return_3m_pct": .25,
               "return_6m_pct": .20, "return_1y_pct": .15}
    score, used = 0.0, 0.0
    for key, weight in weights.items():
        value = metrics.get(key)
        if value is not None:
            score += _clamp(5 + float(value) / scales[key] * 5) * weight
            used += weight
    ma50, ma200 = metrics.get("price_vs_50d_ma_pct"), metrics.get("price_vs_200d_ma_pct")
    if ma50 is not None and ma200 is not None:
        score += _clamp(5 + (float(ma50) + float(ma200)) / 8) * .10
        used += .10
    if used == 0:
        return 0.0
    score = score / used
    volatility = metrics.get("volatility_pct")
    if volatility is not None and float(volatility) > 35:
        score -= min(2.0, (float(volatility) - 35) / 20)
    return round(_clamp(score), 2)


def calculate_market_metrics(quote: MarketQuote) -> dict:
    history = quote.histories.get("1y") if quote else None
    base = {column: None for column in RESEARCH_COLUMNS}
    base.update({"price_symbol": quote.symbol if quote else "", "latest_price": quote.latest_price if quote else None,
                 "data_source": "Yahoo Finance via yfinance" if quote and quote.is_available else "Manual review required",
                 "last_updated": quote.fetched_at if quote else "", "research_confidence": "Low"})
    if history is None or history.empty or "Close" not in history:
        base["trend_status"], base["momentum_score"] = "Manual review required", 0.0
        return base
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    if close.empty:
        base["trend_status"], base["momentum_score"] = "Manual review required", 0.0
        return base
    close.index = pd.to_datetime(close.index).tz_localize(None)
    latest = float(close.iloc[-1])
    returns = {"return_1d_pct": _return(close, 1), "return_1w_pct": _return(close, 5),
               "return_1m_pct": _return(close, 21), "return_3m_pct": _return(close, 63),
               "return_6m_pct": _return(close, 126), "return_1y_pct": _return(close, len(close) - 1)}
    ytd_rows = close[close.index >= pd.Timestamp(close.index[-1].year, 1, 1)]
    returns["return_ytd_pct"] = _return(close, base_value=float(ytd_rows.iloc[0])) if not ytd_rows.empty else None
    daily = close.pct_change().dropna()
    volatility = float(daily.std() * sqrt(252) * 100) if not daily.empty else None
    drawdown = close / close.cummax() - 1
    ma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    ma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
    vs50 = (latest / ma50 - 1) * 100 if ma50 else None
    vs200 = (latest / ma200 - 1) * 100 if ma200 else None
    if ma50 and ma200 and latest > ma50 > ma200 and (returns["return_3m_pct"] or 0) > 5:
        trend = "strong uptrend"
    elif ma50 and ma200 and latest > ma50 and latest > ma200:
        trend = "uptrend"
    elif ma50 and ma200 and latest < ma50 < ma200 and float(drawdown.min()) * 100 < -20:
        trend = "high-risk falling trend"
    elif ma50 and ma200 and latest < ma50 and latest < ma200:
        trend = "downtrend"
    else:
        trend = "neutral"
    base.update(returns)
    base.update({"latest_price": latest, "volatility_pct": round(volatility, 2) if volatility is not None else None,
                 "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
                 "price_vs_50d_ma_pct": round(vs50, 2) if vs50 is not None else None,
                 "price_vs_200d_ma_pct": round(vs200, 2) if vs200 is not None else None,
                 "trend_status": trend, "research_confidence": "High" if len(close) >= 200 else "Medium"})
    base["momentum_score"] = momentum_score(base)
    return base


def build_market_research(quotes: dict[str, MarketQuote]) -> pd.DataFrame:
    return pd.DataFrame([calculate_market_metrics(quote) for quote in quotes.values()], columns=RESEARCH_COLUMNS)
