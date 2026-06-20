"""Precise, actionable data-gap reporting after the source waterfall."""

from __future__ import annotations

import pandas as pd


def _number(value) -> float:
    try: return 0.0 if pd.isna(value) else float(value or 0)
    except (TypeError, ValueError): return 0.0


def _verified_cost(asset: dict) -> bool:
    if _number(asset.get("ter_pct")) > 0 or "verified cost" in str(asset.get("notes", "")).lower():
        return True
    suggestions = asset.get("enrichment_suggestions") or {}
    suggestion = suggestions.get("ter_pct", {}) if isinstance(suggestions, dict) else {}
    return suggestion.get("value") is not None and suggestion.get("confidence") == "High"


GAP_RULES = {
    "price": lambda a, candidate: not any(_number(a.get(field)) > 0 for field in ("live_current_price", "manual_current_price", "latest_price")),
    "symbol": lambda a, candidate: str(a.get("asset_type", "")).lower() != "cash" and not str(a.get("price_symbol", "") or "").strip(),
    "TER/cost": lambda a, candidate: str(a.get("asset_type", "")) in {"ETF", "ETC", "ETP"} and not _verified_cost(a),
    "factsheet": lambda a, candidate: str(a.get("asset_type", "")) in {"ETF", "ETC", "ETP"} and not a.get("factsheet_url"),
    "category": lambda a, candidate: not str(a.get("category", "") or "").strip(),
    "asset type": lambda a, candidate: not str(a.get("asset_type", "") or "").strip(),
    "Scalable compatibility": lambda a, candidate: candidate and not bool(a.get("scalable_compatible", False)),
    "FX": lambda a, candidate: str(a.get("currency", "EUR") or "EUR") != "EUR" and not _number(a.get("fx_rate_to_eur")),
}


NEXT_ACTION = {"price": "Confirm symbol, then enter a manual price only after failed enrichment",
               "symbol": "Run symbol repair", "TER/cost": "Run deep metadata scan and confirm issuer factsheet",
               "factsheet": "Search issuer/KID sources", "category": "Confirm category manually",
               "asset type": "Map identifier or confirm asset type", "Scalable compatibility": "Confirm in Scalable manually",
               "FX": "Retry ECB/yfinance FX or enter confirmed manual FX"}


def _attempt_summary(asset: dict) -> tuple[str, str, str]:
    audit = asset.get("enrichment_audit") if isinstance(asset.get("enrichment_audit"), list) else []
    providers = ", ".join(dict.fromkeys(str(item.get("provider", "")) for item in audit if item.get("provider")))
    failures = [item for item in audit if not item.get("success", True)]
    failure = str(failures[-1].get("detail", "")) if failures else ""
    return providers or "Not attempted", str(asset.get("last_auto_repair_at", "") or asset.get("last_updated", "")), failure


def generate_data_gap_report(holdings: pd.DataFrame, candidates: pd.DataFrame,
                             provider_failures: list[dict] | None = None) -> pd.DataFrame:
    rows = []
    for frame, candidate in ((holdings, False), (candidates, True)):
        for _, source in frame.iterrows():
            asset = source.to_dict(); tried, last_attempt, failure = _attempt_summary(asset)
            for field, rule in GAP_RULES.items():
                try: missing = bool(rule(asset, candidate))
                except (TypeError, ValueError): missing = True
                if missing:
                    rows.append({"Dataset": "Candidate" if candidate else "Holding", "Asset": asset.get("instrument", ""),
                                 "ISIN": asset.get("isin", ""), "Missing field": field,
                                 "Sources already tried": tried, "Last attempt": last_attempt,
                                 "Failure reason": failure or "No verified value available",
                                 "Suggested next action": NEXT_ACTION[field]})
    for failure in provider_failures or []:
        rows.append({"Dataset": "Provider", "Asset": failure.get("asset_key", ""), "ISIN": failure.get("isin", ""),
                     "Missing field": failure.get("error_type", "Provider failure"),
                     "Sources already tried": failure.get("provider", ""), "Last attempt": failure.get("created_at", ""),
                     "Failure reason": failure.get("error_message", ""), "Suggested next action": "Retry after cooldown"})
    return pd.DataFrame(rows)
