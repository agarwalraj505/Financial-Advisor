"""Observable orchestration for the full market-data-first rebalance pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

PIPELINE_STEPS = ["refresh_prices", "enrich_missing_data", "read_news", "fresh_market_research",
    "calculate_sentiment", "refresh_strategy", "theme_ranking", "target_allocation_review",
    "portfolio_gap_analysis", "buy_sell_plan", "savings_plan_changes", "execution_order"]

PIPELINE_LABELS = ["Refreshing Prices", "Enriching missing data", "Reading News",
    "Fresh market research", "Calculating Sentiments", "Refreshing Strategy", "Theme ranking",
    "Target allocation review", "Portfolio gap analysis", "Buy/sell plan",
    "Savings-plan changes", "Execution order"]


def run_full_rebalance_pipeline(steps: dict[str, callable]) -> dict:
    results, warnings = {}, []
    for name in PIPELINE_STEPS:
        function = steps.get(name)
        if not function:
            warnings.append(f"Missing pipeline step: {name}")
            results[name] = {"status": "Incomplete", "estimated": True}
            continue
        try:
            results[name] = function(results)
        except Exception as exc:
            warnings.append(f"{name} failed: {exc}")
            results[name] = {"status": "Incomplete", "estimated": True, "error": str(exc)}
    if steps.get("save_run"):
        try:
            results["persistence"] = steps["save_run"](results)
        except Exception as exc:
            warnings.append(f"save_run failed: {exc}")
    return {"run_status": "Completed" if not warnings else "Completed with warnings",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "results": results, "warnings": warnings}
