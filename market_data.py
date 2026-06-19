"""Defensive yfinance adapter for estimated internet market prices."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf


class MarketDataAdapter:
    """Small provider contract so paid APIs can be added without changing scoring."""

    name = "Base adapter"

    def fetch(self, symbol: str) -> "MarketQuote":
        raise NotImplementedError


def normalise_currency(currency: str) -> str:
    """Preserve Yahoo's GBp (pence) distinction instead of treating it as GBP."""
    raw = str(currency or "").strip()
    if raw == "GBp" or raw.upper() in {"GBX", "GBPENCE"}:
        return "GBX"
    return raw.upper()


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
        quote.currency = normalise_currency(_fast_info_value(fast_info, "currency"))
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
    currency = normalise_currency(currency)
    if currency in {"EUR", ""}:
        return ""
    if currency == "GBP":
        return "EURGBP=X"
    if currency == "GBPENCE" or currency == "GBX":
        return "EURGBP=X"
    return f"EUR{currency}=X"


def fetch_fx_rate_to_eur(currency: str) -> tuple[float | None, str]:
    """Return EUR per unit of quote currency using Yahoo's foreign-units-per-EUR pair."""
    currency = normalise_currency(currency)
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


class YFinanceAdapter(MarketDataAdapter):
    name = "Yahoo Finance via yfinance"

    def fetch(self, symbol: str) -> MarketQuote:
        return fetch_market_quote(symbol)


class ManualFallbackAdapter(MarketDataAdapter):
    name = "Manual fallback"

    def __init__(self, prices: dict[str, float], currency: str = "EUR"):
        self.prices, self.currency = prices, currency

    def fetch(self, symbol: str) -> MarketQuote:
        price = self.prices.get(symbol)
        return MarketQuote(symbol=symbol, latest_price=price, currency=self.currency,
                           error="Manual price unavailable" if not price else "")


class PaidMarketDataAdapter(MarketDataAdapter):
    """Extension point. Deliberately has no provider or network implementation."""

    name = "Paid provider (not configured)"

    def fetch(self, symbol: str) -> MarketQuote:
        return MarketQuote(symbol=symbol, error="Paid market-data adapter is not configured")


def openfigi_mapping_payload(identifier: str, id_type: str = "ID_ISIN") -> list[dict[str, str]]:
    """Build an optional OpenFIGI request payload without transmitting personal data."""
    return [{"idType": id_type, "idValue": str(identifier).strip()}]
