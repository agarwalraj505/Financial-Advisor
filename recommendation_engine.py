"""Recommendation report composition and traceability helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd


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
                             "Reason": row["Reason"], "Data source": "Manual portfolio + scored universe",
                             "Timestamp": generated_at, "Execution note": "Check live Scalable availability before execution"})
    savings_frame = pd.DataFrame(savings_rows)
    return pd.concat([trade, savings_frame], ignore_index=True, sort=False)
