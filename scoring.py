"""Transparent score composition for current and candidate assets."""

from __future__ import annotations

import pandas as pd

from asset_quality import calculate_asset_quality

TOTAL_WEIGHTS = {"momentum_score": .25, "quality_score": .25, "cost_score": .15,
                 "portfolio_fit_score": .25, "risk_control_score": .10}

CATEGORY_BUCKETS = {"India": "EM", "AI": "Growth", "Semiconductors": "Growth",
    "Quality tech": "Growth", "Cybersecurity": "Growth", "Healthcare innovation": "Growth",
    "Robotics": "Growth", "Gold": "Commodities", "Silver": "Commodities"}


def allocation_bucket(category: str) -> str:
    return CATEGORY_BUCKETS.get(str(category), str(category))


def _number(value, default=0.0) -> float:
    try:
        return default if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 2)


def calculate_cost_score(asset: dict | pd.Series, trade_value: float = 0,
                         direct_trade_minimum: float = 250) -> float:
    asset_type = str(asset.get("asset_type", ""))
    components = []
    if asset_type in {"ETF", "ETC", "ETP"}:
        ter = asset.get("ter_pct")
        if ter is not None and not pd.isna(ter):
            components.append(clamp(10 - float(ter) * 10))
    spread = asset.get("manual_spread_estimate_pct")
    if spread is not None and not pd.isna(spread):
        components.append(clamp(10 - float(spread) * 12))
    liquidity = asset.get("liquidity_score")
    if liquidity is not None and not pd.isna(liquidity):
        components.append(clamp(float(liquidity)))
    score = sum(components) / len(components) if components else 4.0
    if trade_value and trade_value < direct_trade_minimum:
        score -= 1 if bool(asset.get("savings_plan_available", False)) else 3
    if not bool(asset.get("scalable_compatible", True)):
        score -= 3
    return clamp(score)


def calculate_portfolio_fit_score(asset: dict | pd.Series, drift_by_category: dict[str, float],
                                  projected_weight: float = 0, max_single_weight: float = 25) -> float:
    category = str(asset.get("category", ""))
    bucket = allocation_bucket(category)
    drift = float(drift_by_category.get(bucket, drift_by_category.get(category, 0)))
    score = 5 - drift / 2  # negative drift means underweight and improves fit
    overlap = _number(asset.get("overlap_score"), 0)
    score -= max(0, overlap - 4) * .5
    if projected_weight > max_single_weight:
        score -= min(4, (projected_weight - max_single_weight) / 3)
    if str(asset.get("theme", "")).strip() and overlap < 4:
        score += .5
    return clamp(score)


def calculate_risk_control_score(asset: dict | pd.Series, metrics: dict,
                                 risk_profile: str = "Aggressive", max_crypto_weight: float = 5) -> float:
    volatility = abs(_number(metrics.get("volatility_pct"), 35))
    drawdown = abs(_number(metrics.get("max_drawdown_pct"), 25))
    score = 10 - volatility / 12 - drawdown / 20
    profile_adjustment = {"Balanced": -1.0, "Growth": 0.0, "Aggressive": .5}.get(risk_profile, 0)
    score += profile_adjustment
    if str(asset.get("category", "")) == "Crypto":
        score -= 1.5
        if _number(asset.get("projected_category_weight"), 0) > max_crypto_weight:
            score -= 4
    if str(metrics.get("trend_status", "")) == "high-risk falling trend":
        score -= 2
    return clamp(score)


def calculate_total_score(momentum: float, quality: float, cost: float, fit: float, risk: float) -> float:
    values = {"momentum_score": momentum, "quality_score": quality, "cost_score": cost,
              "portfolio_fit_score": fit, "risk_control_score": risk}
    return round(sum(clamp(values[key]) * weight for key, weight in TOTAL_WEIGHTS.items()), 2)


def score_assets(assets: pd.DataFrame, research: pd.DataFrame, drift: pd.DataFrame,
                 settings: dict, is_current: bool = False) -> pd.DataFrame:
    research_lookup = research.set_index("price_symbol").to_dict("index") if not research.empty else {}
    drift_lookup = drift.set_index("category")["drift_pct_points"].to_dict() if not drift.empty else {}
    total_portfolio = _number(settings.get("portfolio_total_eur"), 0)
    rows = []
    for _, source in assets.iterrows():
        row = source.to_dict()
        row["target_category"] = allocation_bucket(str(row.get("category", "")))
        if _number(row.get("overlap_score"), 0) == 0:
            category_counts = settings.get("current_category_counts", {})
            row["overlap_score"] = min(10, _number(category_counts.get(str(row.get("category", ""))), 0) * 2)
        metrics = research_lookup.get(str(row.get("price_symbol", "")), {})
        quality = calculate_asset_quality(row, metrics)
        current_value = _number(row.get("current_value_eur"), 0)
        projected_weight = current_value / total_portfolio * 100 if total_portfolio else 0
        momentum = _number(metrics.get("momentum_score"), 0)
        cost = calculate_cost_score(row, 0, _number(settings.get("direct_trade_minimum"), 250))
        fit = calculate_portfolio_fit_score(row, drift_lookup, projected_weight,
                                            _number(settings.get("max_single_holding_weight"), 25))
        risk = calculate_risk_control_score(row, metrics, str(settings.get("risk_profile", "Aggressive")),
                                            _number(settings.get("max_crypto_weight"), 5))
        total = calculate_total_score(momentum, quality["quality_score"], cost, fit, risk)
        if quality["manual_review_required"]:
            band = "Manual review required"
        elif total >= 8:
            band = "Eligible for buy/add"
        elif total >= 6.5:
            band = "Watchlist only"
        else:
            band = "Avoid / no buy"
        confidence_levels = [quality["quality_confidence"], metrics.get("research_confidence", "Low")]
        confidence = "Low" if "Low" in confidence_levels else "Medium" if "Medium" in confidence_levels else "High"
        row.update(metrics)
        row.update(quality)
        row.update({"momentum_score": round(momentum, 2), "cost_score": cost,
                    "portfolio_fit_score": fit, "risk_control_score": risk, "total_score": total,
                    "score_band": band, "data_confidence": confidence, "is_current_holding": is_current,
                    "data_source": metrics.get("data_source") or row.get("data_source") or "Manual review required",
                    "last_updated": metrics.get("last_updated") or row.get("last_updated") or ""})
        rows.append(row)
    return pd.DataFrame(rows)
