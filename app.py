"""Production-style Streamlit wealth manager backed by Supabase."""

from datetime import datetime
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import logout_button, require_authentication
from db import Database
from market_data import fetch_fx_rate_to_eur, fetch_market_quote
from market_research import build_market_research
from optimizer import generate_market_aware_recommendations, recommendation_execution_order
from recommendation_engine import build_recommendation_report
from rebalancer import (allocation_table, calculate_allocation, calculate_drift, calculate_total_invested,
                        calculate_total_value, calculate_unrealised_pl, holdings_to_dataframe,
                        savings_plans_to_dataframe)
from sample_data import (CANDIDATE_COLUMNS, SAMPLE_CANDIDATES, SAMPLE_HOLDINGS, SAMPLE_SAVINGS_PLANS,
                         SUPPORTED_CATEGORIES, TARGET_ALLOCATIONS)
from savings_plan_optimizer import optimize_savings_plans
from scoring import score_assets
from storage import ScreenshotStorage
from supabase_client import SupabaseConnectionError, SupabaseGateway, get_supabase_client
from valuation import calculate_historical_gains, portfolio_market_history, valuate_holdings

st.set_page_config(page_title="Market-Aware Wealth Manager", page_icon="⚖️", layout="wide")

HOLDING_DISPLAY = {"instrument": "Instrument", "isin": "ISIN", "ticker_id": "Ticker/ID",
    "price_symbol": "Price Symbol", "asset_type": "Asset type", "category": "Category", "quantity": "Quantity",
    "theme": "Theme", "region": "Region",
    "manual_current_price": "Manual current price", "live_current_price": "Live current price",
    "price_source": "Price source", "currency": "Currency", "fx_rate_to_eur": "FX rate to EUR",
    "current_value_eur": "Current value EUR", "buy_in_value_eur": "Buy-in value EUR",
    "pl_eur": "P/L EUR", "pl_pct": "P/L %", "direct_trading_allowed": "Direct trading allowed",
    "fractional_allowed": "Fractional allowed", "notes": "Notes"}
CANDIDATE_DISPLAY = {column: column.replace("_", " ").title() for column in CANDIDATE_COLUMNS}
CANDIDATE_DISPLAY.update({"isin": "ISIN", "ticker_id": "Ticker/ID", "price_symbol": "Price Symbol",
                          "ter_pct": "TER %", "fund_size_eur": "Fund size EUR",
                          "distribution_policy": "Accumulating/distributing", "source_url": "Source URL"})
SCORE_COLUMNS = ["Quality Score", "Momentum Score", "Cost Score", "Portfolio Fit Score",
                 "Risk Control Score", "Total Score", "Data Confidence"]


@st.cache_data(ttl=3600, show_spinner=False)
def cached_quote(symbol: str, bucket: int):
    return fetch_market_quote(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fx(currency: str, bucket: int):
    return fetch_fx_rate_to_eur(currency)


def _normalise_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    numeric = ["ter_pct", "fund_size_eur", "manual_spread_estimate_pct", "liquidity_score",
               "quality_score", "momentum_score", "valuation_score", "cost_score",
               "portfolio_fit_score", "risk_control_score", "total_score", "overlap_score", "tracking_quality_score",
               "revenue_growth_score", "earnings_quality_score", "valuation_fundamental_score",
               "profitability_score", "balance_sheet_score"]
    booleans = ["savings_plan_available", "direct_trading_available", "fractional_allowed", "scalable_compatible"]
    for column in CANDIDATE_COLUMNS:
        if column not in frame:
            frame[column] = None if column in numeric else False if column in booleans else ""
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in booleans:
        frame[column] = frame[column].fillna(False).astype(bool)
    for column in set(CANDIDATE_COLUMNS) - set(numeric) - set(booleans):
        frame[column] = frame[column].fillna("").astype(str)
    return frame[CANDIDATE_COLUMNS]


def _plans_with_categories(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    if "current_plan" not in frame and "current_plan_eur" in frame:
        frame["current_plan"] = frame["current_plan_eur"]
    if "category" not in frame:
        category_lookup = {}
        for source in (st.session_state.get("holdings", pd.DataFrame()), st.session_state.get("candidates", pd.DataFrame())):
            if not source.empty and {"isin", "category"}.issubset(source.columns):
                category_lookup.update(source.drop_duplicates("isin").set_index("isin")["category"].to_dict())
        frame["category"] = frame.get("isin", pd.Series(dtype=str)).map(category_lookup).fillna("Other tactical")
    for column, default in (("instrument", ""), ("isin", ""), ("current_plan", 0.0)):
        if column not in frame:
            frame[column] = default
    return frame[["instrument", "isin", "category", "current_plan"]]


def initialise_state(database: Database):
    db_holdings = database.load_holdings()
    db_candidates = database.load_candidates()
    db_plans = database.load_savings_plans()
    saved_settings = database.load_settings()
    app_settings = {"base_currency": "EUR", "monthly_savings_budget": 300.0,
                    "max_single_holding_weight": 25.0, "max_crypto_weight": 5.0,
                    "cash_min_pct": 0.0, "cash_max_pct": 2.0,
                    "direct_trade_minimum": 250.0, "small_trade_round_trip_fee": 1.98,
                    "live_enabled": True, "refresh_interval": 300, "risk_profile": "Aggressive"}
    app_settings.update({key: value for key, value in saved_settings.items() if key in app_settings})
    defaults = {
        "holdings": db_holdings if not db_holdings.empty else holdings_to_dataframe(SAMPLE_HOLDINGS),
        "candidates": _normalise_candidates(db_candidates if not db_candidates.empty else pd.DataFrame(SAMPLE_CANDIDATES)),
        "targets": saved_settings.get("target_allocations", TARGET_ALLOCATIONS.copy()),
        "quotes": {}, "fx_rates": {"EUR": 1.0},
        "last_price_fetch": None,
        "settings": app_settings}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "plans" not in st.session_state:
        raw_plans = db_plans if not db_plans.empty else pd.DataFrame(SAMPLE_SAVINGS_PLANS)
        st.session_state.plans = _plans_with_categories(raw_plans)
    recompute_models()


def _enrich_current(details: pd.DataFrame) -> pd.DataFrame:
    rows = []
    candidates = st.session_state.candidates
    plan_isins = set(st.session_state.plans.get("isin", pd.Series(dtype=str)).astype(str))
    for _, holding in details.iterrows():
        row = holding.to_dict()
        match = candidates[candidates["isin"] == str(row.get("isin", ""))]
        if not match.empty:
            metadata = match.iloc[0].to_dict()
            for key, value in metadata.items():
                if key not in row or row.get(key) in (None, ""):
                    row[key] = value
        row.setdefault("scalable_compatible", True)
        row.setdefault("manual_spread_estimate_pct", None)
        row["savings_plan_available"] = str(row.get("isin", "")) in plan_isins or bool(row.get("savings_plan_available", False))
        rows.append(row)
    return pd.DataFrame(rows)


def recompute_models():
    details = valuate_holdings(st.session_state.holdings, st.session_state.quotes, st.session_state.fx_rates)
    st.session_state.valuation_details = details
    st.session_state.holdings = holdings_to_dataframe(details.to_dict("records"))
    drift = calculate_drift(st.session_state.holdings, st.session_state.targets)
    research = build_market_research(st.session_state.quotes)
    score_settings = st.session_state.settings.copy()
    score_settings["portfolio_total_eur"] = calculate_total_value(st.session_state.holdings)
    score_settings["current_category_counts"] = details[details["category"] != "Cash"].groupby("category").size().to_dict()
    scored_candidates = score_assets(st.session_state.candidates, research, drift, score_settings, False)
    for index, asset in scored_candidates.iterrows():
        quote = st.session_state.quotes.get(str(asset.get("price_symbol", "")))
        currency = quote.currency if quote and quote.currency else str(asset.get("currency", "EUR"))
        fx = float(st.session_state.fx_rates.get(currency, 1.0))
        scored_candidates.loc[index, "fx_rate_to_eur"] = fx
        scored_candidates.loc[index, "latest_price_eur"] = float(asset.get("latest_price") or 0) * fx
    scored_current = score_assets(_enrich_current(details), research, drift, score_settings, True)
    cash = float(details.loc[details["category"] == "Cash", "current_value_eur"].sum())
    optimizer_settings = st.session_state.settings.copy()
    optimizer_settings["available_cash_eur"] = cash
    optimizer_settings["portfolio_total_eur"] = calculate_total_value(details)
    optimizer_settings["current_crypto_value_eur"] = float(details.loc[details["category"] == "Crypto", "current_value_eur"].sum())
    recommendations = generate_market_aware_recommendations(scored_current, scored_candidates, drift, optimizer_settings)
    all_scored = pd.concat([scored_current, scored_candidates], ignore_index=True, sort=False)
    savings = optimize_savings_plans(st.session_state.plans, all_scored, drift,
                                     st.session_state.settings["monthly_savings_budget"])
    st.session_state.drift, st.session_state.research = drift, research
    st.session_state.scored_candidates, st.session_state.scored_current = scored_candidates, scored_current
    st.session_state.recommendations = recommendations
    st.session_state.optimized_savings = savings
    st.session_state.recommendation_report = build_recommendation_report(
        recommendation_execution_order(recommendations), savings)


def refresh_live_data(force=False):
    if not st.session_state.settings["live_enabled"]:
        st.warning("Live market data is disabled in Settings.")
        return
    if force:
        cached_quote.clear()
        cached_fx.clear()
    interval = max(30, int(st.session_state.settings["refresh_interval"]))
    bucket = int(time.time() // interval)
    symbols = set(st.session_state.holdings["price_symbol"].astype(str)) | set(st.session_state.candidates["price_symbol"].astype(str))
    symbols = sorted(symbol for symbol in symbols if symbol and symbol.lower() != "nan")
    quotes = {symbol: cached_quote(symbol, bucket) for symbol in symbols}
    currencies = {quote.currency for quote in quotes.values() if quote.currency}
    fx_rates = {"EUR": 1.0}
    for currency in currencies - {"EUR"}:
        rate, _ = cached_fx(currency, bucket)
        if rate:
            fx_rates[currency] = rate
    st.session_state.quotes, st.session_state.fx_rates = quotes, fx_rates
    successful = [quote.fetched_at for quote in quotes.values() if quote.is_available]
    if successful:
        st.session_state.last_price_fetch = max(successful)
    recompute_models()
    failed = [symbol for symbol, quote in quotes.items() if not quote.is_available]
    if failed:
        st.warning("Live price unavailable; manual review or manual price required: " + ", ".join(failed))


def refresh_controls(key: str):
    a, b = st.columns([1, 3])
    if a.button("Refresh market data", type="primary", key=key):
        with st.spinner("Fetching Yahoo Finance estimates..."):
            refresh_live_data(True)
    b.caption("Last successful fetch: " + str(st.session_state.last_price_fetch or "None yet"))


def _gain_metric(column, label, gain):
    column.metric(label, "Not enough history yet" if gain is None else f"€{gain['eur']:+,.2f}",
                  None if gain is None else f"{gain['pct']:+.2f}%")


def valuation_dashboard():
    st.header("Valuation Dashboard")
    st.warning("Internet prices are research estimates. Check final live buy/sell prices manually in Scalable Capital before execution.")
    refresh_controls("valuation_refresh")
    details, history = st.session_state.valuation_details, database.load_snapshots()
    total, invested, profit = calculate_total_value(details), calculate_total_invested(details), calculate_unrealised_pl(details)
    cash = float(details.loc[details["category"] == "Cash", "current_value_eur"].sum())
    gains = calculate_historical_gains(total, history)
    cards = st.columns(4)
    cards[0].metric("Portfolio value", f"€{total:,.2f}")
    _gain_metric(cards[1], "Daily gain", gains["daily"])
    _gain_metric(cards[2], "Weekly gain", gains["weekly"])
    _gain_metric(cards[3], "Monthly gain", gains["monthly"])
    cards2 = st.columns(3)
    _gain_metric(cards2[0], "Yearly gain", gains["yearly"])
    cards2[1].metric("Unrealised P/L", f"€{profit:+,.2f}", f"{profit / invested * 100:+.2f}%" if invested else None)
    cards2[2].metric("Cash", f"€{cash:,.2f}")
    if st.button("Save today's valuation snapshot"):
        now = datetime.now().astimezone()
        snapshot = {"date": now.date().isoformat(), "timestamp": now.isoformat(timespec="seconds"),
            "total_value_eur": total, "cash_eur": cash, "invested_value_eur": invested, "unrealized_pl_eur": profit,
            **{f"{period}_gain_eur": gains[period]["eur"] if gains[period] else 0 for period in ["daily", "weekly", "monthly", "yearly"]},
            **{f"{period}_gain_pct": gains[period]["pct"] if gains[period] else 0 for period in ["daily", "weekly", "monthly", "yearly"]}}
        database.save_snapshot(snapshot)
        st.success("Snapshot saved permanently in Supabase.")
        history = database.load_snapshots()
    market_history = portfolio_market_history(details, st.session_state.quotes)
    if market_history.empty and not history.empty:
        market_history = history.rename(columns={"timestamp": "date", "total_value_eur": "portfolio_value_eur"})
        market_history["daily_gain_eur"] = market_history["portfolio_value_eur"].diff().fillna(0)
    left, right = st.columns(2)
    left.plotly_chart(px.line(market_history, x="date", y="portfolio_value_eur", title="Portfolio live value over time"), width="stretch")
    allocation = calculate_allocation(details)
    right.plotly_chart(px.pie(allocation, names="category", values="value", hole=.4, title="Current allocation"), width="stretch")
    missing = details[details["price_source"] == "Missing"]
    fallback = details[(details["price_source"] == "Manual fallback") & (details["category"] != "Cash")]
    if not missing.empty:
        st.warning("Missing live and manual prices: " + ", ".join(missing["instrument"]))
    if not fallback.empty:
        st.warning("Live price unavailable, using manual price: " + ", ".join(fallback["instrument"]))
    chart_left, chart_right = st.columns(2)
    holdings_chart = details.sort_values("current_value_eur")
    chart_left.plotly_chart(px.bar(holdings_chart, x="current_value_eur", y="instrument", orientation="h",
                                   title="Holdings value"), width="stretch")
    winners = details.sort_values("daily_gain_eur")
    chart_right.plotly_chart(px.bar(winners, x="instrument", y="daily_gain_eur", color="daily_gain_eur",
                                    title="Daily winners and losers",
                                    color_continuous_scale=["#B91C1C", "#E5E7EB", "#15803D"]), width="stretch")
    st.dataframe(details, width="stretch", hide_index=True)
    x, y = st.columns(2)
    x.download_button("Export valuation history CSV", history.to_csv(index=False), "valuation_history.csv", "text/csv")
    confirm = y.checkbox("Confirm clear history")
    if y.button("Clear valuation history", disabled=not confirm):
        database.clear_snapshots(); st.rerun()


def dashboard():
    st.header("Dashboard")
    details = st.session_state.valuation_details
    total = calculate_total_value(details)
    cash = float(details.loc[details["category"] == "Cash", "current_value_eur"].sum())
    columns = st.columns(4)
    columns[0].metric("Portfolio value", f"€{total:,.2f}")
    columns[1].metric("Cash", f"€{cash:,.2f}")
    columns[2].metric("Holdings", len(details))
    columns[3].metric("Candidates", len(st.session_state.candidates))
    left, right = st.columns(2)
    allocation = calculate_allocation(details)
    left.plotly_chart(px.pie(allocation, names="category", values="value", hole=.4,
                              title="Current allocation"), width="stretch")
    drift_chart = st.session_state.drift.melt(id_vars="category",
        value_vars=["current_weight", "target_weight"], var_name="Allocation", value_name="Weight %")
    right.plotly_chart(px.bar(drift_chart, x="category", y="Weight %", color="Allocation",
                              barmode="group", title="Current vs target"), width="stretch")
    st.subheader("Highest-priority recommendations")
    order = recommendation_execution_order(st.session_state.recommendations)
    st.dataframe(order.head(10), width="stretch", hide_index=True)


def current_portfolio():
    st.header("Current Portfolio")
    st.caption("Portfolio data is stored in Supabase after you click save. No broker connection is used.")
    display = st.session_state.holdings.rename(columns=HOLDING_DISPLAY)
    edited = st.data_editor(display, num_rows="dynamic", width="stretch", hide_index=True,
        disabled=["Live current price", "Price source", "Current value EUR", "P/L EUR", "P/L %"],
        column_config={"Category": st.column_config.SelectboxColumn(options=SUPPORTED_CATEGORIES)}, key="current_editor")
    st.session_state.holdings = holdings_to_dataframe(edited.rename(columns={v: k for k, v in HOLDING_DISPLAY.items()}).to_dict("records"))
    recompute_models()
    upload = st.file_uploader("Import holdings CSV", type="csv", key="holdings_csv")
    if upload and st.button("Apply holdings CSV"):
        st.session_state.holdings = holdings_to_dataframe(pd.read_csv(upload).rename(columns={v: k for k, v in HOLDING_DISPLAY.items()}).to_dict("records"))
        recompute_models(); st.rerun()
    a, b, c = st.columns(3)
    if a.button("Save portfolio to Supabase"):
        database.save_holdings(st.session_state.holdings); st.success("Portfolio saved permanently in Supabase.")
    if b.button("Reset sample holdings"):
        st.session_state.holdings = holdings_to_dataframe(SAMPLE_HOLDINGS); recompute_models(); st.rerun()
    c.download_button("Export holdings CSV", display.to_csv(index=False), "holdings_export.csv", "text/csv")


def upload_screenshots_page():
    st.header("Upload Holdings Screenshots")
    st.info("Screenshots are uploaded to the private Supabase Storage bucket, never to GitHub. They are visual references only; no OCR or broker connection is used.")
    files = st.file_uploader("Choose screenshots", type=["png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True, key="supabase_screenshots")
    storage = ScreenshotStorage(gateway, user_id)
    for index, image in enumerate(files):
        st.image(image, caption=image.name, width=380)
        if st.button(f"Save {image.name} privately", key=f"save_image_{index}_{image.name}"):
            path = storage.upload(image.name, image.getvalue(), image.type or "application/octet-stream")
            st.success(f"Saved in private Supabase Storage as {path}.")


def candidate_universe():
    st.header("Candidate Universe")
    st.info("TER, fund size, replication, domicile, distribution policy, spread, compatibility, and source details are manual-first. Missing critical data blocks buy/add recommendations.")
    scored = st.session_state.scored_candidates
    editable = st.session_state.candidates.copy()
    for column in ["quality_score", "momentum_score", "cost_score", "portfolio_fit_score",
                   "risk_control_score", "total_score", "data_confidence"]:
        if column in scored:
            editable[column] = scored[column].values
    display = editable.rename(columns=CANDIDATE_DISPLAY)
    edited = st.data_editor(display, num_rows="dynamic", width="stretch", hide_index=True, disabled=SCORE_COLUMNS,
        column_config={"Category": st.column_config.SelectboxColumn(options=SUPPORTED_CATEGORIES),
                       "Source URL": st.column_config.LinkColumn()}, key="candidate_editor")
    st.session_state.candidates = _normalise_candidates(edited.rename(columns={v: k for k, v in CANDIDATE_DISPLAY.items()}))
    recompute_models()
    upload = st.file_uploader("Import candidate universe CSV", type="csv", key="candidate_csv")
    if upload and st.button("Apply candidate CSV"):
        st.session_state.candidates = _normalise_candidates(pd.read_csv(upload)); recompute_models(); st.rerun()
    a, b, c = st.columns(3)
    if a.button("Save candidate universe to Supabase"):
        database.save_candidates(st.session_state.scored_candidates)
        st.success("Candidate universe and latest computed scores saved permanently in Supabase.")
    if b.button("Reset sample candidates"):
        st.session_state.candidates = _normalise_candidates(pd.DataFrame(SAMPLE_CANDIDATES)); recompute_models(); st.rerun()
    c.download_button("Export candidate universe CSV", st.session_state.candidates.to_csv(index=False), "candidate_universe_export.csv", "text/csv")


def market_research_dashboard():
    st.header("Market Research Dashboard")
    refresh_controls("research_refresh")
    current, candidates = st.session_state.scored_current, st.session_state.scored_candidates
    tables = [
        ("1. Best current holdings", current.sort_values("total_score", ascending=False).head(10)),
        ("2. Weakest current holdings", current.sort_values("total_score").head(10)),
        ("3. Best new candidate assets", candidates.sort_values("total_score", ascending=False).head(10)),
        ("4. Best assets for savings plan", candidates[candidates.get("savings_plan_available", False) == True].sort_values("total_score", ascending=False).head(10)),
        ("5. Assets to avoid", candidates[candidates["score_band"] == "Avoid / no buy"].sort_values("total_score")),
        ("6. Missing data / manual review required", candidates[candidates["manual_review_required"] == True])]
    for title, frame in tables:
        st.subheader(title)
        columns = [c for c in ["instrument", "category", "trend_status", "momentum_score", "quality_score",
                               "cost_score", "portfolio_fit_score", "total_score", "score_band",
                               "data_confidence", "data_source", "last_updated"] if c in frame]
        st.dataframe(frame[columns], width="stretch", hide_index=True)
    drift_chart = st.session_state.drift.melt(id_vars="category", value_vars=["current_weight", "target_weight"],
                                               var_name="Allocation", value_name="Weight %")
    st.plotly_chart(px.bar(drift_chart, x="category", y="Weight %", color="Allocation", barmode="group",
                           title="Current vs target allocation"), width="stretch")
    for score, title in [("total_score", "Candidate universe total score ranking"),
                         ("momentum_score", "Momentum score ranking"), ("quality_score", "Quality score ranking"),
                         ("cost_score", "Cost score ranking")]:
        chart = candidates.nlargest(15, score).sort_values(score)
        st.plotly_chart(px.bar(chart, x=score, y="instrument", orientation="h", title=title), width="stretch")


def asset_quality_dashboard():
    st.header("Asset Quality Dashboard")
    st.warning("Manual review required means the engine will not recommend a new buy/add. Complete facts from an official factsheet or licensed provider and record the source URL and date.")
    combined = pd.concat([st.session_state.scored_current, st.session_state.scored_candidates], ignore_index=True, sort=False)
    columns = [c for c in ["instrument", "asset_type", "category", "ter_pct", "fund_size_eur",
        "replication_method", "distribution_policy", "domicile", "manual_spread_estimate_pct",
        "liquidity_score", "quality_score", "quality_confidence", "manual_review_required",
        "missing_critical_data", "quality_reason", "data_source", "source_url", "last_updated"] if c in combined]
    st.dataframe(combined[columns].sort_values("quality_score", ascending=False), width="stretch", hide_index=True,
                 column_config={"source_url": st.column_config.LinkColumn("Source URL")})
    st.plotly_chart(px.bar(combined.nlargest(20, "quality_score").sort_values("quality_score"),
                           x="quality_score", y="instrument", orientation="h", title="Quality score ranking"), width="stretch")


def rebalance_engine():
    st.header("Rebalance Engine")
    st.warning("Decision support only. No broker connection or orders. Check live Scalable price before every execution.")
    recommendations, order = st.session_state.recommendations, recommendation_execution_order(st.session_state.recommendations)
    st.subheader("Market-aware recommendations")
    st.dataframe(recommendations, width="stretch", hide_index=True)
    st.subheader("Execution order")
    st.dataframe(order, width="stretch", hide_index=True)
    st.subheader("Allocation")
    st.dataframe(allocation_table(st.session_state.drift), width="stretch", hide_index=True)


def savings_plan_page():
    st.header("Savings Plan Optimizer")
    st.session_state.plans = st.data_editor(st.session_state.plans, num_rows="dynamic", width="stretch", hide_index=True,
                                            key="plans_editor")
    recompute_models()
    result = st.session_state.optimized_savings
    st.metric("Monthly budget", f"€{st.session_state.settings['monthly_savings_budget']:,.2f}")
    st.dataframe(result, width="stretch", hide_index=True)
    before = st.session_state.plans[["instrument", "current_plan"]].rename(columns={"instrument": "Instrument", "current_plan": "Amount"})
    before["Plan"] = "Before"
    after = result[["Instrument", "New plan"]].rename(columns={"New plan": "Amount"}); after["Plan"] = "After"
    chart = pd.concat([before, after], ignore_index=True)
    st.plotly_chart(px.bar(chart, x="Instrument", y="Amount", color="Plan", barmode="group",
                           title="Savings-plan allocation before vs after"), width="stretch")
    a, b = st.columns(2)
    if a.button("Save savings plans to Supabase"):
        current_lookup = st.session_state.plans.set_index("isin")["current_plan"].to_dict()
        persisted = result.rename(columns={"Instrument": "instrument", "ISIN": "isin",
            "New plan": "new_plan", "Action": "action", "Reason": "reason", "Score": "score"})
        persisted["current_plan"] = persisted["isin"].map(current_lookup).fillna(0.0)
        database.save_savings_plans(persisted)
        st.success("Savings plans and proposed changes saved permanently in Supabase.")
    b.download_button("Export optimized savings plans CSV", result.to_csv(index=False), "optimized_savings_plans.csv", "text/csv")


def recommendation_report_page():
    st.header("Recommendation Report")
    report = st.session_state.recommendation_report
    st.caption("Every recommendation includes source, timestamp, confidence, reason, and an execution-price warning.")
    st.dataframe(report, width="stretch", hide_index=True)
    a, b = st.columns(2)
    a.download_button("Export recommendation report CSV", report.to_csv(index=False), "recommendation_report.csv", "text/csv")
    if b.button("Save report to Supabase history"):
        database.save_recommendations(report); st.success("Recommendation report saved permanently in Supabase.")


def settings_page():
    st.header("Settings")
    s = st.session_state.settings
    a, b, c = st.columns(3)
    s["base_currency"] = a.selectbox("Base currency", ["EUR"])
    s["risk_profile"] = b.selectbox("Risk profile", ["Balanced", "Growth", "Aggressive"],
                                    index=["Balanced", "Growth", "Aggressive"].index(s["risk_profile"]))
    s["live_enabled"] = c.toggle("Enable live market data", value=s["live_enabled"])
    s["monthly_savings_budget"] = a.number_input("Monthly savings budget EUR", min_value=0.0, value=float(s["monthly_savings_budget"]))
    s["max_single_holding_weight"] = b.number_input("Max single holding weight %", min_value=0.0, value=float(s["max_single_holding_weight"]))
    s["max_crypto_weight"] = c.number_input("Max crypto weight %", min_value=0.0, value=float(s["max_crypto_weight"]))
    s["cash_min_pct"] = a.number_input("Cash target minimum %", min_value=0.0, value=float(s["cash_min_pct"]))
    s["cash_max_pct"] = b.number_input("Cash target maximum %", min_value=0.0, value=float(s["cash_max_pct"]))
    s["direct_trade_minimum"] = c.number_input("Direct trade minimum EUR", min_value=0.0, value=float(s["direct_trade_minimum"]))
    s["small_trade_round_trip_fee"] = a.number_input("Below-threshold round-trip fee EUR", min_value=0.0, value=float(s["small_trade_round_trip_fee"]))
    intervals = [60, 300, 600, 900]
    s["refresh_interval"] = b.selectbox("Data refresh interval", intervals, index=intervals.index(s["refresh_interval"]),
                                        format_func=lambda value: f"{value // 60} minute(s)")
    st.session_state.settings = s
    st.subheader("Target allocations")
    target_df = pd.DataFrame([{"Category": key, "Target weight %": value} for key, value in st.session_state.targets.items()])
    targets = st.data_editor(target_df, num_rows="dynamic", width="stretch", hide_index=True,
                             column_config={"Category": st.column_config.SelectboxColumn(options=SUPPORTED_CATEGORIES)})
    if st.button("Apply settings", type="primary"):
        st.session_state.targets = dict(zip(targets["Category"], targets["Target weight %"]))
        recompute_models()
        database.save_settings({**st.session_state.settings, "target_allocations": st.session_state.targets})
        total = sum(st.session_state.targets.values())
        (st.success if abs(total - 100) < .01 else st.warning)(f"Targets total {total:.2f}%.")
    st.info("Scalable Capital PRIME+: prefer EIX/gettex, avoid Xetra unless needed, use whole units for stocks/ETFs/ETCs/ETPs, and verify all final execution prices manually.")


user_id = require_authentication()
if not user_id:
    st.stop()
try:
    gateway = SupabaseGateway(get_supabase_client(user_id))
    database = Database(gateway, user_id)
    initialise_state(database)
except SupabaseConnectionError as exc:
    st.error(str(exc))
    st.info("Add SUPABASE_URL and SUPABASE_ANON_KEY to Streamlit secrets, then run supabase_schema.sql.")
    st.stop()

PAGES = ["Dashboard", "Valuation Dashboard", "Current Portfolio", "Upload Holdings Screenshots",
         "Candidate Universe", "Market Research Dashboard", "Asset Quality Dashboard", "Rebalance Engine",
         "Savings Plan Optimizer", "Recommendation Report", "Settings"]
with st.sidebar:
    st.title("Market-Aware Wealth Manager")
    page = st.radio("Navigation", PAGES)
    st.warning("Decision support only — never connects to Scalable Capital or places orders.")
    logout_button()

{"Dashboard": dashboard, "Valuation Dashboard": valuation_dashboard, "Current Portfolio": current_portfolio,
 "Upload Holdings Screenshots": upload_screenshots_page,
 "Candidate Universe": candidate_universe, "Market Research Dashboard": market_research_dashboard,
 "Asset Quality Dashboard": asset_quality_dashboard, "Rebalance Engine": rebalance_engine,
 "Savings Plan Optimizer": savings_plan_page, "Recommendation Report": recommendation_report_page,
 "Settings": settings_page}[page]()
