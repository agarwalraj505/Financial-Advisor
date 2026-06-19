"""Database payload mapping and user-scoped repositories."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from rebalancer import holdings_to_dataframe
from sample_data import CANDIDATE_COLUMNS


def clean_value(value):
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _payload(row: dict | pd.Series, mapping: dict[str, str], user_id: str) -> dict:
    source = row.to_dict() if isinstance(row, pd.Series) else dict(row)
    result = {"user_id": user_id}
    for app_name, db_name in mapping.items():
        if app_name in source:
            value = clean_value(source[app_name])
            if db_name in {"last_updated", "inception_date", "timestamp", "snapshot_date"} and value == "":
                value = None
            result[db_name] = value
    return result


HOLDING_MAP = {"instrument": "instrument", "isin": "isin", "ticker_id": "ticker_id",
    "price_symbol": "price_symbol", "asset_type": "asset_type", "category": "category", "theme": "theme",
    "region": "region", "currency": "currency", "quantity": "quantity",
    "manual_current_price": "manual_current_price", "live_current_price": "live_current_price",
    "price_source": "price_source", "fx_rate_to_eur": "fx_rate_to_eur",
    "current_value_eur": "current_value_eur", "buy_in_value_eur": "buy_in_value_eur",
    "pl_eur": "pl_eur", "pl_pct": "pl_percent", "direct_trading_allowed": "direct_trading_allowed",
    "fractional_allowed": "fractional_allowed", "notes": "notes"}

CANDIDATE_MAP = {"instrument": "instrument", "isin": "isin", "ticker_id": "ticker_id",
    "price_symbol": "price_symbol", "asset_type": "asset_type", "category": "category", "theme": "theme",
    "region": "region", "currency": "currency", "ter_pct": "ter_percent", "fund_size_eur": "fund_size_eur",
    "replication_method": "replication_method", "distribution_policy": "distribution_policy",
    "domicile": "domicile", "savings_plan_available": "savings_plan_available",
    "direct_trading_available": "direct_trading_available", "fractional_allowed": "fractional_allowed",
    "scalable_compatible": "scalable_compatible", "preferred_venue": "preferred_venue",
    "manual_spread_estimate_pct": "manual_spread_estimate_percent", "liquidity_score": "liquidity_score",
    "quality_score": "quality_score", "momentum_score": "momentum_score", "valuation_score": "valuation_score",
    "cost_score": "cost_score", "portfolio_fit_score": "portfolio_fit_score",
    "risk_control_score": "risk_control_score", "total_score": "total_score", "data_source": "data_source",
    "source_url": "source_url", "data_confidence": "data_confidence", "last_updated": "last_updated",
    "notes": "notes", "overlap_score": "overlap_score", "tracking_quality_score": "tracking_quality_score",
    "inception_date": "inception_date", "revenue_growth_score": "revenue_growth_score",
    "earnings_quality_score": "earnings_quality_score", "valuation_fundamental_score": "valuation_fundamental_score",
    "profitability_score": "profitability_score", "balance_sheet_score": "balance_sheet_score"}

SAVINGS_MAP = {"instrument": "instrument", "isin": "isin", "current_plan": "current_plan_eur",
               "new_plan": "new_plan_eur", "action": "action", "reason": "reason", "score": "score"}

SNAPSHOT_MAP = {"date": "snapshot_date", "timestamp": "timestamp", "total_value_eur": "total_value_eur",
    "cash_eur": "cash_eur", "invested_value_eur": "invested_value_eur", "unrealized_pl_eur": "unrealized_pl_eur",
    "daily_gain_eur": "daily_gain_eur", "daily_gain_pct": "daily_gain_percent",
    "weekly_gain_eur": "weekly_gain_eur", "weekly_gain_pct": "weekly_gain_percent",
    "monthly_gain_eur": "monthly_gain_eur", "monthly_gain_pct": "monthly_gain_percent",
    "yearly_gain_eur": "yearly_gain_eur", "yearly_gain_pct": "yearly_gain_percent"}

RECOMMENDATION_MAP = {"Action": "action", "Purpose": "purpose", "Instrument": "instrument",
    "ISIN": "isin", "Ticker/ID": "ticker_id", "Quantity": "quantity", "Est. value": "estimated_value_eur",
    "Fee issue": "fee_issue", "Score": "score", "Data confidence": "data_confidence", "Reason": "reason",
    "Step": "execution_order"}


def holding_to_payload(row, user_id): return _payload(row, HOLDING_MAP, user_id)
def candidate_to_payload(row, user_id): return _payload(row, CANDIDATE_MAP, user_id)
def savings_to_payload(row, user_id): return _payload(row, SAVINGS_MAP, user_id)
def snapshot_to_payload(row, user_id): return _payload(row, SNAPSHOT_MAP, user_id)
def recommendation_to_payload(row, user_id): return _payload(row, RECOMMENDATION_MAP, user_id)


def _from_db(rows: list[dict], reverse_mapping: dict[str, str]) -> pd.DataFrame:
    reverse = {db_name: app_name for app_name, db_name in reverse_mapping.items()}
    return pd.DataFrame([{reverse.get(key, key): value for key, value in row.items()
                          if key not in {"id", "user_id", "created_at", "updated_at"}} for row in rows])


class Database:
    def __init__(self, gateway, user_id: str):
        self.gateway, self.user_id = gateway, user_id

    def load_holdings(self) -> pd.DataFrame:
        frame = _from_db(self.gateway.select("holdings", {"user_id": self.user_id}, order="created_at"), HOLDING_MAP)
        return holdings_to_dataframe(frame.to_dict("records")) if not frame.empty else frame

    def save_holdings(self, frame: pd.DataFrame) -> None:
        self.gateway.replace_user_rows("holdings", self.user_id,
                                       [holding_to_payload(row, self.user_id) for _, row in frame.iterrows()])

    def load_candidates(self) -> pd.DataFrame:
        frame = _from_db(self.gateway.select("candidate_assets", {"user_id": self.user_id}, order="instrument"), CANDIDATE_MAP)
        for column in CANDIDATE_COLUMNS:
            if column not in frame:
                frame[column] = None
        return frame[CANDIDATE_COLUMNS] if not frame.empty else frame

    def save_candidates(self, frame: pd.DataFrame) -> None:
        self.gateway.replace_user_rows("candidate_assets", self.user_id,
                                       [candidate_to_payload(row, self.user_id) for _, row in frame.iterrows()])

    def load_savings_plans(self) -> pd.DataFrame:
        return _from_db(self.gateway.select("savings_plans", {"user_id": self.user_id}, order="instrument"), SAVINGS_MAP)

    def save_savings_plans(self, frame: pd.DataFrame) -> None:
        self.gateway.replace_user_rows("savings_plans", self.user_id,
                                       [savings_to_payload(row, self.user_id) for _, row in frame.iterrows()])

    def load_snapshots(self) -> pd.DataFrame:
        return _from_db(self.gateway.select("valuation_snapshots", {"user_id": self.user_id},
                                            order="timestamp"), SNAPSHOT_MAP)

    def save_snapshot(self, row: dict) -> None:
        self.gateway.upsert("valuation_snapshots", snapshot_to_payload(row, self.user_id),
                            on_conflict="user_id,snapshot_date")

    def clear_snapshots(self) -> None:
        self.gateway.delete("valuation_snapshots", {"user_id": self.user_id})

    def save_recommendations(self, report: pd.DataFrame) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = []
        for index, row in report.iterrows():
            payload = recommendation_to_payload(row, self.user_id)
            payload["created_at"] = now
            step = clean_value(row.get("Step", index + 1))
            payload["execution_order"] = int(step if step is not None else index + 1)
            rows.append(payload)
        self.gateway.insert("recommendations", rows)

    def load_recommendations(self) -> pd.DataFrame:
        return _from_db(self.gateway.select("recommendations", {"user_id": self.user_id},
                                            order="created_at", desc=True), RECOMMENDATION_MAP)

    def load_settings(self) -> dict[str, Any]:
        rows = self.gateway.select("app_settings", {"user_id": self.user_id})
        return {row["setting_key"]: row["setting_value"] for row in rows}

    def save_settings(self, settings: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [{"user_id": self.user_id, "setting_key": key, "setting_value": clean_value(value),
                 "updated_at": now} for key, value in settings.items()]
        self.gateway.upsert("app_settings", rows, on_conflict="user_id,setting_key")
