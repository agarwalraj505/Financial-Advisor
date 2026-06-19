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


def assess_asset_readiness(asset: dict | pd.Series, is_candidate: bool = False) -> dict:
    """Separate valuation readiness from buy/add recommendation readiness."""
    quantity = _number(asset.get("quantity"), 1 if is_candidate else 0) or 0
    price = (_number(asset.get("live_current_price"), 0) or _number(asset.get("latest_price"), 0)
             or _number(asset.get("manual_current_price"), 0) or _number(asset.get("current_price_eur"), 0))
    currency = str(asset.get("currency", "") or "").upper()
    fx = _number(asset.get("fx_rate_to_eur"), 1 if currency == "EUR" else 0) or 0
    valuation_reasons = []
    if not is_candidate and quantity <= 0: valuation_reasons.append("Quantity missing")
    if not price: valuation_reasons.append("Live and manual price missing")
    if not currency: valuation_reasons.append("Currency missing")
    elif currency != "EUR" and fx <= 0: valuation_reasons.append("FX rate to EUR missing")
    valuation_ready = not valuation_reasons

    recommendation_reasons = list(valuation_reasons)
    asset_type = str(asset.get("asset_type", "") or "")
    if not str(asset.get("category", "") or "").strip(): recommendation_reasons.append("Category missing")
    if not asset_type.strip(): recommendation_reasons.append("Asset type missing")
    if is_candidate and not bool(asset.get("scalable_compatible", False)):
        recommendation_reasons.append("Scalable compatibility not confirmed")
    if asset_type in FUND_TYPES:
        ter = _number(asset.get("ter_pct")) or _number(asset.get("ter_percent"))
        notes = str(asset.get("notes", "") or "").lower()
        suggestion = (asset.get("enrichment_suggestions") or {}).get("ter_pct", {}) if isinstance(asset.get("enrichment_suggestions"), dict) else {}
        verified_suggestion = suggestion.get("value") is not None and suggestion.get("confidence") == "High"
        if ter is None and not verified_suggestion and not any(word in notes for word in ("verified cost", "verified ter")):
            recommendation_reasons.append("Quality review required: TER/cost missing")
    source = str(asset.get("data_source", "") or asset.get("provider", "") or "")
    confidence = str(asset.get("data_confidence", "") or asset.get("web_scrape_confidence", "") or "")
    if not source: recommendation_reasons.append("Data source missing")
    if not confidence: recommendation_reasons.append("Data confidence missing")
    recommendation_ready = valuation_ready and not recommendation_reasons
    return {"valuation_ready": valuation_ready, "recommendation_ready": recommendation_ready,
            "valuation_review_reasons": "; ".join(valuation_reasons),
            "recommendation_review_reasons": "; ".join(dict.fromkeys(recommendation_reasons))}


def calculate_asset_quality(asset: dict | pd.Series, market_metrics: dict | None = None,
                            is_candidate: bool = False) -> dict:
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
    readiness = assess_asset_readiness(asset, is_candidate)
    missing = critical_missing_fields(asset)
    confidence = "High" if not missing and len(values) >= 4 else "Medium" if not missing else "Low"
    if missing:
        prefix = "Manual review required" if bool(asset.get("manual_review_attempted", False)) else "Data enrichment required"
        reasons.append(prefix + ": " + ", ".join(missing))
    has_valuation_context = any(key in asset for key in (
        "quantity", "live_current_price", "latest_price", "manual_current_price", "current_price_eur"
    ))
    return {"quality_score": round(score, 2), "quality_confidence": confidence,
            # A standalone quality calculation may not yet contain valuation fields.
            # Operational scoring still uses recommendation_ready below.
            "manual_review_required": (not readiness["recommendation_ready"] if has_valuation_context else bool(missing)),
            "missing_critical_data": readiness["recommendation_review_reasons"],
            "quality_reason": "; ".join(reasons) if reasons else "Indicative quality score; confirm metadata.",
            **readiness}
