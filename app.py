"""Production-style Streamlit wealth manager backed by Supabase."""

from datetime import datetime
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import logout_button, require_authentication
from db import Database
from market_data import get_fx_rate_to_eur, get_market_quote
from market_data_engine import MarketDataEngine
from market_research import build_market_research
from master_rebalance import run_full_rebalance_pipeline
from metadata_enrichment import accept_suggestion
from news_provider import get_market_news, rank_news_by_relevance
from optimizer import generate_market_aware_recommendations, recommendation_execution_order
from recommendation_engine import build_recommendation_report
from rebalancer import (allocation_table, calculate_allocation, calculate_drift, calculate_total_invested,
                        calculate_total_value, calculate_unrealised_pl, holdings_to_dataframe,
                        savings_plans_to_dataframe)
from sample_data import (CANDIDATE_COLUMNS, SAMPLE_CANDIDATES, SAMPLE_HOLDINGS, SAMPLE_SAVINGS_PLANS,
                         SUPPORTED_CATEGORIES, TARGET_ALLOCATIONS)
from savings_plan_optimizer import optimize_savings_plans
from savings_plan_manager import (create_savings_plan_execution_checklist,
                                  normalize_savings_plan_rows, validate_savings_plan_budget)
from screenshot_parser import (create_holding_from_screenshot_data, parse_scalable_text,
                               update_holding_by_isin, validate_screenshot_holding)
from scoring import score_assets
from sentiment_engine import classify_sentiment, create_market_sentiment_summary
from storage import ScreenshotStorage
from strategy_engine import (create_strategy_explanation, get_current_strategy,
                             refresh_market_strategy)
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
    return get_market_quote(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fx(currency: str, bucket: int):
    rate = get_fx_rate_to_eur(currency)
    return rate, "" if rate else "FX rate unavailable"


def _normalise_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    numeric = ["ter_pct", "fund_size_eur", "manual_spread_estimate_pct", "liquidity_score",
               "quality_score", "momentum_score", "valuation_score", "cost_score",
               "portfolio_fit_score", "risk_control_score", "total_score"]
    booleans = ["savings_plan_available", "direct_trading_available", "fractional_allowed", "scalable_compatible",
                "valuation_ready", "recommendation_ready", "confirmed_by_user", "manual_review_attempted"]
    json_columns = ["provider_status", "enrichment_audit", "web_scrape_sources", "metadata_conflicts",
                    "enrichment_suggestions", "suggested_price_symbols"]
    for column in CANDIDATE_COLUMNS:
        if column not in frame:
            frame[column] = None if column in numeric else False if column in booleans else [] if column in json_columns else ""
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in booleans:
        frame[column] = frame[column].fillna(False).astype(bool)
    for column in json_columns:
        frame[column] = frame[column].apply(lambda value: value if isinstance(value, (dict, list)) else [])
    for column in set(CANDIDATE_COLUMNS) - set(numeric) - set(booleans) - set(json_columns):
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
                    "live_enabled": True, "scraping_enabled": True, "news_enabled": True,
                    "rate_limit_seconds": 0.25, "refresh_interval": 300, "risk_profile": "Aggressive"}
    app_settings.update({key: value for key, value in saved_settings.items() if key in app_settings})
    defaults = {
        "holdings": db_holdings if not db_holdings.empty else holdings_to_dataframe(SAMPLE_HOLDINGS),
        "candidates": _normalise_candidates(db_candidates if not db_candidates.empty else pd.DataFrame(SAMPLE_CANDIDATES)),
        "targets": saved_settings.get("target_allocations", TARGET_ALLOCATIONS.copy()),
        "quotes": {}, "fx_rates": {"EUR": 1.0},
        "last_price_fetch": None, "enrichment_audit": pd.DataFrame(), "enrichment_warnings": [],
        "provider_status": [],
        "news_items": [], "sentiment": {"sentiment": "Neutral", "market_regime": "Neutral",
                                           "confidence": "Low", "explanation": "News has not been refreshed yet."},
        "settings": app_settings}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "plans" not in st.session_state:
        raw_plans = db_plans if not db_plans.empty else pd.DataFrame(SAMPLE_SAVINGS_PLANS)
        st.session_state.plans = _plans_with_categories(raw_plans)
    recompute_models()
    if "strategy" not in st.session_state:
        st.session_state.strategy = get_current_strategy(st.session_state.settings, st.session_state.targets,
                                                         st.session_state.holdings, st.session_state.candidates)


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
    optimizer_settings["news_sentiment"] = st.session_state.get("sentiment", {}).get("sentiment", "Neutral")
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
        st.warning("Live price unavailable; run Data Enrichment, then use manual fallback after failed enrichment: " + ", ".join(failed))


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
    left.plotly_chart(px.line(market_history, x="date", y="portfolio_value_eur", title="Portfolio live value over time"), width="stretch", key="valuation_history_chart")
    allocation = calculate_allocation(details)
    right.plotly_chart(px.pie(allocation, names="category", values="value", hole=.4, title="Current allocation"), width="stretch", key="valuation_allocation_chart")
    comparison = st.session_state.drift.melt(id_vars="category",
        value_vars=["current_weight", "target_weight"], var_name="Allocation", value_name="Weight %")
    st.plotly_chart(px.bar(comparison, x="category", y="Weight %", color="Allocation", barmode="group",
                           title="Current vs target allocation"), width="stretch", key="valuation_target_chart")
    missing = details[details["price_source"] == "Missing"]
    fallback = details[(details["price_source"] == "Manual fallback") & (details["category"] != "Cash")]
    if not missing.empty:
        st.warning("Missing live and manual prices: " + ", ".join(missing["instrument"]))
    if not fallback.empty:
        st.warning("Live price unavailable, using manual price: " + ", ".join(fallback["instrument"]))
    chart_left, chart_right = st.columns(2)
    holdings_chart = details.sort_values("current_value_eur")
    chart_left.plotly_chart(px.bar(holdings_chart, x="current_value_eur", y="instrument", orientation="h",
                                   title="Holdings value"), width="stretch", key="valuation_holdings_chart")
    winners = details.sort_values("daily_gain_eur")
    chart_right.plotly_chart(px.bar(winners, x="instrument", y="daily_gain_eur", color="daily_gain_eur",
                                    title="Daily winners and losers",
                                    color_continuous_scale=["#B91C1C", "#E5E7EB", "#15803D"]), width="stretch", key="valuation_winners_chart")
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
    invested = calculate_total_invested(details)
    profit = calculate_unrealised_pl(details)
    cash = float(details.loc[details["category"] == "Cash", "current_value_eur"].sum())
    columns = st.columns(6)
    columns[0].metric("Portfolio value", f"€{total:,.2f}")
    columns[1].metric("Invested value", f"€{invested:,.2f}")
    columns[2].metric("Unrealised P/L", f"€{profit:+,.2f}", f"{profit / invested * 100:+.2f}%" if invested else None)
    columns[3].metric("Cash", f"€{cash:,.2f}")
    columns[4].metric("Holdings", len(details))
    columns[5].metric("Candidates", len(st.session_state.candidates))
    left, right = st.columns(2)
    allocation = calculate_allocation(details)
    left.plotly_chart(px.pie(allocation, names="category", values="value", hole=.4,
                              title="Current allocation"), width="stretch", key="dashboard_allocation_chart")
    drift_chart = st.session_state.drift.melt(id_vars="category",
        value_vars=["current_weight", "target_weight"], var_name="Allocation", value_name="Weight %")
    right.plotly_chart(px.bar(drift_chart, x="category", y="Weight %", color="Allocation",
                              barmode="group", title="Current vs target"), width="stretch", key="dashboard_target_chart")
    st.subheader("Highest-priority recommendations")
    order = recommendation_execution_order(st.session_state.recommendations)
    st.dataframe(order.head(10), width="stretch", hide_index=True)


def current_portfolio():
    st.header("Current Portfolio")
    st.caption("Portfolio data is stored in Supabase after you click save. No broker connection is used.")
    refresh_controls("portfolio_refresh")
    existing = st.session_state.holdings.copy()
    display = existing[[column for column in HOLDING_DISPLAY if column in existing]].rename(columns=HOLDING_DISPLAY)
    edited = st.data_editor(display, num_rows="dynamic", width="stretch", hide_index=True,
        disabled=["Live current price", "Price source", "Current value EUR", "P/L EUR", "P/L %"],
        column_config={"Category": st.column_config.SelectboxColumn(options=SUPPORTED_CATEGORIES)}, key="current_editor")
    edited_rows = edited.rename(columns={v: k for k, v in HOLDING_DISPLAY.items()}).to_dict("records")
    old_lookup = {str(row.get("isin")): row for row in existing.to_dict("records")}
    merged_rows = []
    for row in edited_rows:
        saved = old_lookup.get(str(row.get("isin")), {})
        merged_rows.append({**saved, **row})
    st.session_state.holdings = holdings_to_dataframe(merged_rows)
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
    st.info("The Market Data Engine attempts free enrichment first. Unresolved or conflicting facts move to manual fallback after failed enrichment; incomplete candidates remain blocked from buy/add.")
    refresh_controls("candidate_refresh")
    scored = st.session_state.scored_candidates
    editable = st.session_state.candidates.copy()
    for column in ["quality_score", "momentum_score", "cost_score", "portfolio_fit_score",
                   "risk_control_score", "total_score", "data_confidence"]:
        if column in scored:
            editable[column] = scored[column].values
    advanced = {"provider_status", "enrichment_audit", "web_scrape_sources", "metadata_conflicts",
                "enrichment_suggestions", "suggested_price_symbols", "valuation_review_reasons",
                "recommendation_review_reasons"}
    editor_columns = [column for column in CANDIDATE_COLUMNS if column not in advanced]
    display = editable[editor_columns].rename(columns=CANDIDATE_DISPLAY)
    edited = st.data_editor(display, num_rows="dynamic", width="stretch", hide_index=True, disabled=SCORE_COLUMNS,
        column_config={"Category": st.column_config.SelectboxColumn(options=SUPPORTED_CATEGORIES),
                       "Source URL": st.column_config.LinkColumn()}, key="candidate_editor")
    edited_internal = edited.rename(columns={v: k for k, v in CANDIDATE_DISPLAY.items()})
    old_lookup = {str(row.get("isin")): row for row in st.session_state.candidates.to_dict("records")}
    records = [{**old_lookup.get(str(row.get("isin")), {}), **row} for row in edited_internal.to_dict("records")]
    st.session_state.candidates = _normalise_candidates(pd.DataFrame(records))
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
        ("6. Missing data / enrichment or review required", candidates[candidates["manual_review_required"] == True])]
    for title, frame in tables:
        st.subheader(title)
        columns = [c for c in ["instrument", "category", "trend_status", "momentum_score", "quality_score",
                               "cost_score", "portfolio_fit_score", "total_score", "score_band",
                               "data_confidence", "data_source", "last_updated"] if c in frame]
        st.dataframe(frame[columns], width="stretch", hide_index=True)
    drift_chart = st.session_state.drift.melt(id_vars="category", value_vars=["current_weight", "target_weight"],
                                               var_name="Allocation", value_name="Weight %")
    st.plotly_chart(px.bar(drift_chart, x="category", y="Weight %", color="Allocation", barmode="group",
                           title="Current vs target allocation"), width="stretch", key="research_target_chart")
    for score, title in [("total_score", "Candidate universe total score ranking"),
                         ("momentum_score", "Momentum score ranking"), ("quality_score", "Quality score ranking"),
                         ("cost_score", "Cost score ranking")]:
        chart = candidates.nlargest(15, score).sort_values(score)
        st.plotly_chart(px.bar(chart, x=score, y="instrument", orientation="h", title=title), width="stretch", key=f"research_{score}_chart")


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
                           x="quality_score", y="instrument", orientation="h", title="Quality score ranking"), width="stretch", key="quality_ranking_chart")


def rebalance_engine():
    st.header("Rebalance Engine")
    st.warning("Decision support only. No broker connection or orders. Check live Scalable price before every execution.")
    recommendations, order = st.session_state.recommendations, recommendation_execution_order(st.session_state.recommendations)
    if recommendations["Reason"].astype(str).str.contains("insufficient|cash", case=False, regex=True).any():
        st.warning("Cash shortfall: lower-priority buys were reduced or deferred.")
    if recommendations["Fee issue"].astype(str).str.contains("Below", case=False).any():
        st.warning("Fee inefficiency: trades below the configured minimum should normally use a savings plan.")
    if recommendations["Purpose"].astype(str).str.contains("Manual review", case=False).any():
        st.warning("Manual review required: incomplete assets are blocked from buy/add recommendations.")
    st.subheader("Market-aware recommendations")
    st.dataframe(recommendations, width="stretch", hide_index=True)
    st.subheader("Execution order")
    st.dataframe(order, width="stretch", hide_index=True)
    st.subheader("Allocation")
    st.dataframe(allocation_table(st.session_state.drift), width="stretch", hide_index=True)


def savings_plan_page():
    st.header("Savings Plan Optimizer")
    st.warning("These changes are saved in this app only. You must manually update the actual savings plans in Scalable Capital.")
    st.session_state.plans = st.data_editor(st.session_state.plans, num_rows="dynamic", width="stretch", hide_index=True,
                                            key="plans_editor")
    recompute_models()
    result = st.session_state.optimized_savings
    st.metric("Monthly budget", f"€{st.session_state.settings['monthly_savings_budget']:,.2f}")
    st.dataframe(result, width="stretch", hide_index=True)
    budget_check = validate_savings_plan_budget(result, st.session_state.settings["monthly_savings_budget"])
    if not budget_check["valid"]:
        st.warning(f"Optimizer total differs from the monthly budget by €{budget_check['difference']:+,.2f}.")
    before = st.session_state.plans[["instrument", "current_plan"]].rename(columns={"instrument": "Instrument", "current_plan": "Amount"})
    before["Plan"] = "Before"
    after = result[["Instrument", "New plan"]].rename(columns={"New plan": "Amount"}); after["Plan"] = "After"
    chart = pd.concat([before, after], ignore_index=True)
    st.plotly_chart(px.bar(chart, x="Instrument", y="Amount", color="Plan", barmode="group",
                           title="Savings-plan allocation before vs after"), width="stretch", key="savings_before_after_chart")
    checklist = create_savings_plan_execution_checklist(st.session_state.plans, result)
    a, b, c, d = st.columns(4)
    if a.button("Save savings plans to Supabase"):
        current_lookup = st.session_state.plans.set_index("isin")["current_plan"].to_dict()
        persisted = result.rename(columns={"Instrument": "instrument", "ISIN": "isin",
            "New plan": "new_plan", "Action": "action", "Reason": "reason", "Score": "score"})
        persisted["current_plan"] = persisted["isin"].map(current_lookup).fillna(0.0)
        database.save_savings_plans(persisted)
        st.success("Savings plans and proposed changes saved permanently in Supabase.")
    if b.button("Apply optimizer recommendation"):
        applied = normalize_savings_plan_rows(result)
        applied["current_plan"] = applied["new_plan"]
        st.session_state.plans = _plans_with_categories(applied)
        recompute_models(); st.success("Recommendations applied to app records. Save to persist them.")
    if c.button("Reset to current saved plans"):
        saved = database.load_savings_plans()
        st.session_state.plans = _plans_with_categories(saved if not saved.empty else pd.DataFrame(SAMPLE_SAVINGS_PLANS))
        recompute_models(); st.rerun()
    d.download_button("Export Scalable execution checklist CSV", checklist.to_csv(index=False),
                      "scalable_savings_plan_checklist.csv", "text/csv")


def recommendation_report_page():
    st.header("Recommendation Report")
    report = st.session_state.recommendation_report
    st.caption("Every recommendation includes source, timestamp, confidence, reason, and an execution-price warning.")
    st.dataframe(report, width="stretch", hide_index=True)
    a, b = st.columns(2)
    a.download_button("Export recommendation report CSV", report.to_csv(index=False), "recommendation_report.csv", "text/csv")
    if b.button("Save report to Supabase history"):
        database.save_recommendations(report); st.success("Recommendation report saved permanently in Supabase.")


def _run_data_enrichment(force_web: bool = False, selected_isin: str | None = None,
                         target: str = "all"):
    """Run the free/no-key waterfall and keep every attempt visible in the audit."""
    settings = st.session_state.settings
    if not settings.get("live_enabled", True):
        st.session_state.enrichment_warnings = [
            "Live Market Data is explicitly disabled in Settings; enrichment was not run."
        ]
        return
    engine = MarketDataEngine(settings.get("scraping_enabled", True), settings.get("rate_limit_seconds", .25))
    holdings = st.session_state.holdings
    candidates = st.session_state.candidates
    if selected_isin:
        holding_mask = holdings["isin"].astype(str) == selected_isin
        candidate_mask = candidates["isin"].astype(str) == selected_isin
        if holding_mask.any():
            enriched, audit = engine.enrich_assets(holdings.loc[holding_mask], False, force_web)
            replacement = enriched.iloc[0].to_dict()
            records = [replacement if str(row.get("isin")) == selected_isin else row
                       for row in holdings.to_dict("records")]
            holdings = pd.DataFrame(records)
        elif candidate_mask.any():
            enriched, audit = engine.enrich_assets(candidates.loc[candidate_mask], True, force_web)
            replacement = enriched.iloc[0].to_dict()
            records = [replacement if str(row.get("isin")) == selected_isin else row
                       for row in candidates.to_dict("records")]
            candidates = pd.DataFrame(records)
        else:
            return
    else:
        holding_audit, candidate_audit = pd.DataFrame(), pd.DataFrame()
        if target in {"all", "holdings"}:
            holdings, holding_audit = engine.enrich_assets(holdings, False, force_web)
        if target in {"all", "candidates"}:
            candidates, candidate_audit = engine.enrich_assets(candidates, True, force_web)
        audit = pd.concat([holding_audit, candidate_audit], ignore_index=True)
    st.session_state.holdings = holdings_to_dataframe(holdings.to_dict("records"))
    st.session_state.candidates = _normalise_candidates(candidates)
    st.session_state.enrichment_audit = audit
    st.session_state.enrichment_warnings = engine.warnings
    st.session_state.provider_status = engine.provider_status_rows(settings.get("news_enabled", True))
    recompute_models()


def _refresh_news_and_strategy(redesign: bool = False):
    items = get_market_news() if st.session_state.settings.get("news_enabled", True) else []
    items = rank_news_by_relevance(items, st.session_state.holdings, st.session_state.candidates,
                                   st.session_state.strategy)
    for item in items:
        item.update(classify_sentiment(item.get("title", "") + " " + item.get("summary", "")))
    sentiment = create_market_sentiment_summary(items, st.session_state.research)
    st.session_state.news_items, st.session_state.sentiment = items, sentiment
    try:
        database.save_news(items)
    except SupabaseConnectionError as exc:
        st.session_state.enrichment_warnings.append(f"News snapshot was not saved: {exc}")
    if redesign:
        st.session_state.strategy = refresh_market_strategy(
            st.session_state.holdings, st.session_state.candidates, st.session_state.targets,
            sentiment, st.session_state.research, st.session_state.settings)
    return items


def screenshot_workflow():
    st.subheader("Upload Scalable screenshot")
    st.info("Screenshots are stored privately in Supabase Storage. Paste the visible text for deterministic parsing, then confirm every field before saving.")
    image = st.file_uploader("Screenshot", type=["png", "jpg", "jpeg", "webp"], key="command_screenshot")
    if image:
        st.image(image, caption=image.name, width=420)
    text = st.text_area("Paste visible screenshot text", height=180,
                        placeholder="Instrument, ISIN, WKN, shares, value, buy-in, P/L, sell and buy prices")
    if st.button("Parse pasted text", disabled=not text):
        st.session_state.screenshot_draft = parse_scalable_text(text)
    draft = st.session_state.get("screenshot_draft", {})
    if draft:
        left, right = st.columns(2)
        draft["instrument"] = left.text_input("Instrument", value=str(draft.get("instrument", "")))
        draft["isin"] = right.text_input("ISIN", value=str(draft.get("isin", "")))
        draft["wkn"] = left.text_input("WKN", value=str(draft.get("wkn", "")))
        draft["quantity"] = right.number_input("Quantity", min_value=0.0, value=float(draft.get("quantity") or 0))
        for field, label in [("current_value_eur", "Current position value EUR"),
                             ("buy_in_value_eur", "Buy-in value EUR"),
                             ("current_price_eur", "Current price per share EUR"),
                             ("buy_in_price_eur", "Buy-in price per share EUR"),
                             ("pl_eur", "P/L EUR"), ("pl_pct", "P/L %"),
                             ("sell_price_eur", "Sell price EUR"), ("buy_price_eur", "Buy price EUR")]:
            draft[field] = left.number_input(label, value=float(draft.get(field) or 0), key=f"shot_{field}")
        confirmed = st.checkbox("I reviewed and confirmed these screenshot fields")
        if st.button("Save or update holding by ISIN", type="primary", disabled=not confirmed):
            errors = validate_screenshot_holding(draft)
            if errors:
                st.error("; ".join(errors))
            else:
                holding = create_holding_from_screenshot_data(draft)
                if image:
                    holding["screenshot_path"] = ScreenshotStorage(gateway, user_id).upload(
                        image.name, image.getvalue(), image.type or "application/octet-stream")
                rows = update_holding_by_isin(st.session_state.holdings.to_dict("records"), holding)
                st.session_state.holdings = holdings_to_dataframe(rows)
                database.save_holdings(st.session_state.holdings)
                recompute_models(); st.success("Confirmed holding saved to Supabase.")


def portfolio_section():
    st.title("Portfolio Command Center")
    if st.button("Refresh all prices and metadata", type="primary"):
        with st.spinner("Refreshing prices, FX, identifiers, and available metadata..."):
            refresh_live_data(True)
            _run_data_enrichment(False)
        st.rerun()
    tabs = st.tabs(["Dashboard", "Current holdings", "Holding screenshot upload",
                    "Live valuation", "Valuation snapshots"])
    with tabs[0]: dashboard()
    with tabs[1]: current_portfolio()
    with tabs[2]: screenshot_workflow()
    with tabs[3]: valuation_dashboard()
    with tabs[4]:
        history = database.load_snapshots()
        st.subheader("Valuation snapshots")
        st.dataframe(history, width="stretch", hide_index=True)
        st.download_button("Export valuation snapshots CSV", history.to_csv(index=False),
                           "valuation_history.csv", "text/csv")


def _missing_data_frame() -> pd.DataFrame:
    combined = pd.concat([st.session_state.holdings.assign(dataset="Holding"),
                          st.session_state.candidates.assign(dataset="Candidate")],
                         ignore_index=True, sort=False)
    checks = {"price_symbol": "Price symbol", "ter_pct": "TER/cost", "asset_type": "Asset type",
              "category": "Category", "factsheet_url": "Factsheet URL",
              "scalable_compatible": "Scalable compatibility"}
    rows = []
    def missing_value(value):
        if value is None or value is False or value == "": return True
        try: return bool(pd.isna(value))
        except (TypeError, ValueError): return False
    for _, asset in combined.iterrows():
        missing = []
        for field, label in checks.items():
            value = asset.get(field)
            fund_only = field == "ter_pct" and str(asset.get("asset_type")) not in {"ETF", "ETC", "ETP"}
            candidate_only = field == "scalable_compatible" and asset.get("dataset") != "Candidate"
            if not fund_only and not candidate_only and missing_value(value):
                missing.append(label)
        if asset.get("metadata_conflicts"): missing.append("Conflicting metadata")
        if str(asset.get("web_scrape_status", "")).lower() == "failed": missing.append("Failed web scrape")
        if missing:
            rows.append({"Dataset": asset.get("dataset"), "Instrument": asset.get("instrument"),
                         "ISIN": asset.get("isin"), "Missing / repair needed": ", ".join(missing),
                         "Last auto repair": asset.get("last_auto_repair_at", "")})
    return pd.DataFrame(rows)


def _replace_asset(dataset: str, isin: str, updated: dict):
    if dataset == "Holding":
        records = [updated if str(row.get("isin")) == isin else row
                   for row in st.session_state.holdings.to_dict("records")]
        st.session_state.holdings = holdings_to_dataframe(records)
        database.save_holdings(st.session_state.holdings)
    else:
        records = [updated if str(row.get("isin")) == isin else row
                   for row in st.session_state.candidates.to_dict("records")]
        st.session_state.candidates = _normalise_candidates(pd.DataFrame(records))
        database.save_candidates(st.session_state.candidates)
    recompute_models()


def market_data_news_section():
    st.title("Market Data & News")
    st.warning("Web-scraped data may be incomplete or outdated. Confirm important data from issuer factsheet before investing.")
    engine = MarketDataEngine(st.session_state.settings.get("scraping_enabled", True),
                              st.session_state.settings.get("rate_limit_seconds", .25))
    tabs = st.tabs(["Market Data Engine", "Internet Enrichment Center", "Candidate assets",
                    "Market research", "Asset quality", "Latest market news", "Market sentiment",
                    "Missing Data Repair Center", "Scraping audit"])
    with tabs[0]:
        st.subheader("Provider status")
        provider_rows = st.session_state.provider_status or engine.provider_status_rows(
            st.session_state.settings.get("news_enabled", True))
        st.dataframe(pd.DataFrame(provider_rows),
                     width="stretch", hide_index=True)
        st.caption("Free/no-key priority: yfinance → OpenFIGI → ECB → optional CoinGecko → safe web enrichment → manual fallback after failed enrichment.")
    with tabs[1]:
        ready_h = st.session_state.holdings
        ready_c = st.session_state.candidates
        cards = st.columns(4)
        cards[0].metric("Valuation ready", int(ready_h.get("valuation_ready", pd.Series(False)).fillna(False).sum()))
        cards[1].metric("Recommendation ready", int(ready_c.get("recommendation_ready", pd.Series(False)).fillna(False).sum()))
        unresolved = ~ready_c.get("recommendation_ready", pd.Series(False)).fillna(False)
        attempted = ready_c.get("manual_review_attempted", pd.Series(False)).fillna(False)
        cards[2].metric("Manual review after enrichment", int((unresolved & attempted).sum()))
        cards[3].metric("Missing price symbol", int((ready_c.get("price_symbol", pd.Series(dtype=str)).fillna("") == "").sum()))
        extra_cards = st.columns(2)
        fund_mask = ready_c.get("asset_type", pd.Series(dtype=str)).isin(["ETF", "ETC", "ETP"])
        extra_cards[0].metric("Missing TER/cost", int((fund_mask & ready_c.get("ter_pct", pd.Series(dtype=float)).isna()).sum()))
        extra_cards[1].metric("Missing Scalable confirmation", int((~ready_c.get("scalable_compatible", pd.Series(False)).fillna(False)).sum()))
        a, b, c = st.columns(3)
        if a.button("Enrich holdings using free data"):
            with st.spinner("Running market-data waterfall for holdings..."): _run_data_enrichment(False, target="holdings")
            st.rerun()
        if b.button("Enrich candidates using free data"):
            with st.spinner("Running market-data waterfall for candidates..."): _run_data_enrichment(False, target="candidates")
            st.rerun()
        if c.button("Force enrich all missing ISIN data", type="primary"):
            with st.spinner("Searching and safely scraping ranked public sources..."): _run_data_enrichment(True)
            st.rerun()
        for warning in st.session_state.enrichment_warnings: st.warning(warning)
        if st.button("Retry failed enrichment"):
            with st.spinner("Retrying unresolved assets through the full waterfall..."): _run_data_enrichment(True)
            st.rerun()
    with tabs[2]: candidate_universe()
    with tabs[3]: market_research_dashboard()
    with tabs[4]: asset_quality_dashboard()
    with tabs[5]:
        if st.button("Refresh news"):
            with st.spinner("Fetching public RSS and market headlines..."): _refresh_news_and_strategy(False)
        news = pd.DataFrame(st.session_state.news_items)
        if news.empty: st.info("No usable public headlines are cached yet.")
        else:
            columns = [c for c in ["title", "source", "published_at", "category", "sentiment", "confidence", "url"] if c in news]
            st.dataframe(news[columns], width="stretch", hide_index=True,
                         column_config={"url": st.column_config.LinkColumn("Link")})
    with tabs[6]:
        sentiment = st.session_state.sentiment
        st.metric("Market sentiment", sentiment.get("sentiment", "Neutral"))
        st.metric("Market regime", sentiment.get("market_regime", "Neutral"))
        st.write(sentiment.get("explanation", "")); st.caption("Confidence: " + sentiment.get("confidence", "Low"))
        if st.button("Use news in strategy refresh"):
            _refresh_news_and_strategy(True); st.success("Strategy refreshed using the available evidence.")
    with tabs[7]:
        missing = _missing_data_frame()
        st.dataframe(missing, width="stretch", hide_index=True)
        if not missing.empty:
            selected = st.selectbox("Asset to repair", missing["ISIN"].astype(str).tolist(),
                                    format_func=lambda value: missing.loc[missing["ISIN"].astype(str) == value, "Instrument"].iloc[0])
            selected_summary = missing.loc[missing["ISIN"].astype(str) == selected].iloc[0]
            dataset = selected_summary["Dataset"]
            source_frame = st.session_state.holdings if dataset == "Holding" else st.session_state.candidates
            asset = source_frame.loc[source_frame["isin"].astype(str) == selected].iloc[0].to_dict()
            a, b = st.columns(2)
            if a.button("Auto repair now", type="primary"):
                with st.spinner("Trying every enabled free enrichment route..."): _run_data_enrichment(True, selected)
                st.rerun()
            if b.button("Search web and retry"):
                with st.spinner("Searching source-ranked public pages..."): _run_data_enrichment(True, selected)
                st.rerun()
            suggestions = asset.get("enrichment_suggestions") if isinstance(asset.get("enrichment_suggestions"), dict) else {}
            if suggestions:
                suggestion_field = st.selectbox("Suggested field", list(suggestions), key="repair_suggestion_field")
                st.json(suggestions[suggestion_field])
                if st.button("Accept suggested value"):
                    _replace_asset(dataset, selected, accept_suggestion(asset, suggestion_field)); st.rerun()
            manual_fields = ["price_symbol", "ter_pct", "asset_type", "category", "factsheet_url",
                             "scalable_compatible", "issuer", "currency"]
            field = st.selectbox("Enter a confirmed value for", manual_fields, key="repair_manual_field")
            manual_value = st.text_input("Confirmed value", key="repair_manual_value")
            confirmed = st.checkbox("Mark confirmed", key="repair_confirmed")
            if st.button("Save confirmed value", disabled=not (manual_value and confirmed)):
                updated = dict(asset)
                if field == "ter_pct":
                    try: updated[field] = float(manual_value.replace(",", "."))
                    except ValueError: st.error("Enter TER as a number, for example 0.20"); st.stop()
                elif field == "scalable_compatible":
                    updated[field] = manual_value.strip().lower() in {"true", "yes", "1", "confirmed"}
                else: updated[field] = manual_value.strip()
                updated["confirmed_by_user"] = True
                _replace_asset(dataset, selected, updated); st.rerun()
            st.caption("Suggested values are retained separately when they conflict with user-entered data; confirmation is required before replacement.")
    with tabs[8]:
        audit = st.session_state.enrichment_audit
        st.dataframe(audit, width="stretch", hide_index=True)
        st.download_button("Export enrichment audit CSV", audit.to_csv(index=False),
                           "enrichment_audit.csv", "text/csv")


def strategy_section():
    st.title("Strategy")
    strategy = st.session_state.strategy
    st.subheader(strategy.get("strategy_name", "Current strategy"))
    cards = st.columns(3)
    cards[0].metric("Market regime", strategy.get("market_regime", "Neutral"))
    cards[1].metric("Risk profile", strategy.get("risk_profile", "Aggressive"))
    cards[2].metric("Confidence", strategy.get("confidence", "Low"))
    st.write(create_strategy_explanation(strategy))
    left, right = st.columns(2)
    left.write("Preferred themes: " + (", ".join(strategy.get("preferred_themes", [])) or "None confirmed"))
    right.write("Reduced themes: " + (", ".join(strategy.get("reduced_themes", [])) or "None confirmed"))
    st.write("Current risks: " + ("; ".join(strategy.get("current_risks", [])) or "No additional evidence-backed risks."))
    st.write("Savings-plan priorities: " + (", ".join(strategy.get("savings_plan_priorities", [])) or "Follow underweight categories and score quality."))
    st.write("Rebalance implications: " + "; ".join(strategy.get("rebalance_rules", [])))
    st.caption("Latest refresh: " + str(strategy.get("timestamp", "Not refreshed")))
    st.subheader("Target allocation")
    st.dataframe(pd.DataFrame(strategy.get("target_allocations", st.session_state.targets).items(),
                              columns=["Category", "Target %"]), hide_index=True, width="stretch")
    a, b, c = st.columns(3)
    if a.button("Refresh market news and sentiment"):
        _refresh_news_and_strategy(False); st.rerun()
    if b.button("Redesign strategy using latest market data", type="primary"):
        _refresh_news_and_strategy(True); st.rerun()
    if c.button("Save strategy snapshot"):
        database.save_strategy_snapshot(strategy); st.success("Strategy snapshot saved to Supabase.")
    history = database.load_strategy_snapshots()
    st.subheader("Strategy history")
    st.dataframe(history, width="stretch", hide_index=True)


def _save_current_valuation_snapshot():
    details = st.session_state.valuation_details
    total = calculate_total_value(details); history = database.load_snapshots()
    gains = calculate_historical_gains(total, history); now = datetime.now().astimezone()
    snapshot = {"date": now.date().isoformat(), "timestamp": now.isoformat(timespec="seconds"),
        "total_value_eur": total,
        "cash_eur": float(details.loc[details["category"] == "Cash", "current_value_eur"].sum()),
        "invested_value_eur": calculate_total_invested(details),
        "unrealized_pl_eur": calculate_unrealised_pl(details)}
    for period in ["daily", "weekly", "monthly", "yearly"]:
        snapshot[f"{period}_gain_eur"] = gains[period]["eur"] if gains[period] else None
        snapshot[f"{period}_gain_pct"] = gains[period]["pct"] if gains[period] else None
    database.save_snapshot(snapshot)
    return snapshot


def rebalance_section():
    st.title("Rebalance")
    st.warning("Decision support only. No broker connection, orders, or savings-plan updates. Check live Scalable price before execution.")
    st.session_state.market_reasoning_notes = st.text_area(
        "Short market reasoning notes",
        value=st.session_state.get("market_reasoning_notes", ""),
        placeholder="Add your own interpretation, constraints, tax notes, or reasons to defer execution.")
    if st.button("Run full rebalance", type="primary", use_container_width=True):
        progress = st.progress(0, "Starting Market Data Engine...")
        def progress_step(name, fraction, function):
            def wrapped(results):
                progress.progress(fraction, name.replace("_", " ").title())
                return function(results)
            return wrapped
        steps = {
            "refresh_prices": progress_step("refresh_prices", .06, lambda _: refresh_live_data(True)),
            "enrich_assets": progress_step("enrich_assets", .13, lambda _: _run_data_enrichment(False)),
            "repair_missing_metadata": progress_step("repair_missing_metadata", .20, lambda _: _run_data_enrichment(True)),
            "fetch_news": progress_step("fetch_news", .28, lambda _: _refresh_news_and_strategy(False)),
            "calculate_sentiment": progress_step("calculate_sentiment", .35, lambda _: st.session_state.sentiment),
            "redesign_strategy": progress_step("redesign_strategy", .42, lambda _: _refresh_news_and_strategy(True)),
            "recalculate_valuation": progress_step("recalculate_valuation", .50, lambda _: recompute_models()),
            "recalculate_drift": progress_step("recalculate_drift", .57, lambda _: st.session_state.drift.to_dict("records")),
            "score_assets": progress_step("score_assets", .64, lambda _: recompute_models()),
            "run_portfolio_optimizer": progress_step("run_portfolio_optimizer", .71, lambda _: st.session_state.recommendations.to_dict("records")),
            "run_savings_optimizer": progress_step("run_savings_optimizer", .78, lambda _: st.session_state.optimized_savings.to_dict("records")),
            "create_report": progress_step("create_report", .85, lambda _: st.session_state.recommendation_report.to_dict("records")),
            "create_execution_checklist": progress_step("create_execution_checklist", .92, lambda _: create_savings_plan_execution_checklist(st.session_state.plans, st.session_state.optimized_savings).to_dict("records")),
            "save_run": progress_step("save_run", 1.0, lambda results: _save_master_run(results)),
        }
        run = run_full_rebalance_pipeline(steps)
        st.session_state.last_rebalance_run = run
        progress.empty(); st.success(run["run_status"])
    tabs = st.tabs(["Portfolio recommendations", "Execution order", "Savings plans",
                    "Allocation", "Recommendation report"])
    with tabs[0]: rebalance_engine()
    with tabs[1]: st.dataframe(recommendation_execution_order(st.session_state.recommendations), width="stretch", hide_index=True)
    with tabs[2]: savings_plan_page()
    with tabs[3]: st.dataframe(allocation_table(st.session_state.drift), width="stretch", hide_index=True)
    with tabs[4]: recommendation_report_page()


def _save_master_run(results):
    valuation_snapshot = _save_current_valuation_snapshot()
    database.save_strategy_snapshot(st.session_state.strategy)
    database.save_recommendations(st.session_state.recommendation_report)
    payload = {"run_status": "Completed", "strategy_snapshot": st.session_state.strategy,
               "valuation_snapshot": valuation_snapshot,
               "recommendations": st.session_state.recommendation_report.to_dict("records"),
               "savings_plan_changes": st.session_state.optimized_savings.to_dict("records"),
               "news_inputs": st.session_state.news_items, "sentiment_summary": st.session_state.sentiment,
               "warnings": st.session_state.enrichment_warnings +
                           (["User market notes: " + st.session_state.market_reasoning_notes]
                            if st.session_state.get("market_reasoning_notes") else [])}
    database.save_rebalance_run(payload)
    return payload


def settings_page():
    st.header("Settings")
    s = st.session_state.settings
    st.subheader("Market Data Engine")
    def secret_status(name):
        try:
            return "Configured" if st.secrets.get(name) else "Not configured"
        except Exception:
            return "Not configured"
    required = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "APP_PASSWORD"]
    optional = ["OPENFIGI_API_KEY", "COINGECKO_API_KEY", "FMP_API_KEY", "TWELVE_DATA_API_KEY"]
    st.dataframe(pd.DataFrame(
        [{"Secret": name, "Required": "Yes", "Status": secret_status(name)} for name in required] +
        [{"Secret": name, "Required": "No", "Status": secret_status(name)} for name in optional]),
        width="stretch", hide_index=True)
    a, b, c = st.columns(3)
    s["base_currency"] = a.selectbox("Base currency", ["EUR"])
    s["risk_profile"] = b.selectbox("Risk profile", ["Balanced", "Growth", "Aggressive"],
                                    index=["Balanced", "Growth", "Aggressive"].index(s["risk_profile"]))
    s["live_enabled"] = c.toggle("Enable live market data", value=s["live_enabled"])
    s["scraping_enabled"] = a.toggle("Enable internet scraping", value=s.get("scraping_enabled", True),
                                      help="Uses robots-aware public pages only; no paywall or anti-bot bypassing.")
    s["news_enabled"] = b.toggle("Enable news fetching", value=s.get("news_enabled", True))
    s["rate_limit_seconds"] = c.number_input("Request delay seconds", min_value=0.0, max_value=10.0,
                                               value=float(s.get("rate_limit_seconds", .25)), step=.25)
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

PAGES = ["Portfolio", "Market Data & News", "Strategy", "Rebalance", "Settings"]
with st.sidebar:
    st.title("Financial Command Center")
    page = st.radio("Navigation", PAGES)
    st.warning("Decision support only — never connects to Scalable Capital or places orders.")
    logout_button()

{"Portfolio": portfolio_section, "Market Data & News": market_data_news_section,
 "Strategy": strategy_section, "Rebalance": rebalance_section, "Settings": settings_page}[page]()
