import pandas as pd
from streamlit.testing.v1 import AppTest


class FakeDatabase:
    def __init__(self, gateway, user_id): pass
    def load_holdings(self): return pd.DataFrame()
    def load_candidates(self): return pd.DataFrame()
    def load_savings_plans(self): return pd.DataFrame()
    def load_settings(self): return {}
    def load_snapshots(self): return pd.DataFrame()
    def load_strategy_snapshots(self): return pd.DataFrame()
    def save_holdings(self, *args): pass
    def save_candidates(self, *args): pass
    def save_savings_plans(self, *args): pass


def test_authenticated_portfolio_page_starts_without_paid_keys(monkeypatch):
    import db
    import supabase_client
    monkeypatch.setattr(db, "Database", FakeDatabase)
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda user_id: object())
    monkeypatch.setattr(supabase_client, "SupabaseGateway", lambda client: object())
    app = AppTest.from_file("app.py")
    app.secrets = {"APP_PASSWORD": "test", "SUPABASE_URL": "https://example.supabase.co",
                   "SUPABASE_ANON_KEY": "anon"}
    app.run(timeout=30)
    app.text_input(key="login_password").input("test")
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert app.radio[0].options == ["Portfolio", "Market", "Strategy", "Rebalance", "Settings"]
    assert "Quick Refresh Prices" in [button.label for button in app.button]
    for section in ["Market", "Strategy", "Rebalance", "Settings"]:
        app.radio[0].set_value(section).run(timeout=30)
        assert not app.exception, section
        labels = [button.label for button in app.button]
        if section == "Market":
            assert {"Quick Refresh Prices", "Repair Missing Symbols", "Run Deep Data Scan"}.issubset(labels)
        if section == "Rebalance":
            assert "Run Full Rebalance" in labels
