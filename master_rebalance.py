"""Observable orchestration for the full market-data-first rebalance pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

PIPELINE_STEPS = ["refresh_prices", "enrich_assets", "repair_missing_metadata", "fetch_news",
    "calculate_sentiment", "redesign_strategy", "recalculate_valuation", "recalculate_drift",
    "score_assets", "run_portfolio_optimizer", "run_savings_optimizer", "create_report",
    "create_execution_checklist", "save_run"]


def run_full_rebalance_pipeline(steps: dict[str, callable]) -> dict:
    results, warnings = {}, []
    for name in PIPELINE_STEPS:
        function = steps.get(name)
        if not function:
            warnings.append(f"Missing pipeline step: {name}"); continue
        try:
            results[name] = function(results)
        except Exception as exc:
            warnings.append(f"{name} failed: {exc}")
            results[name] = None
    return {"run_status": "Completed" if not warnings else "Completed with warnings",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "results": results, "warnings": warnings}
