"""Pure valuation and historical gain calculations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from data_cache import is_stale
from market_data import MarketQuote, normalise_currency

PRICE_SOURCE_LIVE = "Live market data"
PRICE_SOURCE_SCREENSHOT = "Scalable screenshot"
PRICE_SOURCE_MANUAL = "Manual fallback"
PRICE_SOURCE_MISSING = "Missing"


def calculate_position_value(quantity: float, price: float, fx_rate_to_eur: float = 1.0) -> float:
    return round(float(quantity) * float(price) * float(fx_rate_to_eur), 2)


def calculate_current_value(quantity: float, price: float, fx_rate_to_eur: float = 1.0) -> float:
    """Public beginner-friendly alias used by the web app contract."""
    return calculate_position_value(quantity, price, fx_rate_to_eur)


def calculate_pl(current_value: float, buy_in_value: float) -> dict[str, float]:
    profit = float(current_value) - float(buy_in_value)
    percent = profit / float(buy_in_value) * 100 if buy_in_value else 0.0
    return {"pl_eur": round(profit, 2), "pl_percent": round(percent, 2)}


def _number(value, default=0.0) -> float:
    try:
        return default if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return default


def select_position_price(row: dict, quote: MarketQuote | None = None) -> tuple[float, str, bool]:
    """Choose one explainable price without mutating entered screenshot values."""
    stale_live_available = bool(quote and quote.is_available and quote.stale)
    if quote and quote.is_available and not quote.stale:
        return float(quote.latest_price), PRICE_SOURCE_LIVE, False
    cached_live = _number(row.get("live_current_price"))
    cached_stale = cached_live > 0 and is_stale(row.get("last_updated"), "price")
    stale_live_available = stale_live_available or cached_stale
    if cached_live > 0 and not cached_stale:
        return cached_live, PRICE_SOURCE_LIVE, False
    screenshot = _number(row.get("current_price_eur"))
    screenshot_evidence = any((row.get("screenshot_path"), row.get("screenshot_captured_at"),
                               str(row.get("source", "")).lower().startswith("scalable"),
                               bool(row.get("user_confirmed", False))))
    if screenshot > 0 and screenshot_evidence:
        return screenshot, PRICE_SOURCE_SCREENSHOT, stale_live_available
    manual = _number(row.get("manual_current_price"))
    if manual > 0:
        return manual, PRICE_SOURCE_MANUAL, stale_live_available
    return 0.0, PRICE_SOURCE_MISSING, stale_live_available


def resolve_position_fx(currency: str, row: dict, fx_rates: dict[str, float]) -> tuple[float, str]:
    """Return EUR per quote unit; GBX/GBp is converted from pence, not pounds."""
    normalized = normalise_currency(currency)
    if normalized == "EUR":
        return 1.0, "EUR"
    direct = _number(fx_rates.get(normalized))
    if direct > 0:
        return direct, "ECB/yfinance FX"
    if normalized == "GBX":
        gbp = _number(fx_rates.get("GBP"))
        if gbp > 0:
            return gbp / 100.0, "ECB/yfinance FX (GBP pence conversion)"
    row_currency = normalise_currency(row.get("currency", ""))
    stored = _number(row.get("fx_rate_to_eur"))
    if stored > 0 and row_currency == normalized:
        return stored, "Cached/manual FX"
    return 0.0, "Missing FX"


def calculate_category_allocation(holdings: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty:
        return pd.DataFrame(columns=["category", "current_value_eur", "weight_percent"])
    frame = holdings.copy()
    if "current_value_eur" not in frame:
        frame["current_value_eur"] = 0.0
    frame["current_value_eur"] = pd.to_numeric(frame["current_value_eur"], errors="coerce").fillna(0)
    if "category" not in frame:
        frame["category"] = "Uncategorised"
    total = float(frame["current_value_eur"].sum())
    grouped = frame.groupby("category", as_index=False)["current_value_eur"].sum()
    grouped["weight_percent"] = grouped["current_value_eur"] / total * 100 if total else 0.0
    return grouped.round(2)


def calculate_portfolio_totals(holdings: pd.DataFrame) -> dict[str, float]:
    if holdings.empty:
        return {"total_value_eur": 0.0, "invested_value_eur": 0.0,
                "unrealized_pl_eur": 0.0, "unrealized_pl_percent": 0.0, "cash_eur": 0.0}
    current = pd.to_numeric(holdings["current_value_eur"], errors="coerce").fillna(0) if "current_value_eur" in holdings else pd.Series(0.0, index=holdings.index)
    invested = pd.to_numeric(holdings["buy_in_value_eur"], errors="coerce").fillna(0) if "buy_in_value_eur" in holdings else pd.Series(0.0, index=holdings.index)
    total, buy_in = float(current.sum()), float(invested.sum())
    profit = total - buy_in
    categories = holdings.get("category", pd.Series(index=holdings.index, dtype=str)).astype(str)
    cash = float(current[categories == "Cash"].sum())
    return {"total_value_eur": round(total, 2), "invested_value_eur": round(buy_in, 2),
            "unrealized_pl_eur": round(profit, 2),
            "unrealized_pl_percent": round(profit / buy_in * 100, 2) if buy_in else 0.0,
            "cash_eur": round(cash, 2)}


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
        symbol = str(row.get("resolved_price_symbol") or row.get("price_symbol") or "").strip()
        quantity = _number(row.get("quantity"))
        quote = quotes.get(symbol)
        currency = normalise_currency(quote.currency if quote and quote.currency else row.get("currency", "") or "EUR")
        price, source, stale = select_position_price(row, quote)
        if source == PRICE_SOURCE_SCREENSHOT:
            currency = "EUR"  # current_price_eur is explicitly denominated in euros.
        fx_rate, fx_source = resolve_position_fx(currency, row, fx_rates)
        value = calculate_position_value(quantity, price, fx_rate) if price > 0 and fx_rate > 0 else 0.0
        buy_in = _number(row.get("buy_in_value_eur"))
        pl = calculate_pl(value, buy_in)
        previous = (float(quote.previous_close) if quote and quote.previous_close
                    else _number(row.get("previous_close")))
        daily_gain = calculate_position_value(quantity, price - previous, fx_rate) if previous else 0.0
        live = float(quote.latest_price) if quote and quote.is_available else _number(row.get("live_current_price"))
        errors = []
        if price <= 0: errors.append("Price missing after live, screenshot, and manual fallbacks")
        if fx_rate <= 0: errors.append(f"FX rate to EUR missing for {currency}")
        if quote and quote.error and not quote.is_available: errors.append(quote.error)
        row.update({"live_current_price": live, "selected_price": price, "price_source": source,
                    "price_stale": stale, "currency": currency,
                    "fx_rate_to_eur": fx_rate, "current_value_eur": value,
                    "fx_source": fx_source, "pl_eur": pl["pl_eur"],
                    "pl_pct": pl["pl_percent"], "pl_percent": pl["pl_percent"],
                    "previous_close": previous, "daily_gain_eur": daily_gain,
                    "daily_gain_pct": round((price / previous - 1) * 100, 2) if previous else 0.0,
                    "daily_gain_percent": round((price / previous - 1) * 100, 2) if previous else 0.0,
                    "price_error": "; ".join(dict.fromkeys(errors))})
        rows.append(row)
    return pd.DataFrame(rows)


def portfolio_market_history(holdings: pd.DataFrame, quotes: dict[str, MarketQuote]) -> pd.DataFrame:
    """Approximate 1-year portfolio value using current quantities and historical closes."""
    series = []
    static_value = 0.0
    for _, row in holdings.iterrows():
        if str(row.get("category", "")) == "Cash":
            static_value += float(row.get("current_value_eur", 0) or 0)
            continue
        symbol = str(row.get("resolved_price_symbol") or row.get("price_symbol") or "")
        quote = quotes.get(symbol)
        history = quote.histories.get("1y") if quote else None
        if history is None or history.empty or "Close" not in history:
            static_value += float(row.get("current_value_eur", 0) or 0)
            continue
        close = pd.to_numeric(history["Close"], errors="coerce").dropna()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        value = close * float(row.get("quantity", 0) or 0) * float(row.get("fx_rate_to_eur", 1) or 1)
        series.append(value.rename(symbol or str(row.get("instrument", "Holding"))))
    if not series:
        return pd.DataFrame(columns=["date", "portfolio_value_eur", "daily_gain_eur"])
    combined = pd.concat(series, axis=1).ffill().dropna(how="all")
    total = combined.sum(axis=1) + static_value
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


def calculate_snapshot_gains(current_value: float, historical_snapshots: pd.DataFrame,
                             as_of: datetime | None = None):
    return calculate_historical_gains(current_value, historical_snapshots, as_of)


def create_valuation_snapshot(holdings: pd.DataFrame, historical_snapshots: pd.DataFrame,
                              as_of: datetime | None = None) -> dict:
    as_of = as_of or datetime.now(timezone.utc)
    totals = calculate_portfolio_totals(holdings)
    gains = calculate_snapshot_gains(totals["total_value_eur"], historical_snapshots, as_of)
    snapshot = {"date": as_of.date().isoformat(), "timestamp": as_of.isoformat(timespec="seconds"), **totals}
    for period in ("daily", "weekly", "monthly", "yearly"):
        snapshot[f"{period}_gain_eur"] = gains[period]["eur"] if gains[period] else None
        snapshot[f"{period}_gain_pct"] = gains[period]["pct"] if gains[period] else None
    return snapshot
