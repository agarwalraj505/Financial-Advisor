"""yfinance prices, histories, symbol search, and best-effort metadata."""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from providers.base import BaseProvider, ProviderResult


class YFinanceProvider(BaseProvider):
    name = "yfinance"
    purpose = "Prices/history"

    def __init__(self, timeout_seconds: int = 8):
        super().__init__(); self.timeout_seconds = timeout_seconds

    def get_price(self, symbol: str) -> ProviderResult:
        if not symbol:
            return self.failure("Missing price symbol")
        try:
            ticker = yf.Ticker(symbol)
            fast = ticker.fast_info
            price = fast.get("last_price") if hasattr(fast, "get") else getattr(fast, "last_price", None)
            currency = fast.get("currency") if hasattr(fast, "get") else getattr(fast, "currency", None)
            if not price:
                history = ticker.history(period="5d", interval="1d", auto_adjust=False, timeout=self.timeout_seconds)
                close = pd.to_numeric(history.get("Close"), errors="coerce").dropna()
                price = float(close.iloc[-1]) if not close.empty else None
            if not price:
                return self.failure("No usable yfinance price")
            return self.success({"price": float(price), "currency": currency or ""}, "High")
        except Exception as exc:
            return self.failure(str(exc) or "yfinance price failed")

    def get_history(self, symbol: str, period: str = "1y") -> ProviderResult:
        try:
            history = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False, timeout=self.timeout_seconds)
            if history.empty:
                return self.failure("No yfinance history")
            self.last_success, self.last_error = pd.Timestamp.utcnow().isoformat(), ""
            return ProviderResult(True, self.name, {"history": history}, "High", fetched_at=self.last_success)
        except Exception as exc:
            return self.failure(str(exc) or "yfinance history failed")

    def search(self, query: str, max_results: int = 6) -> ProviderResult:
        if not query:
            return self.failure("Empty search query")
        try:
            quotes = yf.Search(query, max_results=max_results, news_count=0, lists_count=0,
                               include_research=False, timeout=self.timeout_seconds, raise_errors=False).quotes
            normalized = [{"symbol": item.get("symbol", ""), "name": item.get("longname") or item.get("shortname", ""),
                           "exchange": item.get("exchange", ""), "quote_type": item.get("quoteType", "")}
                          for item in quotes]
            return self.success({"matches": normalized}, "Medium" if normalized else "Low")
        except Exception as exc:
            return self.failure(str(exc) or "yfinance search failed")

    def get_metadata(self, symbol: str) -> ProviderResult:
        """Metadata is best effort. Missing TER remains blank and needs confirmation."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            fast = ticker.fast_info
            currency = info.get("currency") or (fast.get("currency") if hasattr(fast, "get") else None)
            data = {"instrument": info.get("longName") or info.get("shortName"),
                    "currency": currency, "exchange": info.get("exchange"),
                    "asset_type": info.get("quoteType"), "fund_size_eur": info.get("totalAssets"),
                    "issuer": info.get("fundFamily"), "ter_percent": info.get("annualReportExpenseRatio")}
            return self.success({key: value for key, value in data.items() if value not in (None, "")}, "Medium")
        except Exception as exc:
            return self.failure(str(exc) or "yfinance metadata failed")

    def get_news(self, symbol: str) -> ProviderResult:
        try:
            items = yf.Ticker(symbol).news or []
            return self.success({"items": items}, "Medium") if items else self.failure("No yfinance news")
        except Exception as exc:
            return self.failure(str(exc) or "yfinance news failed")
