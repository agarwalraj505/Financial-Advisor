import pandas as pd

import market_data
from market_data import (MarketQuote, enrich_holding_with_market_data, fetch_fx_rate_to_eur,
                         fetch_market_quote, get_latest_price, get_returns, normalise_currency)


class FakeTicker:
    fast_info = {"last_price": 102.5, "previous_close": 100.0, "currency": "USD"}

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period, interval, auto_adjust):
        return pd.DataFrame({"Close": [100.0, 102.5]}, index=pd.date_range("2026-01-01", periods=2))


def test_fetch_market_quote_reads_price_currency_and_all_histories(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Ticker", FakeTicker)
    quote = fetch_market_quote("TEST")
    assert quote.latest_price == 102.5
    assert quote.previous_close == 100.0
    assert quote.currency == "USD"
    assert set(quote.histories) == {"5d", "1mo", "1y"}
    assert quote.fetched_at


def test_fetch_market_quote_fails_gracefully(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Ticker", lambda symbol: (_ for _ in ()).throw(ConnectionError("offline")))
    quote = fetch_market_quote("FAIL")
    assert not quote.is_available
    assert "offline" in quote.error


def test_usd_fx_conversion_uses_inverse_eurusd_quote(monkeypatch):
    monkeypatch.setattr(market_data, "fetch_market_quote",
                        lambda symbol: MarketQuote(symbol=symbol, latest_price=1.25, currency="USD"))
    rate, error = fetch_fx_rate_to_eur("USD")
    assert rate == 0.8
    assert error == ""


def test_eur_fx_rate_is_one():
    assert fetch_fx_rate_to_eur("EUR") == (1.0, "")


def test_yahoo_gbp_pence_currency_is_preserved():
    assert normalise_currency("GBp") == "GBX"


def test_get_latest_price_uses_coingecko_for_crypto(monkeypatch):
    get_latest_price.clear()
    monkeypatch.setattr(market_data, "_coingecko_json", lambda path, params: {"bitcoin": {"eur": 60000}})
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
    monkeypatch.setattr(market_data, "get_latest_price", lambda symbol: None)
    monkeypatch.setattr(market_data, "get_fx_rate_to_eur", lambda currency: 1.0)
    row = enrich_holding_with_market_data({"price_symbol": "FAIL", "quantity": 2,
        "manual_current_price": 40, "buy_in_value_eur": 70, "currency": "EUR"})
    assert row["price_source"] == "Manual fallback"
    assert row["current_value_eur"] == 80
