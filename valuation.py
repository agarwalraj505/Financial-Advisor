"""Pure valuation and historical gain calculations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from market_data import MarketQuote


def calculate_position_value(quantity: float, price: float, fx_rate_to_eur: float = 1.0) -> float:
    return round(float(quantity) * float(price) * float(fx_rate_to_eur), 2)


def valuate_holdings(
    holdings: pd.DataFrame,
    quotes: dict[str, MarketQuote] | None = None,
    fx_rates: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Apply live quotes where possible and reliably fall back to manual prices."""
    quotes, fx_rates = quotes or {}, fx_rates or {}
    frame = holdings.copy()
    rows = []
    for _, holding in frame.iterrows():
        row = holding.to_dict()
        symbol = str(row.get("price_symbol", "") or "").strip()
        manual = float(row.get("manual_current_price", 0) or 0)
        quantity = float(row.get("quantity", 0) or 0)
        quote = quotes.get(symbol)
        live = float(quote.latest_price) if quote and quote.is_available else 0.0
        currency = (quote.currency if quote and quote.currency else str(row.get("currency", "") or "EUR")).upper()
        fx_rate = float(fx_rates.get(currency, row.get("fx_rate_to_eur", 1) or 1))
        if live > 0:
            price, source = live, "Live"
        elif manual > 0:
            price, source = manual, "Manual fallback"
            # Manual prices are entered in the row's stated currency.
        else:
            price, source = 0.0, "Missing"
        value = calculate_position_value(quantity, price, fx_rate)
        buy_in = float(row.get("buy_in_value_eur", 0) or 0)
        profit = value - buy_in
        previous = float(quote.previous_close) if quote and quote.previous_close else 0.0
        daily_gain = calculate_position_value(quantity, price - previous, fx_rate) if previous else 0.0
        row.update({"live_current_price": live, "price_source": source, "currency": currency,
                    "fx_rate_to_eur": fx_rate, "current_value_eur": value,
                    "pl_eur": round(profit, 2), "pl_pct": round(profit / buy_in * 100, 2) if buy_in else 0.0,
                    "previous_close": previous, "daily_gain_eur": daily_gain,
                    "daily_gain_pct": round((price / previous - 1) * 100, 2) if previous else 0.0,
                    "price_error": quote.error if quote else ("Missing price symbol" if not symbol else "Live price unavailable")})
        rows.append(row)
    return pd.DataFrame(rows)


def portfolio_market_history(holdings: pd.DataFrame, quotes: dict[str, MarketQuote]) -> pd.DataFrame:
    """Approximate 1-year portfolio value using current quantities and historical closes."""
    series = []
    cash = 0.0
    for _, row in holdings.iterrows():
        if str(row.get("category", "")) == "Cash":
            cash += float(row.get("current_value_eur", 0) or 0)
            continue
        symbol = str(row.get("price_symbol", "") or "")
        quote = quotes.get(symbol)
        history = quote.histories.get("1y") if quote else None
        if history is None or history.empty or "Close" not in history:
            continue
        close = pd.to_numeric(history["Close"], errors="coerce").dropna()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        value = close * float(row.get("quantity", 0) or 0) * float(row.get("fx_rate_to_eur", 1) or 1)
        series.append(value.rename(symbol or str(row.get("instrument", "Holding"))))
    if not series:
        return pd.DataFrame(columns=["date", "portfolio_value_eur", "daily_gain_eur"])
    combined = pd.concat(series, axis=1).ffill().dropna(how="all")
    total = combined.sum(axis=1) + cash
    return pd.DataFrame({"date": total.index, "portfolio_value_eur": total.values,
                         "daily_gain_eur": total.diff().fillna(0).values})


def calculate_historical_gains(
    current_value: float, history: pd.DataFrame, as_of: datetime | None = None
) -> dict[str, dict[str, float] | None]:
    """Compare against the previous snapshot and snapshots closest to 7/30/365 days ago."""
    as_of = as_of or datetime.now(timezone.utc)
    result: dict[str, dict[str, float] | None] = {key: None for key in ("daily", "weekly", "monthly", "yearly")}
    if history is None or history.empty:
        return result
    frame = history.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["total_value_eur"] = pd.to_numeric(frame["total_value_eur"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "total_value_eur"])
    # Snapshots are daily closes; today's saved row is not its own comparison base.
    prior = frame[frame["timestamp"].dt.date < as_of.date()]
    if prior.empty:
        return result

    def gain_from(base: float) -> dict[str, float]:
        gain = float(current_value) - float(base)
        return {"eur": round(gain, 2), "pct": round(gain / base * 100, 2) if base else 0.0}

    result["daily"] = gain_from(float(prior.sort_values("timestamp").iloc[-1]["total_value_eur"]))
    for label, days in (("weekly", 7), ("monthly", 30), ("yearly", 365)):
        target = pd.Timestamp(as_of - timedelta(days=days))
        closest_index = (prior["timestamp"] - target).abs().idxmin()
        result[label] = gain_from(float(prior.loc[closest_index, "total_value_eur"]))
    return result
