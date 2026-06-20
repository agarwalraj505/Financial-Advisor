"""Optional Alpha Vantage adapter for quotes, search, history, ETF data, and FX."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import pandas as pd
import requests

from providers.base import BaseProvider, ProviderResult


BASE_URL = "https://www.alphavantage.co/query"


def _number(value: Any) -> float | None:
    if value in (None, "", "None", "-"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _percentage(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if "%" in str(value):
        return number
    return number * 100 if abs(number) <= 1 else number


def _currency_hint(symbol: str) -> str:
    upper = str(symbol or "").upper()
    if upper.endswith((".DEX", ".FRA", ".AMS", ".MIL", ".PAR")):
        return "EUR"
    if upper.endswith(".LON"):
        return "GBX"
    if "." not in upper and upper:
        return "USD"
    return ""


class AlphaVantageProvider(BaseProvider):
    name = "Alpha Vantage"
    purpose = "Quotes, symbol search, daily history, ETF profile"
    key_name = "ALPHA_VANTAGE_API_KEY"
    key_required = True
    _cache: dict[tuple, tuple[datetime, dict]] = {}
    _cache_lock = Lock()
    _global_paused_until: datetime | None = None
    _ttl_seconds = {"GLOBAL_QUOTE": 15 * 60, "TIME_SERIES_DAILY": 12 * 60 * 60,
                    "ETF_PROFILE": 7 * 24 * 60 * 60, "CURRENCY_EXCHANGE_RATE": 12 * 60 * 60,
                    "DIGITAL_CURRENCY_DAILY": 12 * 60 * 60, "SYMBOL_SEARCH": 7 * 24 * 60 * 60}

    def __init__(self, session=None, timeout: int = 8):
        super().__init__()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.paused_until: datetime | None = None

    def is_enabled(self) -> bool:
        return self.enabled

    def status_row(self, key_label: str = "Yes") -> dict:
        return super().status_row(key_label)

    def _request(self, params: dict[str, Any]) -> ProviderResult:
        """Run one API request without exposing the API key in results or errors."""
        if not self.enabled:
            return self.failure("Alpha Vantage disabled: API key not configured")
        now = datetime.now(timezone.utc)
        paused_until = max(filter(None, [self.paused_until, self._global_paused_until]), default=None)
        if paused_until and now < paused_until:
            return self.failure("Alpha Vantage temporarily paused after a rate-limit response", 429)
        function = str(params.get("function", ""))
        cache_key = tuple(sorted((str(key), str(value)) for key, value in params.items()))
        ttl = self._ttl_seconds.get(function, 0)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached and ttl and (now - cached[0]).total_seconds() < ttl:
            return self.success({"raw": cached[1]}, "High")
        try:
            response = self.session.get(
                BASE_URL,
                params={**params, "apikey": self.api_key},
                timeout=self.timeout,
            )
            status_code = int(getattr(response, "status_code", 200))
            if status_code >= 400:
                return self.failure(f"Alpha Vantage HTTP {status_code}", status_code)
            try:
                payload = response.json()
            except (TypeError, ValueError):
                return self.failure("Alpha Vantage returned invalid JSON", status_code)
        except requests.Timeout:
            return self.failure("Alpha Vantage network timeout")
        except requests.RequestException as exc:
            return self.failure(f"Alpha Vantage network error: {type(exc).__name__}")
        except Exception as exc:
            return self.failure(f"Alpha Vantage request failed: {type(exc).__name__}")
        if not isinstance(payload, dict) or not payload:
            return self.failure("Alpha Vantage returned an empty response", status_code)
        if payload.get("Note"):
            self.paused_until = now + timedelta(minutes=1)
            AlphaVantageProvider._global_paused_until = self.paused_until
            return self.failure("Alpha Vantage rate limit reached; fallback providers will continue", 429)
        if payload.get("Information"):
            information = str(payload["Information"])
            is_limit = any(term in information.lower() for term in ("rate", "frequency", "limit", "premium"))
            if is_limit:
                self.paused_until = now + timedelta(minutes=1)
                AlphaVantageProvider._global_paused_until = self.paused_until
            return self.failure(
                "Alpha Vantage information response: " + information[:240],
                429 if is_limit else status_code,
            )
        if payload.get("Error Message"):
            return self.failure("Alpha Vantage invalid API call or symbol")
        if ttl:
            with self._cache_lock:
                self._cache[cache_key] = (now, payload)
        return self.success({"raw": payload}, "High")

    @staticmethod
    def _raw(result: ProviderResult) -> dict:
        return result.data.get("raw", {}) if result.success else {}

    def search_symbols(self, keywords: str) -> ProviderResult:
        result = self._request({"function": "SYMBOL_SEARCH", "keywords": str(keywords or "").strip()})
        if not result.success:
            return result
        matches = []
        for item in self._raw(result).get("bestMatches", []) or []:
            symbol = str(item.get("1. symbol", "")).strip()
            if not symbol:
                continue
            matches.append({
                "symbol": symbol,
                "name": item.get("2. name", ""),
                "type": item.get("3. type", ""),
                "region": item.get("4. region", ""),
                "market_open": item.get("5. marketOpen", ""),
                "market_close": item.get("6. marketClose", ""),
                "timezone": item.get("7. timezone", ""),
                "currency": item.get("8. currency", ""),
                "match_score": _number(item.get("9. matchScore")) or 0.0,
            })
        return self.success({"matches": matches, "raw": self._raw(result)}, "High" if matches else "Low") if matches else self.failure("Alpha Vantage symbol search returned no matches")

    def get_global_quote(self, symbol: str) -> ProviderResult:
        result = self._request({"function": "GLOBAL_QUOTE", "symbol": str(symbol or "").strip()})
        if not result.success:
            return result
        quote = self._raw(result).get("Global Quote", {}) or {}
        price = _number(quote.get("05. price"))
        if not price or price <= 0:
            return self.failure("Alpha Vantage quote unavailable or symbol invalid")
        change_text = quote.get("10. change percent", "")
        return self.success({
            "symbol": quote.get("01. symbol") or symbol,
            "price": price,
            "previous_close": _number(quote.get("08. previous close")),
            "change_percent": _number(change_text),
            "currency": _currency_hint(symbol),
            "raw": self._raw(result),
        }, "High")

    def get_daily_series(self, symbol: str, outputsize: str = "compact") -> ProviderResult:
        result = self._request({"function": "TIME_SERIES_DAILY", "symbol": str(symbol or "").strip(),
                                "outputsize": outputsize})
        if not result.success:
            return result
        raw = self._raw(result)
        series = raw.get("Time Series (Daily)", {}) or {}
        rows = []
        for date, values in series.items():
            rows.append({"Date": date, "Open": _number(values.get("1. open")),
                         "High": _number(values.get("2. high")), "Low": _number(values.get("3. low")),
                         "Close": _number(values.get("4. close")), "Volume": _number(values.get("5. volume"))})
        history = pd.DataFrame(rows)
        if history.empty:
            return self.failure("Alpha Vantage daily history unavailable or symbol invalid")
        history["Date"] = pd.to_datetime(history["Date"], errors="coerce")
        history = history.dropna(subset=["Date", "Close"]).sort_values("Date").set_index("Date")
        return self.success({"symbol": symbol, "history": history, "raw": raw}, "High")

    def get_etf_profile(self, symbol: str) -> ProviderResult:
        result = self._request({"function": "ETF_PROFILE", "symbol": str(symbol or "").strip()})
        if not result.success:
            return result
        raw = self._raw(result)
        if not raw or raw.get("symbol") in (None, "") and not any(
                key in raw for key in ("net_assets", "net_expense_ratio", "expense_ratio", "holdings", "sectors")):
            return self.failure("Alpha Vantage ETF profile unavailable or symbol invalid")
        net_assets = _number(raw.get("net_assets") or raw.get("netAssets") or raw.get("assets_under_management"))
        ter = _percentage(raw.get("net_expense_ratio") or raw.get("expense_ratio") or raw.get("expenseRatio"))
        currency = str(raw.get("currency", "") or _currency_hint(symbol))
        data = {
            "symbol": raw.get("symbol") or symbol,
            "currency": currency,
            "fund_size_native": net_assets,
            "ter_pct": ter,
            "ter_percent": ter,
            "turnover": _percentage(raw.get("portfolio_turnover") or raw.get("turnover")),
            "sectors": raw.get("sectors") or [],
            "holdings": raw.get("holdings") or [],
            "raw": raw,
        }
        if net_assets is not None and currency == "EUR":
            data["fund_size_eur"] = net_assets
        return self.success(data, "High")

    def get_fx_rate(self, from_currency: str, to_currency: str = "EUR") -> ProviderResult:
        source, target = str(from_currency or "").upper(), str(to_currency or "EUR").upper()
        if source == target:
            return self.success({"from_currency": source, "to_currency": target, "rate": 1.0,
                                 "fx_rate_to_eur": 1.0}, "High")
        result = self._request({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": source,
                                "to_currency": target})
        if not result.success:
            return result
        raw = self._raw(result)
        exchange = raw.get("Realtime Currency Exchange Rate", {}) or {}
        rate = _number(exchange.get("5. Exchange Rate"))
        if not rate or rate <= 0:
            return self.failure("Alpha Vantage FX rate unavailable")
        return self.success({"from_currency": source, "to_currency": target, "rate": rate,
                             "fx_rate_to_eur": rate, "raw": raw}, "High")

    def get_crypto_daily(self, symbol: str, market: str = "EUR") -> ProviderResult:
        result = self._request({"function": "DIGITAL_CURRENCY_DAILY", "symbol": str(symbol or "").upper(),
                                "market": str(market or "EUR").upper()})
        if not result.success:
            return result
        raw = self._raw(result); series = raw.get("Time Series (Digital Currency Daily)", {}) or {}
        market = str(market or "EUR").upper(); rows = []
        for date, values in series.items():
            close = (_number(values.get(f"4a. close ({market})")) or _number(values.get("4. close"))
                     or _number(values.get(f"4b. close ({market})")))
            rows.append({"Date": date, "Close": close})
        history = pd.DataFrame(rows)
        if history.empty:
            return self.failure("Alpha Vantage crypto history unavailable")
        history["Date"] = pd.to_datetime(history["Date"], errors="coerce")
        history = history.dropna(subset=["Date", "Close"]).sort_values("Date").set_index("Date")
        return self.success({"symbol": symbol, "currency": market, "history": history, "raw": raw}, "High")

    def get_price(self, symbol: str) -> ProviderResult:
        quote = self.get_global_quote(symbol)
        if quote.success:
            return quote
        daily = self.get_daily_series(symbol)
        if daily.success:
            closes = pd.to_numeric(daily.data["history"]["Close"], errors="coerce").dropna()
            if not closes.empty:
                return self.success({"symbol": symbol, "price": float(closes.iloc[-1]),
                                     "previous_close": float(closes.iloc[-2]) if len(closes) > 1 else None,
                                     "currency": _currency_hint(symbol), "history": daily.data["history"],
                                     "raw": daily.data.get("raw", {})}, "Medium")
        return self.failure("; ".join(filter(None, [quote.error, daily.error])) or "Alpha Vantage price unavailable",
                            quote.status_code or daily.status_code)

    def get_metadata(self, symbol: str) -> ProviderResult:
        return self.get_etf_profile(symbol)
