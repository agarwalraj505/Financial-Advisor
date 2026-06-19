"""Serializable enrichment audit records."""

from __future__ import annotations

from datetime import datetime, timezone


def audit_event(asset: dict, provider: str, action: str, success: bool, details: str = "",
                source_url: str = "", confidence: str = "Low") -> dict:
    return {"isin": asset.get("isin", ""), "instrument": asset.get("instrument", ""),
            "provider": provider, "action": action, "success": success, "details": details,
            "source_url": source_url, "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def audit_to_rows(audit: list[dict]) -> list[dict]:
    return [dict(item) for item in audit]
