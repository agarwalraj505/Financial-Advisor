import pandas as pd

from storage import (clear_valuation_history, load_portfolio, load_valuation_history,
                     save_portfolio, save_uploaded_file, save_valuation_snapshot)


def test_save_and_load_portfolio_round_trip(tmp_path):
    path = tmp_path / "portfolio.json"
    original = pd.DataFrame([{"instrument": "Test ETF", "isin": "TEST", "category": "Core",
                              "quantity": 2, "manual_current_price": 50, "current_value_eur": 100,
                              "buy_in_value_eur": 90, "fractional_allowed": False}])
    save_portfolio(original, path)
    loaded = load_portfolio(path)
    assert loaded.loc[0, "instrument"] == "Test ETF"
    assert loaded.loc[0, "current_value_eur"] == 100
    assert loaded.loc[0, "direct_trading_allowed"]


def test_load_uses_fallback_when_file_is_missing(tmp_path):
    loaded = load_portfolio(tmp_path / "missing.json", fallback=[{"instrument": "Cash", "category": "Cash", "current_value_eur": 10}])
    assert loaded.loc[0, "current_value_eur"] == 10


def test_uploaded_file_is_saved_locally_with_safe_name(tmp_path):
    saved = save_uploaded_file("../private screenshot.png", b"image bytes", tmp_path)
    assert saved.parent == tmp_path
    assert saved.name == "private_screenshot.png"
    assert saved.read_bytes() == b"image bytes"


def test_daily_snapshot_replaces_same_day_and_can_be_cleared(tmp_path):
    path = tmp_path / "valuation_history.csv"
    first = {"date": "2026-06-19", "timestamp": "2026-06-19T09:00:00+02:00", "total_value_eur": 100}
    second = {"date": "2026-06-19", "timestamp": "2026-06-19T18:00:00+02:00", "total_value_eur": 110}
    save_valuation_snapshot(first, path)
    save_valuation_snapshot(second, path)
    history = load_valuation_history(path)
    assert len(history) == 1
    assert history.loc[0, "total_value_eur"] == 110
    clear_valuation_history(path)
    assert load_valuation_history(path).empty
