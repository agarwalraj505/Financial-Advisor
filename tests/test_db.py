import math

import pandas as pd

from db import (Database, candidate_to_payload, delete_candidate_asset, delete_holding,
                get_candidate_assets, get_holdings, get_recommendations, get_savings_plans,
                get_settings, get_valuation_snapshots, holding_to_payload,
                insert_recommendations, insert_valuation_snapshot, recommendation_to_payload,
                snapshot_to_payload, upsert_candidate_asset, upsert_holding, upsert_savings_plan,
                upsert_setting)


def test_holding_payload_maps_app_columns_and_removes_nan():
    payload = holding_to_payload({"instrument": "ETF", "isin": "TEST", "pl_pct": 12.5,
                                  "quantity": 2, "manual_current_price": math.nan}, "user-1")
    assert payload["user_id"] == "user-1"
    assert payload["pl_percent"] == 12.5
    assert payload["manual_current_price"] is None
    assert "pl_pct" not in payload


def test_candidate_payload_uses_database_column_names():
    payload = candidate_to_payload({"instrument": "Fund", "ter_pct": .2,
                                    "manual_spread_estimate_pct": .1,
                                    "last_updated": ""}, "user-1")
    assert payload["ter_percent"] == .2
    assert payload["manual_spread_estimate_percent"] == .1
    assert payload["last_updated"] is None


def test_snapshot_and_recommendation_payloads():
    snapshot = snapshot_to_payload({"date": "2026-06-19", "daily_gain_pct": 1.2}, "u")
    recommendation = recommendation_to_payload({"Action": "Buy new asset", "Est. value": 300,
                                                 "Data confidence": "High", "Step": 2}, "u")
    assert snapshot == {"user_id": "u", "snapshot_date": "2026-06-19", "daily_gain_percent": 1.2}
    assert recommendation["estimated_value_eur"] == 300
    assert recommendation["execution_order"] == 2


class FakeGateway:
    def __init__(self):
        self.tables = {"holdings": [], "candidate_assets": [], "savings_plans": [],
                       "valuation_snapshots": [], "recommendations": [], "app_settings": []}
        self.replacements = []
        self.upserts = []
        self.inserts = []

    def select(self, table, filters=None, columns="*", order=None, desc=False):
        return [row for row in self.tables[table] if not filters or all(row.get(k) == v for k, v in filters.items())]

    def replace_user_rows(self, table, user_id, rows):
        self.replacements.append((table, user_id, rows))

    def upsert(self, table, rows, on_conflict):
        self.upserts.append((table, rows, on_conflict))

    def insert(self, table, rows):
        self.inserts.append((table, rows))

    def delete(self, table, filters):
        self.tables[table] = [row for row in self.tables[table]
                              if not all(row.get(k) == v for k, v in filters.items())]


def test_database_scopes_saves_and_reads_to_user():
    gateway = FakeGateway()
    gateway.tables["holdings"] = [
        {"user_id": "mine", "instrument": "Mine", "category": "Core", "current_value_eur": 100},
        {"user_id": "other", "instrument": "Other", "category": "Core", "current_value_eur": 999}]
    database = Database(gateway, "mine")
    loaded = database.load_holdings()
    assert loaded["instrument"].tolist() == ["Mine"]
    database.save_holdings(pd.DataFrame([{"instrument": "Saved", "category": "Cash", "current_value_eur": 50}]))
    table, user_id, rows = gateway.replacements[0]
    assert table == "holdings" and user_id == "mine"
    assert rows[0]["user_id"] == "mine"


def test_settings_are_upserted_as_json_values():
    gateway = FakeGateway()
    database = Database(gateway, "mine")
    database.save_settings({"monthly_savings_budget": 300, "target_allocations": {"Core": 25}})
    table, rows, conflict = gateway.upserts[0]
    assert table == "app_settings"
    assert conflict == "user_id,setting_key"
    assert {row["setting_key"] for row in rows} == {"monthly_savings_budget", "target_allocations"}


def test_required_database_helper_api_is_available():
    helpers = [get_holdings, upsert_holding, delete_holding, get_candidate_assets,
               upsert_candidate_asset, delete_candidate_asset, get_savings_plans,
               upsert_savings_plan, get_valuation_snapshots, insert_valuation_snapshot,
               get_recommendations, insert_recommendations, get_settings, upsert_setting]
    assert all(callable(helper) for helper in helpers)
