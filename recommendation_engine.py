"""Recommendation report composition and traceability helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from collections import OrderedDict

import pandas as pd

from rulebook_engine import (build_required_rebalance_sections, create_skip_conditions,
                             format_allocation_table, format_immediate_buy_sell_table,
                             format_savings_plan_table)


def build_recommendation_report(rebalance: pd.DataFrame, savings: pd.DataFrame) -> pd.DataFrame:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report_id = str(uuid4())
    trade = rebalance.copy()
    if not trade.empty:
        trade.insert(0, "Report section", "Portfolio action")
        trade.insert(0, "Report ID", report_id)
        trade.insert(1, "Generated at", generated_at)
    savings_rows = []
    for _, row in savings.iterrows():
        savings_rows.append({"Report ID": report_id, "Generated at": generated_at,
                             "Report section": "Savings plan", "Action": row["Action"],
                             "Purpose": "Optimize monthly contributions", "Instrument": row["Instrument"],
                             "ISIN": row["ISIN"], "Ticker/ID": "", "Quantity": 0,
                             "Est. value": row["New plan"], "Fee issue": "Savings-plan execution; verify eligibility",
                             "Score": row["Score"], "Data confidence": "Low",
                             "Reason": row["Reason"], "Price source": "Not applicable to savings plan",
                             "Metadata source": "Saved portfolio and scored candidate universe",
                             "News/sentiment input": "See latest strategy snapshot", "Last updated": generated_at,
                             "Scalable execution warning": "Check availability and update manually in Scalable Capital",
                             "Data source": "Saved portfolio and scored candidate universe",
                             "Timestamp": generated_at, "Execution note": "Check live Scalable availability before execution"})
    savings_frame = pd.DataFrame(savings_rows)
    return pd.concat([trade, savings_frame], ignore_index=True, sort=False)


def build_structured_rebalance_report(*, strategy: dict, theme_ranking, target_review,
                                      gap_analysis, recommendations, execution_order,
                                      savings_plans, allocation, watchlist,
                                      market_reasoning: str, context: dict | None = None) -> OrderedDict:
    """Return every mandatory rulebook section in its prescribed order."""
    values = {
        "Market and strategy refresh": strategy,
        "Theme / sector ranking": theme_ranking,
        "Target allocation review": target_review,
        "Portfolio gap analysis": gap_analysis,
        "Immediate buy/sell table": format_immediate_buy_sell_table(recommendations),
        "Execution order": execution_order,
        "Savings-plan adjustment table": format_savings_plan_table(savings_plans),
        "Allocation table": format_allocation_table(allocation, strategy.get("target_allocations", {})),
        "Themes considered but rejected / watchlisted": watchlist,
        "Short market reasoning": market_reasoning,
        "Skip conditions / when not to execute": create_skip_conditions(context),
    }
    return OrderedDict((section, values[section]) for section in build_required_rebalance_sections())
