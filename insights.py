"""Small, explainable portfolio insight rules."""

from __future__ import annotations

import pandas as pd


def generate_insights(
    holdings: pd.DataFrame,
    drift: pd.DataFrame,
    fee_threshold: float = 250.0,
    cash_max_pct: float = 2.0,
) -> list[str]:
    if holdings.empty:
        return ["Add holdings to generate insights."]
    frame = holdings.copy()
    total = float(frame["current_value_eur"].sum())
    insights: list[str] = []
    if total > 0:
        largest = frame.loc[frame["current_value_eur"].idxmax()]
        weight = float(largest["current_value_eur"]) / total * 100
        insights.append(f"Largest holding: {largest['instrument']} at €{largest['current_value_eur']:,.2f} ({weight:.1f}%).")
        if weight > 25:
            insights.append(f"Concentration warning: {largest['instrument']} is above 25% of the portfolio.")
    if "daily_gain_eur" not in frame:
        frame["daily_gain_eur"] = 0.0
    frame["daily_gain_eur"] = pd.to_numeric(frame["daily_gain_eur"], errors="coerce").fillna(0.0)
    daily = frame
    if not daily.empty:
        winner, loser = daily.loc[daily["daily_gain_eur"].idxmax()], daily.loc[daily["daily_gain_eur"].idxmin()]
        insights.append(f"Largest daily winner: {winner['instrument']} ({winner['daily_gain_eur']:+.2f} EUR).")
        insights.append(f"Largest daily loser: {loser['instrument']} ({loser['daily_gain_eur']:+.2f} EUR).")
    exposure = frame.groupby("category")["current_value_eur"].sum()
    if not exposure.empty:
        insights.append(f"Highest category exposure: {exposure.idxmax()} at €{exposure.max():,.2f}.")
    if not drift.empty:
        over, under = drift.loc[drift["drift_pct_points"].idxmax()], drift.loc[drift["drift_pct_points"].idxmin()]
        insights.append(f"Most overweight category: {over['category']} ({over['drift_pct_points']:+.1f} pp).")
        insights.append(f"Most underweight category: {under['category']} ({under['drift_pct_points']:+.1f} pp).")
    non_cash = frame[frame["category"] != "Cash"]
    missing_symbols = non_cash[non_cash["price_symbol"].fillna("").str.strip() == ""]["instrument"].tolist()
    fallbacks = non_cash[non_cash["price_source"] == "Manual fallback"]["instrument"].tolist()
    if missing_symbols:
        insights.append("Missing live price symbols: " + ", ".join(missing_symbols) + ".")
    if fallbacks:
        insights.append("Using manual fallback price: " + ", ".join(fallbacks) + ".")
    cash = float(frame.loc[frame["category"] == "Cash", "current_value_eur"].sum())
    cash_pct = cash / total * 100 if total else 0
    if cash_pct > cash_max_pct:
        insights.append(f"Cash warning: cash is {cash_pct:.1f}%, above the configured {cash_max_pct:.1f}% maximum.")
    small = non_cash[(non_cash["current_value_eur"] > 0) & (non_cash["current_value_eur"] < fee_threshold)]
    if not small.empty:
        insights.append(f"Small-position fee warning: {len(small)} holding(s) are below €{fee_threshold:,.0f}.")
    return insights
