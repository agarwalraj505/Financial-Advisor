"""Provider metadata merging that preserves user-entered values."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isnan

from enrichment_audit import audit_event
from web_search import generate_yfinance_symbol_candidates


def merge_provider_data(asset: dict, provider_data: dict, provider: str,
                        confidence: str, audit: list[dict] | None = None) -> dict:
    output = dict(asset); suggestions = dict(output.get("enrichment_suggestions") or {})
    conflicts = dict(output.get("metadata_conflicts") or {})
    field_map = {"ter_percent": "ter_pct", "ticker": "ticker_id", "name": "instrument",
                 "security_type": "asset_type"}
    def missing(value):
        return value in (None, "", 0) or (isinstance(value, float) and isnan(value))
    for source_field, value in provider_data.items():
        target = field_map.get(source_field, source_field)
        if target in {"provider", "isin"} or missing(value): continue
        current = output.get(target)
        if missing(current):
            suggestions[target] = {"value": value, "provider": provider, "confidence": confidence,
                                   "source_url": provider_data.get("source_url", ""),
                                   "source_title": provider_data.get("source_title", provider),
                                   "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        elif str(current) != str(value):
            conflicts[target] = {"entered": current, "suggested": value,
                                 "provider": provider, "confidence": confidence}
    output["enrichment_suggestions"], output["metadata_conflicts"] = suggestions, conflicts
    if audit is not None:
        audit.append(audit_event(asset, provider, "metadata merge", True,
                                 f"{len(suggestions)} suggestions, {len(conflicts)} conflicts", confidence=confidence))
    return output


def accept_suggestion(asset: dict, field: str) -> dict:
    output = dict(asset); suggestions = dict(output.get("enrichment_suggestions") or {})
    suggestion = suggestions.pop(field, None)
    if suggestion:
        output[field] = suggestion.get("value")
        output["confirmed_by_user"] = True
    output["enrichment_suggestions"] = suggestions
    return output


def suggested_symbol_candidates(asset: dict, openfigi_data: dict | None = None) -> list[str]:
    working = dict(asset)
    if openfigi_data and openfigi_data.get("ticker_id"):
        working["suggested_price_symbol"] = openfigi_data["ticker_id"]
    return generate_yfinance_symbol_candidates(working)
