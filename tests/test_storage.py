import pandas as pd

from storage import load_portfolio, save_portfolio, save_uploaded_file


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
