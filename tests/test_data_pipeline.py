from datetime import datetime, timezone
import json

import pandas as pd

from coverage_engine import DeepScanEngine, calculate_data_coverage
from data_gap_report import generate_data_gap_report
from news_provider import get_gdelt_news
from provider_registry import get_provider_registry
from providers.base import ProviderResult
from providers.openfigi_provider import build_mapping_request
from retry_queue import RetryQueue
from symbol_resolver import SymbolResolver
from symbol_resolver import avoid_recent_bad_symbols, generate_exchange_candidates


class FailedProvider:
    def __init__(self): self.calls = []
    def get_price(self, symbol):
        self.calls.append(symbol); return ProviderResult(False, "test", error="missing")
    def get_history(self, symbol, period): return ProviderResult(False, "test", error="missing")


def test_provider_registry_needs_no_paid_keys(monkeypatch):
    monkeypatch.setattr("provider_registry.read_secret", lambda *args: "")
    rows = {row["Provider"]: row for row in get_provider_registry()}
    assert rows["yfinance"]["Status"] == "Enabled"
    assert rows["Alpha Vantage"]["Status"] == "Disabled"
    assert rows["OpenFIGI"]["Status"] == "Enabled"
    assert rows["FMP"]["Status"] == "Disabled"
    assert rows["Twelve Data"]["Status"] == "Disabled"


def test_openfigi_no_key_request_builder_batches_five():
    request = build_mapping_request([f"ISIN{i}" for i in range(8)])
    assert "x-openfigi-apikey" not in {key.lower(): value for key, value in request.header_items()}
    payload = json.loads(request.data.decode())
    assert len(payload) == 5 and payload[0]["idType"] == "ID_ISIN"


def test_symbol_resolver_does_not_retry_fresh_bad_symbols():
    yahoo, stooq = FailedProvider(), FailedProvider()
    resolver = SymbolResolver(yahoo=yahoo, stooq=stooq)
    asset = {"isin": "TEST-BAD", "ticker_id": "BAD", "instrument": "Bad symbol"}
    first = resolver.resolve_price_symbol(asset); calls = len(yahoo.calls)
    second = resolver.resolve_price_symbol(asset)
    assert first["bad_symbols"] and second["chosen_symbol"] == ""
    assert len(yahoo.calls) == calls


def test_symbol_resolver_stores_bad_candidates():
    resolver = SymbolResolver(yahoo=FailedProvider(), stooq=FailedProvider())
    result = resolver.resolve_price_symbol({"isin": "TEST-STORE", "ticker_id": "NOPE"})
    assert "NOPE" in result["bad_symbols"]


def test_symbol_resolver_chooses_first_symbol_with_price_and_history():
    class Yahoo:
        def get_price(self, symbol):
            return ProviderResult(True, "yfinance", {"price": 10, "currency": "EUR"}, "High")
        def get_history(self, symbol, period):
            return ProviderResult(symbol == "GOOD.DE", "yfinance", {"history": [1, 2]} if symbol == "GOOD.DE" else {},
                                  "High", error="no history" if symbol != "GOOD.DE" else "")
    resolver = SymbolResolver(yahoo=Yahoo(), stooq=FailedProvider())
    result = resolver.resolve_price_symbol({"isin": "DETEST-FIRST", "price_symbol": "BAD.DE",
                                            "ticker_id": "GOOD", "instrument": "Good"})
    assert result["chosen_symbol"] == "GOOD.DE"
    assert result["candidate_symbols"][0]["status"] == "Bad"


def test_exchange_candidates_cover_requested_european_suffixes():
    candidates = generate_exchange_candidates({"ticker_id": "TEST", "isin": "DE000TEST000"})
    for suffix in [".DE", ".F", ".SG", ".MU", ".BE", ".AS", ".MI", ".PA", ".L"]:
        assert "TEST" + suffix in candidates


def test_recent_bad_symbol_is_filtered():
    now = datetime.now(timezone.utc).isoformat()
    assert avoid_recent_bad_symbols(["BAD", "GOOD"], {"BAD": {"last_tested": now}}) == ["GOOD"]


def test_data_coverage_calculation():
    holdings = pd.DataFrame([{"instrument": "A", "price_symbol": "A", "manual_current_price": 10, "currency": "EUR",
                              "category": "Core", "asset_type": "Stock", "valuation_ready": True}])
    candidates = pd.DataFrame([{"instrument": "B", "price_symbol": "B", "manual_current_price": 20, "currency": "USD",
                                "fx_rate_to_eur": .9, "category": "Growth", "asset_type": "ETF",
                                "ter_pct": .2, "factsheet_url": "https://issuer.test/f.pdf",
                                "recommendation_ready": True, "valuation_ready": True}])
    result = calculate_data_coverage(holdings, candidates, [{"title": "news"}])
    assert result["price_coverage"] == 100
    assert result["symbol_coverage"] == 100
    assert result["metadata_coverage"] == 100
    assert result["ter_coverage"] == 100
    assert result["fx_coverage"] == 100


def test_data_gap_report_lists_precise_missing_fields():
    gaps = generate_data_gap_report(pd.DataFrame([{"instrument": "A", "isin": "X", "currency": "USD"}]),
                                    pd.DataFrame())
    assert {"price", "symbol", "category", "asset type", "FX"}.issubset(set(gaps["Missing field"]))


def test_data_gap_report_includes_bad_symbol_cache_reason():
    gaps = generate_data_gap_report(pd.DataFrame(), pd.DataFrame(), symbol_resolutions=[{
        "instrument": "Broken ETF", "isin": "IE00BAD", "bad_symbols": {
            "BAD.DE": {"reason": "No price data", "last_tested": "2026-06-20T10:00:00+00:00"}}}])
    row = gaps.iloc[0]
    assert row["Missing field"] == "Bad symbol"
    assert row["Current value"] == "BAD.DE"
    assert row["Error"] == "No price data"


def test_deep_scan_skips_fresh_complete_assets():
    now = datetime.now(timezone.utc).isoformat()
    holdings = pd.DataFrame([{"instrument": "A", "isin": "A", "valuation_ready": True,
                              "last_updated": now, "last_auto_repair_at": now, "asset_type": "Stock"}])
    class Engine:
        def enrich_asset(self, *args, **kwargs): raise AssertionError("fresh asset should be skipped")
    result = DeepScanEngine(Engine()).run_chunk(holdings, pd.DataFrame(), 5)
    assert result["processed"] == 0 and result["remaining"] == 0


def test_deep_scan_processes_incomplete_assets_in_chunks():
    holdings = pd.DataFrame([{"instrument": name, "isin": name, "asset_type": "Stock"} for name in "ABC"])
    class Engine:
        def enrich_asset(self, asset, candidate, force_web=False): return {**asset, "valuation_ready": True}
    saved = []
    result = DeepScanEngine(Engine(), max_workers=4).run_chunk(holdings, pd.DataFrame(), 2,
                                                               partial_save_callback=saved.append)
    assert result["processed"] == 2 and result["remaining"] == 1 and len(saved) == 2


def test_gdelt_failure_does_not_crash(monkeypatch):
    monkeypatch.setattr("news_provider.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down")))
    assert get_gdelt_news() == []


def test_provider_failures_are_stored_for_retry():
    class Repository:
        def __init__(self): self.rows = []
        def save_provider_failure(self, row): self.rows.append(row)
    repository = Repository(); queue = RetryQueue(repository)
    row = queue.record_failure("Yahoo", {"isin": "X"}, "BAD", "Timeout", "timed out")
    assert repository.rows and row["retry_after"] and row["attempts"] == 1
