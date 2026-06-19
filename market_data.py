"""Defensive yfinance adapter for estimated internet market prices."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf


@dataclass
class MarketQuote:
    symbol: str
    latest_price: float | None = None
    previous_close: float | None = None
    currency: str = ""
    fetched_at: str = ""
    histories: dict[str, pd.DataFrame] = field(default_factory=dict)
    error: str = ""

    @property
    def is_available(self) -> bool:
        return self.latest_price is not None and self.latest_price > 0


def _last_close(history: pd.DataFrame) -> float | None:
    if history is None or history.empty or "Close" not in history:
        return None
    values = pd.to_numeric(history["Close"], errors="coerce").dropna()
    return None if values.empty else float(values.iloc[-1])


def _fast_info_value(fast_info: Any, name: str):
    try:
        return fast_info.get(name) if hasattr(fast_info, "get") else getattr(fast_info, name)
    except (AttributeError, KeyError, TypeError):
        return None


def fetch_market_quote(symbol: str) -> MarketQuote:
    """Fetch quote metadata and 5d/1mo/1y histories; return an error instead of raising."""
    symbol = str(symbol or "").strip()
    quote = MarketQuote(symbol=symbol)
    if not symbol:
        quote.error = "Missing price symbol"
        return quote
    try:
        ticker = yf.Ticker(symbol)
        histories = {
            period: ticker.history(period=period, interval="1d", auto_adjust=False)
            for period in ("5d", "1mo", "1y")
        }
        quote.histories = histories
        fast_info = ticker.fast_info
        quote.latest_price = _fast_info_value(fast_info, "last_price") or _last_close(histories["5d"])
        quote.previous_close = _fast_info_value(fast_info, "previous_close")
        quote.currency = str(_fast_info_value(fast_info, "currency") or "").upper()
        if quote.previous_close is None:
            closes = pd.to_numeric(histories["5d"].get("Close"), errors="coerce").dropna()
            if len(closes) >= 2:
                quote.previous_close = float(closes.iloc[-2])
        quote.fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not quote.is_available:
            quote.error = "No usable latest price returned"
    except Exception as exc:  # yfinance/network errors vary by backend and version
        quote.error = str(exc) or type(exc).__name__
    return quote


def fx_symbol_for_currency(currency: str) -> str:
    currency = str(currency or "").upper()
    if currency in {"EUR", ""}:
        return ""
    if currency == "GBP":
        return "EURGBP=X"
    if currency == "GBPENCE" or currency == "GBX":
        return "EURGBP=X"
    return f"EUR{currency}=X"


def fetch_fx_rate_to_eur(currency: str) -> tuple[float | None, str]:
    """Return EUR per unit of quote currency using Yahoo's foreign-units-per-EUR pair."""
    currency = str(currency or "").upper()
    if currency == "EUR":
        return 1.0, ""
    symbol = fx_symbol_for_currency(currency)
    if not symbol:
        return None, "Missing currency"
    quote = fetch_market_quote(symbol)
    if not quote.is_available:
        return None, quote.error or "FX price unavailable"
    rate = 1.0 / float(quote.latest_price)
    if currency in {"GBX", "GBPENCE"}:
        rate /= 100.0
    return rate, ""
