import pandas as pd

import market_data
from market_data import (MarketQuote, enrich_holding_with_market_data, fetch_fx_rate_to_eur,
                         fetch_market_quote, get_latest_price, get_returns, normalise_currency)
from providers.base import ProviderResult


def test_fetch_market_quote_reads_price_currency_and_all_histories(monkeypatch):
    histories = {period: pd.DataFrame({"Close": [100.0, 102.5]}) for period in ("5d", "1mo", "1y")}
    class Engine:
        def quick_quote(self, symbol):
            return {"symbol": symbol, "latest_price": 102.5, "previous_close": 100,
                    "currency": "USD", "histories": histories, "fetched_at": "now", "error": ""}
    monkeypatch.setattr(market_data, "_engine", Engine)
    quote = fetch_market_quote("TEST")
    assert quote.latest_price == 102.5
    assert quote.previous_close == 100.0
    assert quote.currency == "USD"
    assert set(quote.histories) == {"5d", "1mo", "1y"}
    assert quote.fetched_at


def test_fetch_market_quote_fails_gracefully(monkeypatch):
    class Engine:
        def quick_quote(self, symbol):
            return {"symbol": symbol, "latest_price": None, "error": "offline"}
    monkeypatch.setattr(market_data, "_engine", Engine)
    quote = fetch_market_quote("FAIL")
    assert not quote.is_available
    assert "offline" in quote.error


def test_usd_fx_conversion_uses_inverse_eurusd_quote(monkeypatch):
    class Engine:
        def fx_rate_to_eur(self, currency):
            return ProviderResult(True, "ECB", {"fx_rate_to_eur": .8}, "High")
    monkeypatch.setattr(market_data, "_engine", Engine)
    rate, error = fetch_fx_rate_to_eur("USD")
    assert rate == 0.8
    assert error == ""


def test_eur_fx_rate_is_one():
    assert fetch_fx_rate_to_eur("EUR") == (1.0, "")


def test_yahoo_gbp_pence_currency_is_preserved():
    assert normalise_currency("GBp") == "GBX"


def test_get_latest_price_uses_coingecko_for_crypto(monkeypatch):
    get_latest_price.clear()
    monkeypatch.setattr(market_data, "get_market_quote",
                        lambda symbol: MarketQuote(symbol, latest_price=60000, currency="EUR"))
    assert get_latest_price("BTC-USD") == 60000
    get_latest_price.clear()


def test_get_returns_from_cached_history(monkeypatch):
    market_data.get_price_history.clear()
    history = pd.DataFrame({"Close": range(100, 130)}, index=pd.date_range("2026-01-01", periods=30))
    monkeypatch.setattr(market_data, "get_price_history", lambda symbol, period="1y": history)
    returns = get_returns("TEST")
    assert returns["1d"] > 0
    assert returns["1m"] > 0


def test_enrich_holding_uses_manual_fallback(monkeypatch):
    class Engine:
        def enrich_asset(self, row, is_candidate=False, force_web=False):
            return {**row, "price_source": "Manual fallback", "current_value_eur": 80}
    monkeypatch.setattr(market_data, "_engine", Engine)
    row = enrich_holding_with_market_data({"price_symbol": "FAIL", "quantity": 2,
        "manual_current_price": 40, "buy_in_value_eur": 70, "currency": "EUR"})
    assert row["price_source"] == "Manual fallback"
    assert row["current_value_eur"] == 80
