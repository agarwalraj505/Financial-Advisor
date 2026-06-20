"""Field-level source audit helpers; entered facts are never silently replaced."""

from __future__ import annotations

from datetime import datetime, timezone


def source_record(asset: dict, field_name: str, value, provider: str, *, source_url: str = "",
                  source_title: str = "", confidence: str = "Low",
                  extraction_method: str = "provider", user_confirmed: bool = False,
                  conflict=None) -> dict:
    return {"asset_key": str(asset.get("isin") or asset.get("instrument") or ""),
            "isin": asset.get("isin", ""), "field_name": field_name,
            "field_value": value, "provider": provider, "source_url": source_url,
            "source_title": source_title, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "confidence": confidence, "extraction_method": extraction_method,
            "user_confirmed": bool(user_confirmed), "conflict": conflict}


def suggestion_audit_rows(asset: dict) -> list[dict]:
    suggestions = asset.get("enrichment_suggestions") or {}
    conflicts = asset.get("metadata_conflicts") or {}
    rows = []
    for field, suggestion in suggestions.items():
        if not isinstance(suggestion, dict) or suggestion.get("value") in (None, ""):
            continue
        rows.append(source_record(asset, field, suggestion.get("value"), suggestion.get("provider", "Unknown"),
                                  source_url=suggestion.get("source_url", ""),
                                  source_title=suggestion.get("source_title", ""),
                                  confidence=suggestion.get("confidence", "Low"),
                                  extraction_method=suggestion.get("extraction_method", "provider suggestion"),
                                  conflict=conflicts.get(field)))
    return rows

