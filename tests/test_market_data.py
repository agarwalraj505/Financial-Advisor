import pandas as pd

import market_data
from market_data import MarketQuote, fetch_fx_rate_to_eur, fetch_market_quote


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
