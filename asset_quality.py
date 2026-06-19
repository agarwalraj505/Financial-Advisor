"""Explainable asset-quality checks using provider or manually entered facts."""

from __future__ import annotations

from math import log10
from datetime import datetime, timezone

import pandas as pd


FUND_TYPES = {"ETF", "ETC", "ETP"}


def _number(value, default=None):
    try:
        return default if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return default


def critical_missing_fields(asset: dict | pd.Series) -> list[str]:
    missing = []
    asset_type = str(asset.get("asset_type", ""))
    if not str(asset.get("price_symbol", "") or "").strip() and not (_number(asset.get("manual_current_price"), 0) or 0):
        missing.append("Price Symbol or manual current price")
    if not str(asset.get("category", "") or "").strip():
        missing.append("Category")
    if not asset_type.strip():
        missing.append("Asset type")
    if asset_type in FUND_TYPES:
        notes = str(asset.get("notes", "") or "").lower()
        if _number(asset.get("ter_pct")) is None and not any(word in notes for word in ("ter", "cost", "fee")):
            missing.append("TER % or manual cost note")
    if not bool(asset.get("scalable_compatible", True)):
        missing.append("Scalable compatibility")
    return missing


def calculate_asset_quality(asset: dict | pd.Series, market_metrics: dict | None = None) -> dict:
    market_metrics = market_metrics or {}
    asset_type = str(asset.get("asset_type", ""))
    reasons, values = [], []
    if asset_type in FUND_TYPES:
        ter = _number(asset.get("ter_pct"))
        size = _number(asset.get("fund_size_eur"))
        spread = _number(asset.get("manual_spread_estimate_pct"))
        liquidity = _number(asset.get("liquidity_score"))
        if ter is not None:
            values.append(max(0, min(10, 10 - ter * 10)))
            reasons.append(f"TER {ter:.2f}%")
        if size and size > 0:
            values.append(max(0, min(10, 2 + log10(size / 1_000_000) * 2)))
            reasons.append(f"fund size €{size:,.0f}")
        if spread is not None:
            values.append(max(0, min(10, 10 - spread * 12)))
            reasons.append(f"spread estimate {spread:.2f}%")
        if liquidity is not None:
            values.append(max(0, min(10, liquidity)))
        if bool(asset.get("savings_plan_available", False)):
            values.append(8.0)
        replication = str(asset.get("replication_method", "")).lower()
        if replication:
            values.append(9 if "physical" in replication else 8 if "optim" in replication else 6)
        domicile = str(asset.get("domicile", "")).upper()
        if domicile:
            values.append(8 if domicile in {"IE", "IRELAND", "LU", "LUXEMBOURG", "DE", "GERMANY"} else 6)
        tracking = _number(asset.get("tracking_quality_score"))
        if tracking is not None:
            values.append(max(0, min(10, tracking)))
        policy = str(asset.get("distribution_policy", "")).lower()
        if policy:
            values.append(8 if "acc" in policy else 6)
        inception = pd.to_datetime(asset.get("inception_date"), errors="coerce", utc=True)
        if not pd.isna(inception):
            age_years = (datetime.now(timezone.utc) - inception.to_pydatetime()).days / 365.25
            values.append(max(2, min(10, 4 + age_years / 2)))
    elif asset_type == "Stock":
        for field in ("revenue_growth_score", "earnings_quality_score", "valuation_fundamental_score", "valuation_score",
                      "profitability_score", "balance_sheet_score"):
            value = _number(asset.get(field))
            if value is not None:
                values.append(max(0, min(10, value)))
    elif asset_type in {"Crypto", "Crypto ETP"}:
        momentum = _number(market_metrics.get("momentum_score"), 0)
        liquidity = _number(asset.get("liquidity_score"), 5)
        drawdown = abs(_number(market_metrics.get("max_drawdown_pct"), 50))
        values.extend([momentum, liquidity, max(0, 10 - drawdown / 8)])
        reasons.append("crypto risk, liquidity and drawdown controls")
    else:
        values.append(_number(asset.get("quality_score"), 5))
    overlap = _number(asset.get("overlap_score"), 0) or 0
    score = sum(values) / len(values) if values else 0.0
    score = max(0, score - max(0, overlap - 5) * .35)
    missing = critical_missing_fields(asset)
    confidence = "High" if not missing and len(values) >= 4 else "Medium" if not missing else "Low"
    if missing:
        reasons.append("Manual review required: " + ", ".join(missing))
    return {"quality_score": round(score, 2), "quality_confidence": confidence,
            "manual_review_required": bool(missing), "missing_critical_data": ", ".join(missing),
            "quality_reason": "; ".join(reasons) if reasons else "Manual review required."}
