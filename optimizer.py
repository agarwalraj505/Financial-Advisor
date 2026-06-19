"""Conservative, explainable portfolio recommendation engine."""

from __future__ import annotations

from math import floor
from datetime import datetime, timezone

import pandas as pd

from scoring import allocation_bucket

OUTPUT_COLUMNS = ["Action", "Purpose", "Instrument", "ISIN", "Ticker/ID", "Quantity",
                  "Est. value", "Fee issue", "Score", "Data confidence", "Reason",
                  "Price source", "Metadata source", "News/sentiment input", "Last updated",
                  "Scalable execution warning", "Data source", "Timestamp", "Execution note"]


def _number(value, default=0.0):
    try:
        return default if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return default


def _fee_issue(value: float, minimum: float, fee: float) -> str:
    return (f"Below €{minimum:,.0f}; prefer savings plan. Assumed round trip €{fee:.2f}"
            if 0 < value < minimum else "PRIME+ EIX/gettex fee may be avoided; verify manually" if value >= minimum else "No order")


def _row(action: str, purpose: str, asset: pd.Series, quantity: float, value: float,
         reason: str, settings: dict) -> dict:
    fractional = bool(asset.get("fractional_allowed", False))
    return {"Action": action, "Purpose": purpose, "Instrument": asset.get("instrument", ""),
            "ISIN": asset.get("isin", ""), "Ticker/ID": asset.get("ticker_id", ""),
            "Quantity": round(quantity, 6) if fractional else int(quantity), "Est. value": round(value, 2),
            "Fee issue": _fee_issue(value, settings["direct_trade_minimum"], settings["small_trade_round_trip_fee"]),
            "Score": round(_number(asset.get("total_score")), 2),
            "Data confidence": asset.get("data_confidence", "Low"), "Reason": reason,
            "Price source": asset.get("price_source") or asset.get("data_source") or "Manual fallback after failed enrichment",
            "Metadata source": asset.get("source_url") or asset.get("issuer") or asset.get("data_source") or "Pending confirmation",
            "News/sentiment input": settings.get("news_sentiment", "Neutral / no material evidence"),
            "Last updated": asset.get("last_updated") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "Scalable execution warning": "Check live Scalable price before execution",
            "Data source": asset.get("data_source") or "Manual fallback after failed enrichment",
            "Timestamp": asset.get("last_updated") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "Execution note": "Check live Scalable price before execution"}


def generate_market_aware_recommendations(current: pd.DataFrame, candidates: pd.DataFrame,
                                          drift: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Recommend sells/holds first, then cash-limited adds and new buys."""
    minimum = float(settings.get("direct_trade_minimum", 250))
    configured = {"direct_trade_minimum": minimum,
                  "small_trade_round_trip_fee": float(settings.get("small_trade_round_trip_fee", 1.98)),
                  "news_sentiment": settings.get("news_sentiment", "Neutral / no material evidence")}
    drift_lookup = drift.set_index("category").to_dict("index") if not drift.empty else {}
    cash = float(settings.get("available_cash_eur", 0))
    rows, owned_isins = [], set(current.get("isin", pd.Series(dtype=str)).astype(str))

    for _, asset in current.iterrows():
        if str(asset.get("category", "")) == "Cash":
            continue
        score = _number(asset.get("total_score"))
        category_data = drift_lookup.get(allocation_bucket(str(asset.get("category", ""))), {})
        drift_eur, status = _number(category_data.get("drift_eur")), category_data.get("status", "On target")
        value, quantity = _number(asset.get("current_value_eur")), _number(asset.get("quantity"))
        price = value / quantity if quantity else 0
        ready = bool(asset.get("recommendation_ready", not bool(asset.get("manual_review_required", False))))
        if status == "Overweight" and score < 6.5 and value > 0 and ready:
            sell_value = min(value, max(abs(drift_eur), minimum))
            sell_qty = sell_value / price if bool(asset.get("fractional_allowed", False)) and price else floor(sell_value / price) if price else 0
            sell_value = sell_qty * price
            action = "Sell fully" if sell_qty >= quantity else "Sell partially"
            rows.append(_row(action, "Reduce weak overweight holding", asset, min(sell_qty, quantity), min(sell_value, value),
                             "Weak score combined with an overweight category; sale remains optional and tax-sensitive.", configured))
            cash += min(sell_value, value)
        elif status == "Underweight" and score >= 8:
            rows.append(_row("Hold / consider add", "Strong holding in underweight category", asset, 0, 0,
                             "Strong setup, but compare with higher-scoring candidates before adding.", configured))
        else:
            reason = "No clearly superior risk/reward setup justifies a forced trade."
            if not ready:
                reason = "Hold, but complete cost review; manual review remains required. " + str(
                    asset.get("recommendation_review_reasons", "Metadata needs review."))
            rows.append(_row("Hold", "Maintain current position", asset, 0, 0, reason, configured))

    eligible = candidates.sort_values("total_score", ascending=False) if not candidates.empty else candidates
    for _, asset in eligible.iterrows():
        if str(asset.get("isin", "")) in owned_isins:
            continue
        category_data = drift_lookup.get(allocation_bucket(str(asset.get("category", ""))), {})
        underweight = category_data.get("status") == "Underweight"
        score = _number(asset.get("total_score"))
        critical = not bool(asset.get("recommendation_ready", not bool(asset.get("manual_review_required", False))))
        if critical:
            attempted = bool(asset.get("manual_review_attempted", False))
            purpose = "Manual review required" if attempted else "Data enrichment required"
            reason = ("All enabled enrichment routes were attempted; unresolved critical data keeps this asset on the watchlist."
                      if attempted else "Run the Market Data Engine before considering this candidate for buy/add.")
            rows.append(_row("No trade", purpose, asset, 0, 0, reason, configured))
            continue
        scalable = bool(asset.get("scalable_compatible", False))
        direct_available = bool(asset.get("direct_trading_available", False))
        if not scalable:
            rows.append(_row("No trade / watchlist", "Compatibility confirmation required", asset, 0, 0,
                             "Scalable compatibility is not confirmed; verify availability manually.", configured))
            continue
        if score < 8 or not underweight:
            if score >= 6.5:
                rows.append(_row("No trade / watchlist", "Monitor candidate", asset, 0, 0,
                                 "Score is watchlist-level or its category is not underweight.", configured))
            continue
        price = _number(asset.get("latest_price_eur")) or _number(asset.get("latest_price")) * _number(asset.get("fx_rate_to_eur"), 1)
        desired = min(abs(_number(category_data.get("drift_eur"))), cash)
        portfolio_total = _number(settings.get("portfolio_total_eur"), 0)
        if portfolio_total:
            desired = min(desired, portfolio_total * _number(settings.get("max_single_holding_weight"), 25) / 100)
        if str(asset.get("category", "")) == "Crypto" and portfolio_total:
            crypto_room = (portfolio_total * _number(settings.get("max_crypto_weight"), 5) / 100 -
                           _number(settings.get("current_crypto_value_eur"), 0))
            desired = min(desired, max(0, crypto_room))
        fractional = bool(asset.get("fractional_allowed", False))
        quantity = desired / price if fractional and price else floor(desired / price) if price else 0
        value = quantity * price
        if not direct_available:
            action = "Add to savings plan" if bool(asset.get("savings_plan_available", False)) else "No trade"
            rows.append(_row(action, "No confirmed direct-trading route", asset, 0, value,
                             "Direct trading is unavailable or unconfirmed; verify Scalable eligibility.", configured))
            continue
        if value < minimum:
            if bool(asset.get("savings_plan_available", False)):
                rows.append(_row("Add to savings plan", "Fee-efficient new exposure", asset, 0, value,
                                 "High-scoring underweight exposure, but direct trade size is below the configured minimum.", configured))
            else:
                rows.append(_row("No trade", "Fee-inefficient setup", asset, 0, value,
                                 "Available cash cannot fund a fee-efficient direct order.", configured))
            continue
        rows.append(_row("Buy new asset", "Improve underweight allocation", asset, quantity, value,
                         "High score, complete critical data, and useful exposure to an underweight category.", configured))
        cash -= value
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def recommendation_execution_order(recommendations: pd.DataFrame) -> pd.DataFrame:
    if recommendations.empty:
        return pd.DataFrame(columns=["Step"] + OUTPUT_COLUMNS)
    priority = {"Sell fully": 1, "Sell partially": 1, "Buy new asset": 2, "Hold / consider add": 3,
                "Add to savings plan": 3, "Hold": 4, "No trade / watchlist": 5, "No trade": 5}
    result = recommendations.copy()
    result["_priority"] = result["Action"].map(priority).fillna(9)
    result = result.sort_values(["_priority", "Score", "Est. value"], ascending=[True, False, False]).reset_index(drop=True)
    result.insert(0, "Step", result.index + 1)
    return result[["Step"] + OUTPUT_COLUMNS]
