"""Editable savings-plan records and manual Scalable execution checklist."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

PLAN_COLUMNS = ["instrument", "isin", "category", "current_plan", "new_plan", "action",
                "priority", "score", "reason", "user_approved", "last_updated"]


def normalize_savings_plan_rows(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    defaults = {"instrument": "", "isin": "", "category": "Other tactical", "current_plan": 0.0,
                "new_plan": 0.0, "action": "Keep", "priority": 5, "score": 0.0, "reason": "",
                "user_approved": False, "last_updated": ""}
    aliases = {"current_plan_eur": "current_plan", "new_plan_eur": "new_plan",
               "Instrument": "instrument", "ISIN": "isin", "Category": "category",
               "Current plan": "current_plan", "New plan": "new_plan", "Action": "action",
               "Priority": "priority", "Score": "score", "Reason": "reason",
               "User approved": "user_approved", "Last updated": "last_updated"}
    for old, new in aliases.items():
        if new not in frame and old in frame: frame[new] = frame[old]
    for column, default in defaults.items():
        if column not in frame: frame[column] = default
    for column in ("current_plan", "new_plan", "priority", "score"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(defaults[column])
    frame["user_approved"] = frame["user_approved"].fillna(False).astype(bool)
    return frame[PLAN_COLUMNS]


def validate_savings_plan_budget(df: pd.DataFrame, monthly_budget: float) -> dict:
    frame = normalize_savings_plan_rows(df); total = round(float(frame["new_plan"].sum()), 2)
    difference = round(float(monthly_budget) - total, 2)
    return {"valid": abs(difference) < .01, "total": total, "budget": float(monthly_budget), "difference": difference}


def apply_savings_plan_updates(current_plans: pd.DataFrame, edited_plans: pd.DataFrame) -> pd.DataFrame:
    current = normalize_savings_plan_rows(current_plans).set_index("isin")
    edited = normalize_savings_plan_rows(edited_plans)
    edited["last_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for _, row in edited.iterrows(): current.loc[row["isin"]] = row
    return current.reset_index()[PLAN_COLUMNS]


def create_savings_plan_execution_checklist(current_plans: pd.DataFrame, optimized_plans: pd.DataFrame) -> pd.DataFrame:
    current = normalize_savings_plan_rows(current_plans).set_index("isin")["current_plan"].to_dict()
    optimized = normalize_savings_plan_rows(optimized_plans)
    rows = []
    for _, row in optimized.iterrows():
        old, new = float(current.get(row["isin"], 0)), float(row["new_plan"])
        if old == new: continue
        rows.append({"Instrument": row["instrument"], "ISIN": row["isin"], "Current EUR": old,
                     "Set manually to EUR": new, "Action": "Add" if old == 0 else "Pause" if new == 0 else "Increase" if new > old else "Reduce",
                     "Warning": "Update manually in Scalable Capital; this app cannot change broker plans."})
    return pd.DataFrame(rows)


def summarize_savings_plan_changes(current_plans: pd.DataFrame, optimized_plans: pd.DataFrame) -> str:
    checklist = create_savings_plan_execution_checklist(current_plans, optimized_plans)
    return "No savings-plan changes." if checklist.empty else f"{len(checklist)} manual Scalable savings-plan change(s) prepared."
