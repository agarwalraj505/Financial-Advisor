"""Compatibility API backed exclusively by :mod:`market_data_engine`.

Provider calls belong in ``providers/*`` and waterfall decisions belong in
``MarketDataEngine``. This module keeps the app's stable public types/helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from market_data_engine import MarketDataEngine


def normalise_currency(currency: str) -> str:
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
    stale: bool = False
    provider: str = ""
    confidence: str = ""
    provider_symbol: str = ""

    @property
    def is_available(self) -> bool:
        return self.latest_price is not None and float(self.latest_price) > 0


def _engine() -> MarketDataEngine:
    return MarketDataEngine(scraping_enabled=False)


def _quote_from_payload(payload: dict) -> MarketQuote:
    return MarketQuote(symbol=str(payload.get("symbol", "")), latest_price=payload.get("latest_price"),
                       previous_close=payload.get("previous_close"),
                       currency=normalise_currency(payload.get("currency", "")),
                       fetched_at=str(payload.get("fetched_at", "")),
                       histories=payload.get("histories") or {}, error=str(payload.get("error", "")),
                       provider=str(payload.get("provider", "")), confidence=str(payload.get("confidence", "")),
                       provider_symbol=str(payload.get("provider_symbol", "")))


def fetch_market_quote(symbol: str, alpha_vantage_symbol: str = "",
                       alpha_vantage_currency: str = "") -> MarketQuote:
    engine = _engine()
    payload = (engine.quick_quote(symbol, alpha_vantage_symbol, alpha_vantage_currency)
               if alpha_vantage_symbol else engine.quick_quote(symbol))
    return _quote_from_payload(payload)


def get_market_quote(symbol: str, alpha_vantage_symbol: str = "",
                     alpha_vantage_currency: str = "") -> MarketQuote:
    return fetch_market_quote(symbol, alpha_vantage_symbol, alpha_vantage_currency)


def fetch_fx_rate_to_eur(currency: str) -> tuple[float | None, str]:
    result = _engine().fx_rate_to_eur(normalise_currency(currency))
    return (float(result.data["fx_rate_to_eur"]), "") if result.success else (None, result.error)


def fx_symbol_for_currency(currency: str) -> str:
    currency = normalise_currency(currency)
    if currency in {"", "EUR"}: return ""
    return f"EUR{'GBP' if currency == 'GBX' else currency}=X"


@st.cache_data(ttl=900, show_spinner=False)
def get_latest_price(symbol: str) -> float | None:
    return get_market_quote(symbol).latest_price


@st.cache_data(ttl=3600, show_spinner=False)
def get_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    history = get_market_quote(symbol).histories.get(period)
    return history if isinstance(history, pd.DataFrame) else pd.DataFrame()


def get_returns(symbol: str) -> dict[str, float | None]:
    history = get_price_history(symbol, "1y")
    if history.empty or "Close" not in history:
        return {key: None for key in ("1d", "1w", "1m", "1y", "ytd")}
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    def period_return(periods: int):
        return None if len(close) <= periods else round((close.iloc[-1] / close.iloc[-periods - 1] - 1) * 100, 2)
    index = pd.to_datetime(close.index, errors="coerce")
    ytd = close[index.year == index[-1].year] if len(index) else pd.Series(dtype=float)
    return {"1d": period_return(1), "1w": period_return(5), "1m": period_return(21),
            "1y": period_return(len(close) - 1),
            "ytd": round((close.iloc[-1] / ytd.iloc[0] - 1) * 100, 2) if not ytd.empty else None}


@st.cache_data(ttl=43200, show_spinner=False)
def get_fx_rate_to_eur(currency: str) -> float | None:
    return fetch_fx_rate_to_eur(currency)[0]


@st.cache_data(ttl=43200, show_spinner=False)
def get_quote_currency(symbol: str) -> str:
    return get_market_quote(symbol).currency


def enrich_holding_with_market_data(row: dict) -> dict:
    enriched = _engine().enrich_asset(dict(row), is_candidate=False, force_web=False)
    from valuation import valuate_holdings
    return valuate_holdings(pd.DataFrame([enriched])).iloc[0].to_dict()


def enrich_candidate_with_market_data(row: dict) -> dict:
    return _engine().enrich_asset(dict(row), is_candidate=True, force_web=False)


def openfigi_mapping_payload(identifier: str, id_type: str = "ID_ISIN") -> list[dict[str, str]]:
    return [{"idType": id_type, "idValue": str(identifier).strip()}]


def quote_timestamp() -> str:
    """Compatibility helper for callers creating manual quote records."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
