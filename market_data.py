"""Defensive yfinance adapter for estimated internet market prices."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st
import yfinance as yf

CRYPTO_IDS = {"BTC-USD": "bitcoin", "BTC-EUR": "bitcoin", "ETH-USD": "ethereum",
              "ETH-EUR": "ethereum", "SOL-USD": "solana", "SOL-EUR": "solana"}


def _secret(name: str, default="") -> str:
    try:
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


def _coingecko_id(symbol: str) -> str:
    symbol = str(symbol or "").strip()
    return symbol.split(":", 1)[1] if symbol.lower().startswith("coingecko:") else CRYPTO_IDS.get(symbol.upper(), "")


def _coingecko_json(path: str, params: dict) -> dict:
    url = "https://api.coingecko.com/api/v3/" + path + "?" + urlencode(params)
    headers = {"accept": "application/json", "user-agent": "wealth-manager/1.0"}
    api_key = _secret("COINGECKO_API_KEY")
    if api_key:
        headers["x-cg-demo-api-key"] = api_key
    with urlopen(Request(url, headers=headers), timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


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
    stale: bool = False

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
        histories = {}
        for period in ("5d", "1mo", "1y"):
            try:
                histories[period] = ticker.history(period=period, interval="1d", auto_adjust=False, timeout=8)
            except TypeError:  # Lightweight test doubles and older yfinance releases.
                histories[period] = ticker.history(period=period, interval="1d", auto_adjust=False)
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


@st.cache_data(ttl=900, show_spinner=False)
def get_latest_price(symbol: str) -> float | None:
    """Return yfinance first; CoinGecko is a no-key crypto fallback."""
    symbol = str(symbol or "").strip()
    if not symbol:
        return None
    yahoo_symbol = symbol if not symbol.lower().startswith("coingecko:") else ""
    if yahoo_symbol:
        try:
            ticker = yf.Ticker(yahoo_symbol)
            price = _fast_info_value(ticker.fast_info, "last_price")
            if price: return float(price)
            history = ticker.history(period="5d", interval="1d", auto_adjust=False, timeout=8)
            price = _last_close(history)
            if price: return price
        except Exception:
            pass
    coin_id = _coingecko_id(symbol)
    if coin_id:
        try:
            data = _coingecko_json("simple/price", {"ids": coin_id, "vs_currencies": "eur"})
            price = data.get(coin_id, {}).get("eur")
            if price: return float(price)
        except Exception:
            pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Return yfinance history first, then CoinGecko for supported crypto."""
    symbol = str(symbol or "").strip()
    if not symbol:
        return pd.DataFrame()
    explicit_coingecko = symbol.lower().startswith("coingecko:")
    yahoo_symbol = "" if explicit_coingecko else symbol
    if yahoo_symbol:
        try:
            history = yf.Ticker(yahoo_symbol).history(period=period, interval="1d", auto_adjust=False, timeout=8)
            if history is not None and not history.empty: return history
        except Exception:
            pass
    coin_id = _coingecko_id(symbol)
    if coin_id:
        try:
            days = {"5d": 5, "1mo": 30, "1y": 365}.get(period, 365)
            data = _coingecko_json(f"coins/{coin_id}/market_chart", {"vs_currency": "eur", "days": days,
                                                                       "interval": "daily"})
            prices = data.get("prices", [])
            if prices:
                index = pd.to_datetime([item[0] for item in prices], unit="ms", utc=True)
                return pd.DataFrame({"Close": [float(item[1]) for item in prices]}, index=index)
        except Exception:
            pass
    return pd.DataFrame()


def get_returns(symbol: str) -> dict[str, float | None]:
    history = get_price_history(symbol, "1y")
    if history.empty or "Close" not in history:
        return {key: None for key in ("1d", "1w", "1m", "1y", "ytd")}
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()

    def period_return(periods: int):
        return None if len(close) <= periods else round((close.iloc[-1] / close.iloc[-periods - 1] - 1) * 100, 2)

    ytd = close[pd.to_datetime(close.index).year == pd.to_datetime(close.index[-1]).year]
    return {"1d": period_return(1), "1w": period_return(5), "1m": period_return(21),
            "1y": period_return(len(close) - 1),
            "ytd": round((close.iloc[-1] / ytd.iloc[0] - 1) * 100, 2) if not ytd.empty else None}


@st.cache_data(ttl=43200, show_spinner=False)
def get_fx_rate_to_eur(currency: str) -> float | None:
    rate, _ = fetch_fx_rate_to_eur(currency)
    return rate


@st.cache_data(ttl=43200, show_spinner=False)
def get_quote_currency(symbol: str) -> str:
    if str(symbol).lower().startswith("coingecko:"):
        return "EUR"
    try:
        return normalise_currency(_fast_info_value(yf.Ticker(symbol).fast_info, "currency")) or "EUR"
    except Exception:
        return "EUR"


def enrich_holding_with_market_data(row: dict) -> dict:
    enriched = dict(row)
    symbol = str(enriched.get("resolved_price_symbol") or enriched.get("price_symbol") or "")
    live_price = get_latest_price(symbol) if symbol else None
    screenshot_price = float(enriched.get("current_price_eur", 0) or 0)
    screenshot_evidence = bool(enriched.get("screenshot_path") or enriched.get("screenshot_captured_at") or
                               str(enriched.get("source", "")).lower().startswith("scalable") or
                               enriched.get("user_confirmed"))
    manual_price = float(enriched.get("manual_current_price", 0) or 0)
    currency = "EUR" if _coingecko_id(symbol) and live_price else str(enriched.get("currency", "EUR") or "EUR")
    fx = get_fx_rate_to_eur(currency)
    if fx is None: fx = float(enriched.get("fx_rate_to_eur", 0) or 0)
    if live_price:
        selected, source = live_price, "Live market data"
    elif screenshot_price and screenshot_evidence:
        selected, source, currency, fx = screenshot_price, "Scalable screenshot", "EUR", 1.0
    elif manual_price:
        selected, source = manual_price, "Manual fallback"
    else:
        selected, source = 0.0, "Missing"
    quantity = float(enriched.get("quantity", 0) or 0)
    current_value = quantity * selected * fx if fx else 0.0
    buy_in = float(enriched.get("buy_in_value_eur", 0) or 0)
    enriched.update({"live_current_price": float(live_price or 0), "selected_price": float(selected), "price_source": source,
                     "currency": currency, "fx_rate_to_eur": fx, "current_value_eur": round(current_value, 2),
                     "pl_eur": round(current_value - buy_in, 2),
                     "pl_pct": round((current_value - buy_in) / buy_in * 100, 2) if buy_in else 0})
    return enriched


def enrich_candidate_with_market_data(row: dict) -> dict:
    enriched = dict(row)
    symbol = str(enriched.get("resolved_price_symbol") or enriched.get("price_symbol") or "")
    price = get_latest_price(symbol) if symbol else None
    enriched.update({"latest_price": price, "data_source": "CoinGecko" if price and _coingecko_id(symbol)
                     else "Yahoo Finance" if price else enriched.get("data_source") or "Manual review required",
                     "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds") if price else enriched.get("last_updated", "")})
    return enriched


def get_market_quote(symbol: str) -> MarketQuote:
    """Build the common quote object using provider priority and graceful fallback."""
    quote = fetch_market_quote(symbol)
    if quote.is_available:
        return quote
    price = get_latest_price(symbol)
    histories = {period: get_price_history(symbol, period) for period in ("5d", "1mo", "1y")}
    five_day = histories["5d"]
    closes = (pd.to_numeric(five_day["Close"], errors="coerce").dropna()
              if not five_day.empty and "Close" in five_day else pd.Series(dtype=float))
    previous = float(closes.iloc[-2]) if len(closes) >= 2 else None
    return MarketQuote(symbol=symbol, latest_price=price, previous_close=previous,
                       currency=get_quote_currency(symbol),
                       fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds") if price else "",
                       histories=histories, error="" if price else quote.error or "Live price unavailable")
