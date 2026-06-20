import pandas as pd

from market_data_engine import MarketDataEngine
from market_data import MarketQuote
from provider_registry import get_provider_registry
from providers.alpha_vantage_provider import AlphaVantageProvider
from providers.base import ProviderResult
from symbol_resolver import SymbolResolver, generate_alpha_vantage_candidates
from valuation import valuate_holdings


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.payload)


def enabled_provider(monkeypatch, payload):
    AlphaVantageProvider._global_paused_until = None
    AlphaVantageProvider._cache.clear()
    monkeypatch.setattr("providers.base.read_secret", lambda name, default="":
                        "secret-test-key" if name == "ALPHA_VANTAGE_API_KEY" else default)
    return AlphaVantageProvider(session=FakeSession(payload))


def test_provider_is_disabled_when_key_is_missing(monkeypatch):
    monkeypatch.setattr("providers.base.read_secret", lambda *args: "")
    provider = AlphaVantageProvider(session=FakeSession({}))
    assert provider.is_enabled() is False
    assert provider.status_row()["Status"] == "Disabled"


def test_provider_is_enabled_when_key_is_present(monkeypatch):
    provider = enabled_provider(monkeypatch, {})
    assert provider.is_enabled() is True
    assert provider.status_row()["Status"] == "Enabled"


def test_registry_enables_alpha_vantage_only_when_key_is_present(monkeypatch):
    monkeypatch.setattr("provider_registry.read_secret", lambda name, default="":
                        "configured" if name == "ALPHA_VANTAGE_API_KEY" else default)
    rows = {row["Provider"]: row for row in get_provider_registry()}
    assert rows["Alpha Vantage"]["Status"] == "Enabled"
    assert rows["Alpha Vantage"]["Key required?"] == "Yes"


def test_request_uses_key_without_exposing_it_in_result_or_status(monkeypatch):
    provider = enabled_provider(monkeypatch, {"Global Quote": {"05. price": "10"}})
    result = provider.get_global_quote("TEST")
    assert provider.session.calls[0]["params"]["apikey"] == "secret-test-key"
    assert "secret-test-key" not in str(result.data)
    assert "secret-test-key" not in str(provider.status_row())


def test_global_quote_parser(monkeypatch):
    provider = enabled_provider(monkeypatch, {"Global Quote": {
        "01. symbol": "MSFT", "05. price": "450.25", "08. previous close": "445.00",
        "10. change percent": "1.1798%",
    }})
    result = provider.get_global_quote("MSFT")
    assert result.success
    assert result.data["price"] == 450.25
    assert result.data["previous_close"] == 445.0
    assert result.data["change_percent"] == 1.1798
    assert result.data["currency"] == "USD"


def test_daily_series_parser(monkeypatch):
    provider = enabled_provider(monkeypatch, {"Time Series (Daily)": {
        "2026-06-19": {"1. open": "10", "2. high": "12", "3. low": "9", "4. close": "11", "5. volume": "1000"},
        "2026-06-18": {"1. open": "9", "2. high": "11", "3. low": "8", "4. close": "10", "5. volume": "900"},
    }})
    result = provider.get_daily_series("TEST")
    assert result.success
    history = result.data["history"]
    assert list(history.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert history.iloc[-1]["Close"] == 11


def test_symbol_search_parser(monkeypatch):
    provider = enabled_provider(monkeypatch, {"bestMatches": [{
        "1. symbol": "BMW.DEX", "2. name": "Bayerische Motoren Werke AG", "3. type": "Equity",
        "4. region": "Germany", "8. currency": "EUR", "9. matchScore": "0.95",
    }]})
    result = provider.search_symbols("BMW")
    assert result.success
    assert result.data["matches"][0]["symbol"] == "BMW.DEX"
    assert result.data["matches"][0]["currency"] == "EUR"


def test_etf_profile_maps_expense_ratio_and_assets(monkeypatch):
    provider = enabled_provider(monkeypatch, {
        "symbol": "TEST.DEX", "currency": "EUR", "net_assets": "1250000000",
        "net_expense_ratio": "0.0020", "portfolio_turnover": "0.15",
        "sectors": [{"technology": "20"}], "holdings": [{"symbol": "ABC"}],
    })
    result = provider.get_etf_profile("TEST.DEX")
    assert result.success
    assert result.data["ter_pct"] == 0.2
    assert result.data["fund_size_eur"] == 1_250_000_000
    assert result.data["turnover"] == 15.0


def test_rate_limit_note_is_non_fatal_and_pauses_provider(monkeypatch):
    provider = enabled_provider(monkeypatch, {"Note": "Thank you for using Alpha Vantage. API call frequency exceeded."})
    result = provider.get_global_quote("MSFT")
    assert result.success is False
    assert result.status_code == 429
    assert provider.paused_until is not None


def test_invalid_symbol_is_non_fatal(monkeypatch):
    provider = enabled_provider(monkeypatch, {"Error Message": "Invalid API call."})
    result = provider.get_price("NOT-A-SYMBOL")
    assert result.success is False
    assert result.error


def test_engine_falls_back_to_yfinance_when_alpha_fails():
    history = pd.DataFrame({"Close": [99.0, 100.0]})

    class Alpha:
        name = "Alpha Vantage"
        def is_enabled(self): return True
        def get_price(self, symbol): return ProviderResult(False, self.name, error="rate limited", status_code=429)

    class Yahoo:
        name = "yfinance"
        def get_price(self, symbol): return ProviderResult(True, self.name, {"price": 100, "currency": "EUR"}, "High")
        def get_history(self, symbol, period): return ProviderResult(True, self.name, {"history": history}, "High")

    engine = MarketDataEngine(scraping_enabled=False)
    engine.alpha = Alpha(); engine.yahoo = Yahoo()
    result = engine.quick_quote("TEST.DE", "TEST.DEX")
    assert result["latest_price"] == 100
    assert result["provider"] == "yfinance"


def test_alpha_quick_quote_fields_are_retained_for_persistence():
    holdings = pd.DataFrame([{"instrument": "Microsoft", "price_symbol": "MSFT", "quantity": 2,
                              "manual_current_price": 400, "buy_in_value_eur": 700, "currency": "USD"}])
    quote = MarketQuote("MSFT", latest_price=450, previous_close=445, currency="USD",
                        fetched_at="2026-06-20T12:00:00+00:00", provider="Alpha Vantage",
                        confidence="High", provider_symbol="MSFT")
    valued = valuate_holdings(holdings, {"MSFT": quote}, {"USD": 0.9}).iloc[0]
    assert valued["price_source"] == "Alpha Vantage"
    assert valued["alpha_vantage_symbol"] == "MSFT"
    assert valued["alpha_vantage_last_price"] == 450
    assert valued["data_confidence"] == "High"


def test_alpha_candidate_generation_uses_exchange_specific_suffixes():
    assert "BMW.DEX" in generate_alpha_vantage_candidates(
        {"ticker_id": "BMW", "exchange": "XETRA", "isin": "DE0005190003"})
    assert "VOD.LON" in generate_alpha_vantage_candidates(
        {"ticker_id": "VOD", "exchange": "London", "isin": "GB00BH4HKS39"})


def test_alpha_resolver_prefers_symbol_search_results():
    class Alpha:
        def is_enabled(self): return True
        def search_symbols(self, query):
            return ProviderResult(True, "Alpha Vantage", {"matches": [
                {"symbol": "BMW.DEX", "currency": "EUR", "match_score": 0.98}]}, "High")
        def get_global_quote(self, symbol):
            return ProviderResult(True, "Alpha Vantage", {"price": 80, "currency": "EUR"}, "High")

    resolver = SymbolResolver(alpha=Alpha())
    result = resolver.resolve_alpha_vantage_symbol(
        {"isin": "DE0005190003", "instrument": "BMW", "ticker_id": "BMW", "exchange": "XETRA"})
    assert result["alpha_vantage_symbol"] == "BMW.DEX"
    assert result["alpha_vantage_symbol_confidence"] == "High"
