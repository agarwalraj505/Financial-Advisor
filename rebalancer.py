"""Explainable portfolio calculations. No broker connections or trade execution."""

from __future__ import annotations

from math import floor
from typing import Iterable
from copy import deepcopy

import pandas as pd
from pydantic import BaseModel, Field

MIN_EFFICIENT_ORDER_EUR = 250.0
MATERIAL_DRIFT_PCT = 3.0
ON_TARGET_DRIFT_PCT = 1.0
HOLDING_COLUMNS = ["instrument", "isin", "ticker_id", "price_symbol", "asset_type", "category", "theme", "region", "quantity",
                   "manual_current_price", "live_current_price", "price_source", "currency", "fx_rate_to_eur",
                   "current_value_eur", "buy_in_value_eur", "pl_eur", "pl_pct",
                   "direct_trading_allowed", "fractional_allowed", "notes", "wkn", "current_price_eur",
                   "buy_in_price_eur", "sell_price_eur", "buy_price_eur", "spread_eur", "spread_percent",
                   "screenshot_path", "screenshot_captured_at", "source", "user_confirmed",
                   "valuation_ready", "recommendation_ready", "valuation_review_reasons",
                   "recommendation_review_reasons", "provider_status", "enrichment_audit", "web_scrape_status",
                   "web_scrape_last_run", "web_scrape_sources", "web_scrape_confidence", "factsheet_url",
                   "kid_url", "issuer", "metadata_conflicts", "enrichment_suggestions", "confirmed_by_user",
                   "suggested_price_symbols", "suggested_asset_type", "suggested_category",
                   "manual_review_attempted", "last_auto_repair_at", "ter_pct", "fund_size_eur",
                   "replication_method", "distribution_policy", "domicile",
                   "manual_spread_estimate_pct", "last_updated", "selected_price", "price_stale",
                   "fx_source", "pl_percent", "previous_close", "daily_gain_eur", "daily_gain_pct",
                   "daily_gain_percent", "price_error", "resolved_price_symbol", "data_source", "source_url",
                   "data_confidence", "exchange"]


class Holding(BaseModel):
    instrument: str = ""
    isin: str = ""
    ticker_id: str = ""
    price_symbol: str = ""
    asset_type: str = "ETF"
    category: str = "Core"
    theme: str = ""
    region: str = ""
    quantity: float = Field(default=0, ge=0)
    manual_current_price: float = Field(default=0, ge=0)
    live_current_price: float = Field(default=0, ge=0)
    price_source: str = "Manual fallback"
    currency: str = "EUR"
    fx_rate_to_eur: float = Field(default=1, ge=0)
    current_value_eur: float = Field(default=0, ge=0)
    buy_in_value_eur: float = Field(default=0, ge=0)
    pl_eur: float = 0
    pl_pct: float = 0
    direct_trading_allowed: bool = True
    fractional_allowed: bool = False
    notes: str = ""


class SavingsPlan(BaseModel):
    instrument: str
    isin: str = ""
    category: str
    current_plan: float = Field(ge=0)


def _normalise_holdings(data: pd.DataFrame) -> pd.DataFrame:
    """Return a canonical frame while accepting the old prototype schema."""
    frame = data.copy()
    aliases = {"value": "current_value_eur", "current_value": "current_value_eur",
               "current_price": "manual_current_price", "buy_in_value": "buy_in_value_eur",
               "allows_fractional": "fractional_allowed"}
    for old, new in aliases.items():
        if new not in frame and old in frame:
            frame[new] = frame[old]
    defaults = {"instrument": "", "isin": "", "ticker_id": "", "price_symbol": "", "asset_type": "ETF",
                "theme": "", "region": "",
                "category": "Uncategorised", "quantity": 0.0, "manual_current_price": 0.0,
                "live_current_price": 0.0, "price_source": "Manual fallback", "currency": "EUR",
                "fx_rate_to_eur": 1.0, "current_value_eur": 0.0, "buy_in_value_eur": 0.0,
                "pl_eur": 0.0, "pl_pct": 0.0,
                "direct_trading_allowed": True, "fractional_allowed": False, "notes": "",
                "wkn": "", "current_price_eur": 0.0, "buy_in_price_eur": 0.0, "sell_price_eur": 0.0,
                "buy_price_eur": 0.0, "spread_eur": 0.0, "spread_percent": 0.0, "screenshot_path": "",
                "screenshot_captured_at": "", "source": "", "user_confirmed": False,
                "valuation_ready": False, "recommendation_ready": False, "valuation_review_reasons": "",
                "recommendation_review_reasons": "", "provider_status": [], "enrichment_audit": [],
                "web_scrape_status": "", "web_scrape_last_run": "", "web_scrape_sources": [],
                "web_scrape_confidence": "", "factsheet_url": "", "kid_url": "", "issuer": "",
                "metadata_conflicts": {}, "enrichment_suggestions": {}, "confirmed_by_user": False,
                "suggested_price_symbols": [], "suggested_asset_type": "", "suggested_category": "",
                "manual_review_attempted": False, "last_auto_repair_at": "", "ter_pct": None,
                "fund_size_eur": None, "replication_method": "", "distribution_policy": "",
                "domicile": "", "manual_spread_estimate_pct": None, "last_updated": ""}
    defaults.update({"selected_price": 0.0, "price_stale": False, "fx_source": "",
                     "pl_percent": 0.0, "previous_close": 0.0, "daily_gain_eur": 0.0,
                     "daily_gain_pct": 0.0, "daily_gain_percent": 0.0, "price_error": "",
                     "resolved_price_symbol": "", "data_source": "", "source_url": "",
                     "data_confidence": "", "exchange": ""})
    for column, default in defaults.items():
        if column not in frame:
            frame[column] = ([deepcopy(default) for _ in range(len(frame))]
                             if isinstance(default, (dict, list)) else default)
    string_columns = ["instrument", "isin", "ticker_id", "price_symbol", "asset_type", "category", "theme", "region",
                      "price_source", "currency", "notes", "wkn", "screenshot_path", "screenshot_captured_at",
                      "source", "valuation_review_reasons", "recommendation_review_reasons", "web_scrape_status",
                      "web_scrape_last_run", "web_scrape_confidence", "factsheet_url", "kid_url", "issuer",
                      "suggested_asset_type", "suggested_category", "last_auto_repair_at",
                      "replication_method", "distribution_policy", "domicile", "last_updated"]
    string_columns += ["fx_source", "price_error"]
    string_columns += ["resolved_price_symbol", "data_source", "source_url", "data_confidence", "exchange"]
    for column in string_columns:
        frame[column] = frame[column].fillna("").astype(str)
    frame["currency"] = frame["currency"].replace("", "EUR")
    frame["price_source"] = frame["price_source"].replace("", "Manual fallback")
    for column, default in (("direct_trading_allowed", True), ("fractional_allowed", False),
                            ("user_confirmed", False), ("valuation_ready", False),
                            ("recommendation_ready", False), ("confirmed_by_user", False),
                            ("manual_review_attempted", False), ("price_stale", False)):
        frame[column] = frame[column].fillna(default).astype(bool)
    for column in ["quantity", "manual_current_price", "live_current_price", "fx_rate_to_eur",
                   "current_value_eur", "buy_in_value_eur", "pl_eur", "pl_pct", "current_price_eur",
                   "buy_in_price_eur", "sell_price_eur", "buy_price_eur", "spread_eur", "spread_percent"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    for column in ["selected_price", "pl_percent", "previous_close", "daily_gain_eur",
                   "daily_gain_pct", "daily_gain_percent"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    for column in ["ter_pct", "fund_size_eur", "manual_spread_estimate_pct"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    missing_price = (frame["manual_current_price"] <= 0) & (frame["quantity"] > 0)
    frame.loc[missing_price, "manual_current_price"] = frame.loc[missing_price, "current_value_eur"] / frame.loc[missing_price, "quantity"]
    return frame[HOLDING_COLUMNS]


def holdings_to_dataframe(holdings: Iterable[dict | Holding]) -> pd.DataFrame:
    records = [item.model_dump() if isinstance(item, Holding) else dict(item) for item in holdings]
    return _normalise_holdings(pd.DataFrame(records))


def savings_plans_to_dataframe(plans: Iterable[dict | SavingsPlan]) -> pd.DataFrame:
    return pd.DataFrame([SavingsPlan.model_validate(item).model_dump() for item in plans])


def calculate_total_value(holdings_df: pd.DataFrame) -> float:
    return round(float(_normalise_holdings(holdings_df)["current_value_eur"].sum()), 2)


def calculate_total_invested(holdings_df: pd.DataFrame) -> float:
    return round(float(_normalise_holdings(holdings_df)["buy_in_value_eur"].sum()), 2)


def calculate_unrealised_pl(holdings_df: pd.DataFrame) -> float:
    frame = _normalise_holdings(holdings_df)
    return round(float(frame["current_value_eur"].sum() - frame["buy_in_value_eur"].sum()), 2)


def calculate_allocation(holdings_df: pd.DataFrame) -> pd.DataFrame:
    frame = _normalise_holdings(holdings_df)
    total = float(frame["current_value_eur"].sum())
    grouped = frame.groupby("category", as_index=False)["current_value_eur"].sum()
    grouped["current_weight"] = 0.0 if total == 0 else grouped["current_value_eur"] / total * 100
    return grouped.rename(columns={"current_value_eur": "value"}).sort_values("category").reset_index(drop=True)


def calculate_drift(holdings_df: pd.DataFrame, targets: dict[str, float]) -> pd.DataFrame:
    total = calculate_total_value(holdings_df)
    allocation = calculate_allocation(holdings_df)
    target_df = pd.DataFrame([{"category": k, "target_weight": v} for k, v in targets.items()])
    drift = target_df.merge(allocation, on="category", how="left").fillna({"value": 0, "current_weight": 0})
    drift["target_value"] = total * drift["target_weight"] / 100
    drift["drift_pct_points"] = drift["current_weight"] - drift["target_weight"]
    drift["drift_eur"] = drift["value"] - drift["target_value"]
    drift["status"] = drift["drift_pct_points"].map(classify_drift)
    return drift[["category", "value", "current_weight", "target_weight", "target_value",
                  "drift_pct_points", "drift_eur", "status"]].round(2)


def classify_drift(drift: float) -> str:
    if drift > ON_TARGET_DRIFT_PCT:
        return "Overweight"
    if drift < -ON_TARGET_DRIFT_PCT:
        return "Underweight"
    return "On target"


def fee_warning(order_value: float, threshold: float = MIN_EFFICIENT_ORDER_EUR) -> str:
    if abs(order_value) == 0:
        return "No order"
    if abs(order_value) < threshold:
        return f"Below €{threshold:,.0f}: €0.99 buy + €0.99 sell = €1.98 round trip"
    return f"€{threshold:,.0f}+: fees can usually be avoided with PRIME+ on EIX/gettex; verify first"


def _representative(frame: pd.DataFrame, category: str) -> pd.Series | None:
    rows = frame[(frame["category"] == category) & (frame["isin"] != "CASH")]
    rows = rows[rows["direct_trading_allowed"]]
    return None if rows.empty else rows.sort_values("current_value_eur", ascending=False).iloc[0]


def _hold_row(category: str, value: float, reason: str, fee_threshold: float = MIN_EFFICIENT_ORDER_EUR) -> dict:
    return {"Action": "Hold / adjust via savings plan", "Purpose": "Manage impractical drift",
            "Instrument": category, "ISIN": "", "Ticker/ID": "", "Quantity": 0,
            "Est. value": round(value, 2), "Fee issue": fee_warning(value, fee_threshold), "Reason": reason}


def generate_rebalance_trades(holdings_df: pd.DataFrame, drift_df: pd.DataFrame,
                              fee_threshold: float = MIN_EFFICIENT_ORDER_EUR) -> pd.DataFrame:
    """Create conservative manual trade ideas, funding sells before prioritized buys."""
    frame = _normalise_holdings(holdings_df)
    columns = ["Action", "Purpose", "Instrument", "ISIN", "Ticker/ID", "Quantity", "Est. value", "Fee issue", "Reason"]
    cash = float(frame.loc[frame["category"] == "Cash", "current_value_eur"].sum())
    rows: list[dict] = []
    candidates = drift_df[(drift_df["category"] != "Cash") & (drift_df["drift_pct_points"].abs() > MATERIAL_DRIFT_PCT)].copy()
    candidates["_side"] = candidates["status"].map({"Overweight": 0, "Underweight": 1}).fillna(2)
    candidates = candidates.sort_values(["_side", "drift_eur"], ascending=[True, True])
    for _, drift in candidates.iterrows():
        category, needed = str(drift["category"]), abs(float(drift["drift_eur"]))
        holding = _representative(frame, category)
        if holding is None:
            rows.append(_hold_row(category, needed, "No directly tradable instrument is available in this category.", fee_threshold))
            continue
        price = float(holding["live_current_price"] or holding["manual_current_price"]) * float(holding["fx_rate_to_eur"])
        fractional = bool(holding["fractional_allowed"])
        quantity = needed / price if fractional and price > 0 else floor(needed / price) if price > 0 else 0
        value = quantity * price
        if value <= 0:
            rows.append(_hold_row(category, needed, "The drift is smaller than one whole unit.", fee_threshold))
            continue
        action = "Sell" if drift["status"] == "Overweight" else "Buy"
        if value < fee_threshold:
            rows.append(_hold_row(category, value, f"A direct order is below €{fee_threshold:,.0f}; prefer savings-plan changes.", fee_threshold))
            continue
        if action == "Buy" and value > cash:
            affordable_qty = cash / price if fractional else floor(cash / price)
            affordable_value = affordable_qty * price
            if affordable_value < fee_threshold:
                rows.append(_hold_row(category, value, "Cash is insufficient; reduce this lower-priority buy first.", fee_threshold))
                continue
            quantity, value = affordable_qty, affordable_value
        reason = ("Optional sale of a material overweight; consider tax and spread." if action == "Sell"
                  else "Material underweight funded by available cash; prefer EIX/gettex.")
        cash = cash + value if action == "Sell" else cash - value
        rows.append({"Action": action, "Purpose": f"Reduce {drift['status'].lower()}",
                     "Instrument": holding["instrument"], "ISIN": holding["isin"], "Ticker/ID": holding["ticker_id"],
                     "Quantity": round(quantity, 6) if fractional else int(quantity), "Est. value": round(value, 2),
                     "Fee issue": fee_warning(value, fee_threshold), "Reason": reason})
    return pd.DataFrame(rows, columns=columns)


def execution_order(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame(columns=["Step", "Action", "Instrument", "Est. value", "Reason"])
    ordered = trades_df.assign(_priority=trades_df["Action"].map({"Sell": 1, "Buy": 2}).fillna(3))
    ordered = ordered.sort_values(["_priority", "Est. value"], ascending=[True, False]).reset_index(drop=True)
    ordered.insert(0, "Step", ordered.index + 1)
    return ordered[["Step", "Action", "Instrument", "Est. value", "Reason"]]


def recommend_savings_plans(plans_df: pd.DataFrame, drift_df: pd.DataFrame) -> pd.DataFrame:
    statuses = drift_df.set_index("category")["status"].to_dict()
    rows = []
    for _, plan in plans_df.iterrows():
        current, status = float(plan["current_plan"]), statuses.get(plan["category"], "On target")
        new = current * 1.25 if status == "Underweight" else current * 0.5 if status == "Overweight" else current
        action = ("Increase toward underweight category" if status == "Underweight" else
                  "Reduce or pause while overweight" if status == "Overweight" else "Keep unchanged")
        rows.append({"Instrument": plan["instrument"], "ISIN": plan["isin"], "Current plan": round(current, 2),
                     "New plan": round(new, 2), "Action": action})
    return pd.DataFrame(rows)


def allocation_table(drift_df: pd.DataFrame) -> pd.DataFrame:
    return drift_df[["category", "current_weight", "target_weight", "status"]].rename(columns={
        "category": "Category", "current_weight": "Current weight", "target_weight": "Target weight", "status": "Status"})
