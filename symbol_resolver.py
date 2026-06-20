"""Cached, bounded Yahoo/Stooq symbol resolution with seven-day bad-symbol memory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data_cache import parse_timestamp
from providers import StooqProvider, YFinanceProvider

EU_SUFFIXES = [".DE", ".F", ".SG", ".MU", ".BE", ".AS", ".MI", ".PA", ".L", ""]
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


def avoid_recent_bad_symbols(symbols: list[str], bad_symbols: dict | None = None) -> list[str]:
    bad_symbols = bad_symbols or {}
    return [symbol for symbol in symbols
            if symbol not in bad_symbols or not SymbolResolver._bad_is_fresh(bad_symbols[symbol])]


def is_probably_invalid_symbol_error(error: str) -> bool:
    text = str(error or "").lower()
    return any(term in text for term in ("no usable", "no price data", "possibly delisted",
                                          "not found", "no timezone", "invalid symbol"))


class SymbolResolver:
    def __init__(self, repository=None, yahoo=None, stooq=None):
        self.repository = repository; self.yahoo = yahoo or YFinanceProvider(); self.stooq = stooq or StooqProvider()

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

    @staticmethod
    def select_best_symbol(tested: list[dict]) -> dict | None:
        working = [item for item in tested if item.get("price_available") and item.get("history_available")]
        return max(working, key=lambda item: (item.get("currency") == "EUR", item.get("history_available"),
                                              item.get("source") == "yfinance")) if working else None

    def resolve_price_symbol(self, asset: dict) -> dict:
        cached = self.load_cached_symbol_resolution(asset_key(asset)) or {}
        tested_at = parse_timestamp(cached.get("last_tested"))
        if cached.get("chosen_symbol") and tested_at and datetime.now(timezone.utc) - tested_at < timedelta(days=7):
            return cached
        bad = dict(cached.get("bad_symbols") or {}); tested = []
        for symbol in avoid_recent_bad_symbols(generate_yahoo_candidates(asset), bad):
            result = self.test_symbol(symbol); tested.append(result)
            if result["status"] == "Working":
                resolution = {"chosen_symbol": symbol, "candidate_symbols": tested, "bad_symbols": bad,
                              "confidence": "High" if result["source"] == "yfinance" and result["history_available"] else "Medium",
                              "source": result["source"], "last_tested": result["last_tested"], "error": ""}
                self.store_symbol_resolution(asset, resolution); return resolution
            bad[symbol] = {"reason": result["error"], "last_tested": result["last_tested"]}
        resolution = {"chosen_symbol": "", "candidate_symbols": tested, "bad_symbols": bad,
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
