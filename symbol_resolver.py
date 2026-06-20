"""Cached, bounded Yahoo/Stooq symbol resolution with seven-day bad-symbol memory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data_cache import parse_timestamp
from providers import AlphaVantageProvider, StooqProvider, YFinanceProvider

EU_SUFFIXES = [".DE", ".F", ".SG", ".MU", ".BE", ".AS", ".MI", ".PA", ".L", ""]
ALPHA_EXCHANGE_SUFFIXES = {
    "XETRA": ".DEX", "XETR": ".DEX", "DEX": ".DEX", "DE": ".DEX", "GERMANY": ".DEX",
    "LONDON": ".LON", "LSE": ".LON", "LN": ".LON",
    "AMSTERDAM": ".AMS", "AMS": ".AMS", "MILAN": ".MIL", "MIL": ".MIL",
    "PARIS": ".PAR", "PAR": ".PAR", "SWITZERLAND": ".SWX", "SWX": ".SWX",
}
_MEMORY_CACHE: dict[str, dict] = {}


def asset_key(asset: dict) -> str:
    return str(asset.get("id") or asset.get("isin") or asset.get("wkn") or asset.get("instrument") or "").strip()


def generate_exchange_candidates(asset: dict) -> list[str]:
    """Generate a bounded, deterministic exchange list instead of random retries."""
    exact = str(asset.get("price_symbol", "") or "").strip()
    ticker = str(asset.get("ticker_id", "") or "").strip().upper()
    figi = str(asset.get("openfigi_ticker", "") or "").strip().upper()
    exchange = str(asset.get("exchange", "") or "").strip().upper()
    exchange_suffix = {"GR": ".DE", "GY": ".DE", "XETR": ".DE", "GF": ".F", "NA": ".AS",
                       "IM": ".MI", "FP": ".PA", "LN": ".L"}.get(exchange, "")
    candidates = [exact] if exact else []
    for base in (figi, ticker):
        if not base: continue
        if exchange_suffix: candidates.append(base + exchange_suffix)
        is_us = str(asset.get("isin", "")).upper().startswith("US") or str(asset.get("region", "")).lower() in {"us", "usa", "united states"}
        suffixes = ([""] + EU_SUFFIXES[:-1]) if is_us else EU_SUFFIXES
        candidates.extend(base if not suffix or base.endswith(suffix) else base + suffix for suffix in suffixes)
    isin = str(asset.get("isin", "") or "").strip()
    if isin: candidates.extend([isin + ".SG", isin])
    return list(dict.fromkeys(value for value in candidates if value))[:24]


def generate_yahoo_candidates(asset: dict) -> list[str]:
    return generate_exchange_candidates(asset)


def generate_alpha_vantage_candidates(asset: dict) -> list[str]:
    """Generate only defensible Alpha Vantage symbols; search results are preferred."""
    exact = str(asset.get("alpha_vantage_symbol", "") or "").strip().upper()
    price_symbol = str(asset.get("price_symbol", "") or "").strip().upper()
    exchange = str(asset.get("exchange", "") or asset.get("region", "") or "").strip().upper()
    suffix = ALPHA_EXCHANGE_SUFFIXES.get(exchange, "")
    candidates = [exact] if exact else []
    # Unsuffixed US/global tickers and already-Alpha-formatted symbols are safe
    # to test. Yahoo exchange suffixes are intentionally not translated here.
    if price_symbol and ("." not in price_symbol or price_symbol.endswith(tuple(set(ALPHA_EXCHANGE_SUFFIXES.values())))):
        candidates.append(price_symbol)
    for base in (asset.get("openfigi_ticker"), asset.get("ticker_id")):
        base = str(base or "").strip().upper()
        if not base:
            continue
        if suffix:
            candidates.append(base if base.endswith(suffix) else base + suffix)
        if str(asset.get("isin", "")).upper().startswith("US") or not exchange:
            candidates.append(base)
    return list(dict.fromkeys(item for item in candidates if item))[:12]


def avoid_recent_bad_symbols(symbols: list[str], bad_symbols: dict | None = None) -> list[str]:
    bad_symbols = bad_symbols or {}
    return [symbol for symbol in symbols
            if symbol not in bad_symbols or not SymbolResolver._bad_is_fresh(bad_symbols[symbol])]


def is_probably_invalid_symbol_error(error: str) -> bool:
    text = str(error or "").lower()
    return any(term in text for term in ("no usable", "no price data", "possibly delisted",
                                          "not found", "no timezone", "invalid symbol"))


class SymbolResolver:
    def __init__(self, repository=None, yahoo=None, stooq=None, alpha=None):
        self.repository = repository; self.yahoo = yahoo or YFinanceProvider(); self.stooq = stooq or StooqProvider()
        self.alpha = alpha or AlphaVantageProvider()

    def load_cached_symbol_resolution(self, key: str) -> dict | None:
        if self.repository:
            try:
                row = self.repository.load_symbol_resolution(key)
                if row: return row
            except Exception: pass
        return _MEMORY_CACHE.get(key)

    def store_symbol_resolution(self, asset: dict, result: dict) -> None:
        key = asset_key(asset); payload = {**result, "asset_key": key, "isin": asset.get("isin", ""),
                                           "instrument": asset.get("instrument", "")}
        _MEMORY_CACHE[key] = payload
        if self.repository:
            try: self.repository.save_symbol_resolution(payload)
            except Exception: pass

    @staticmethod
    def _bad_is_fresh(entry: dict) -> bool:
        tested = parse_timestamp(entry.get("last_tested"))
        return bool(tested and datetime.now(timezone.utc) - tested < timedelta(days=7))

    def mark_bad_symbol(self, asset: dict, symbol: str, reason: str) -> None:
        cached = self.load_cached_symbol_resolution(asset_key(asset)) or {}; bad = dict(cached.get("bad_symbols") or {})
        bad[symbol] = {"reason": reason, "last_tested": datetime.now(timezone.utc).isoformat()}
        cached.update({"bad_symbols": bad, "chosen_symbol": cached.get("chosen_symbol", ""),
                       "candidate_symbols": cached.get("candidate_symbols", []), "confidence": cached.get("confidence", "Low"),
                       "source": cached.get("source", "Symbol resolver"), "last_tested": datetime.now(timezone.utc).isoformat()})
        self.store_symbol_resolution(asset, cached)

    def test_symbol(self, symbol: str) -> dict:
        yahoo = self.yahoo.get_price(symbol)
        if yahoo.success:
            history = self.yahoo.get_history(symbol, "1mo")
            if history.success:
                return {"symbol": symbol, "status": "Working", "price_available": True,
                        "history_available": True, "currency": yahoo.data.get("currency", ""),
                        "source": "yfinance", "error": "", "last_tested": yahoo.fetched_at}
        stooq = self.stooq.get_price(symbol)
        if stooq.success and stooq.data.get("history_rows", 0) > 1:
            return {"symbol": symbol, "status": "Working", "price_available": True,
                    "history_available": True, "currency": "",
                    "source": "Stooq", "error": "", "last_tested": stooq.fetched_at}
        return {"symbol": symbol, "status": "Bad", "price_available": False, "history_available": False,
                "currency": "", "source": "yfinance + Stooq",
                "error": ("Price returned without recent history" if yahoo.success else yahoo.error) or stooq.error,
                "last_tested": datetime.now(timezone.utc).isoformat()}

    def resolve_alpha_vantage_symbol(self, asset: dict) -> dict:
        """Resolve and cache a provider-specific symbol without rewriting Yahoo symbols."""
        cached = self.load_cached_symbol_resolution(asset_key(asset)) or {}
        tested_at = parse_timestamp(cached.get("alpha_vantage_last_tested"))
        error = str(cached.get("alpha_vantage_error", "") or "")
        retryable_error = any(term in error.lower() for term in ("rate limit", "paused", "timeout", "network"))
        if tested_at and datetime.now(timezone.utc) - tested_at < timedelta(days=7):
            if cached.get("alpha_vantage_symbol") or (error and not retryable_error):
                return cached
        if not self.alpha.is_enabled():
            return {**cached, "alpha_vantage_symbol": "", "alpha_vantage_candidates": [],
                    "alpha_vantage_error": "Alpha Vantage disabled: API key not configured"}

        candidates: list[str] = []
        query = str(asset.get("instrument") or asset.get("ticker_id") or asset.get("isin") or "").strip()
        search_error = ""
        if query:
            search = self.alpha.search_symbols(query)
            if search.success:
                ranked = sorted(search.data.get("matches", []),
                                key=lambda item: (str(item.get("currency", "")).upper() == "EUR",
                                                  float(item.get("match_score", 0) or 0)), reverse=True)
                candidates.extend(str(item.get("symbol", "")) for item in ranked if item.get("symbol"))
            else:
                search_error = search.error
                if search.status_code == 429:
                    return {**cached, "alpha_vantage_symbol": "", "alpha_vantage_candidates": [],
                            "alpha_vantage_error": search_error,
                            "alpha_vantage_last_tested": datetime.now(timezone.utc).isoformat()}
        candidates.extend(generate_alpha_vantage_candidates(asset))
        candidates = list(dict.fromkeys(item for item in candidates if item))[:8]
        attempts = []
        for symbol in candidates:
            quote = self.alpha.get_global_quote(symbol)
            attempts.append({"symbol": symbol, "status": "Working" if quote.success else "Bad",
                             "currency": quote.data.get("currency", "") if quote.success else "",
                             "error": quote.error, "last_tested": quote.fetched_at})
            if quote.success:
                resolution = {**cached, "alpha_vantage_symbol": symbol,
                              "alpha_vantage_candidates": attempts, "alpha_vantage_error": "",
                              "alpha_vantage_symbol_confidence": "High",
                              "alpha_vantage_last_tested": quote.fetched_at}
                self.store_symbol_resolution(asset, resolution)
                return resolution
            if quote.status_code == 429:
                search_error = quote.error
                break
        resolution = {**cached, "alpha_vantage_symbol": "", "alpha_vantage_candidates": attempts,
                      "alpha_vantage_error": search_error or "No working Alpha Vantage symbol found",
                      "alpha_vantage_symbol_confidence": "Low",
                      "alpha_vantage_last_tested": datetime.now(timezone.utc).isoformat()}
        # Invalid/no-match results get the seven-day cache. Transient provider
        # failures remain retryable after the provider cooldown.
        if not any(term in resolution["alpha_vantage_error"].lower()
                   for term in ("rate limit", "paused", "timeout", "network")):
            self.store_symbol_resolution(asset, resolution)
        return resolution

    @staticmethod
    def select_best_symbol(tested: list[dict]) -> dict | None:
        working = [item for item in tested if item.get("price_available") and item.get("history_available")]
        return max(working, key=lambda item: (item.get("currency") == "EUR", item.get("history_available"),
                                              item.get("source") == "yfinance")) if working else None

    def resolve_price_symbol(self, asset: dict) -> dict:
        cached = self.load_cached_symbol_resolution(asset_key(asset)) or {}
        if self.alpha.is_enabled() and not cached.get("alpha_vantage_symbol"):
            alpha_resolution = self.resolve_alpha_vantage_symbol(asset)
            cached = {**cached, **alpha_resolution}
        tested_at = parse_timestamp(cached.get("last_tested"))
        if cached.get("chosen_symbol") and tested_at and datetime.now(timezone.utc) - tested_at < timedelta(days=7):
            return cached
        bad = dict(cached.get("bad_symbols") or {}); tested = []
        for symbol in avoid_recent_bad_symbols(generate_yahoo_candidates(asset), bad):
            result = self.test_symbol(symbol); tested.append(result)
            if result["status"] == "Working":
                resolution = {**{key: cached.get(key) for key in ("alpha_vantage_symbol", "alpha_vantage_candidates",
                                                                  "alpha_vantage_error", "alpha_vantage_symbol_confidence",
                                                                  "alpha_vantage_last_tested")
                                 if key in cached},
                              "chosen_symbol": symbol, "candidate_symbols": tested, "bad_symbols": bad,
                              "confidence": "High" if result["source"] == "yfinance" and result["history_available"] else "Medium",
                              "source": result["source"], "last_tested": result["last_tested"], "error": ""}
                self.store_symbol_resolution(asset, resolution); return resolution
            bad[symbol] = {"reason": result["error"], "last_tested": result["last_tested"]}
        resolution = {**{key: cached.get(key) for key in ("alpha_vantage_symbol", "alpha_vantage_candidates",
                                                          "alpha_vantage_error", "alpha_vantage_symbol_confidence",
                                                          "alpha_vantage_last_tested")
                         if key in cached},
                      "chosen_symbol": "", "candidate_symbols": tested, "bad_symbols": bad,
                      "confidence": "Low", "source": "Symbol resolver", "last_tested": datetime.now(timezone.utc).isoformat(),
                      "error": "No working symbol found"}
        self.store_symbol_resolution(asset, resolution); return resolution


def resolve_price_symbol(asset, resolver=None): return (resolver or SymbolResolver()).resolve_price_symbol(asset)
def test_symbol(symbol, resolver=None): return (resolver or SymbolResolver()).test_symbol(symbol)
def select_best_symbol(candidates, resolver=None): return (resolver or SymbolResolver()).select_best_symbol(candidates)
def store_symbol_resolution(asset_id, result): _MEMORY_CACHE[str(asset_id)] = dict(result)
def load_cached_symbol_resolution(asset_id): return _MEMORY_CACHE.get(str(asset_id))
def fresh_bad_symbols(resolutions: list[dict] | None = None) -> set[str]:
    """Return symbols still inside their seven-day retry cooldown."""
    rows = resolutions if resolutions is not None else list(_MEMORY_CACHE.values())
    output = set()
    for row in rows:
        for symbol, detail in (row.get("bad_symbols") or {}).items():
            if SymbolResolver._bad_is_fresh(detail):
                output.add(str(symbol))
    return output


def mark_bad_symbol(symbol, reason):
    _MEMORY_CACHE.setdefault("global", {"bad_symbols": {}})["bad_symbols"][symbol] = {
        "reason": reason, "last_tested": datetime.now(timezone.utc).isoformat()}
