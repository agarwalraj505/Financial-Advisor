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
from styles import inject_premium_css
from strategy_engine import (create_strategy_explanation, get_current_strategy,
                             refresh_market_strategy)
from supabase_client import SupabaseConnectionError, SupabaseGateway, get_supabase_client
from ui_components import (create_allocation_chart, create_current_vs_target_chart,
                           create_portfolio_value_chart, create_savings_plan_before_after_chart,
                           create_winners_losers_chart, render_alert, render_data_quality_badge,
                           render_empty_state, render_flow_steps, render_hero_summary,
                           render_metric_card, render_news_card, render_page_header,
                           render_rebalance_summary, render_recommendation_card,
                           render_section_card, render_status_pill, render_strategy_summary_card,
                           render_flash_message, safe_toast, set_flash_success, style_figure)
from valuation import calculate_historical_gains, portfolio_market_history, valuate_holdings

st.set_page_config(page_title="Financial Hub", page_icon="◆", layout="wide",
                   initial_sidebar_state="expanded")
inject_premium_css()

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
        render_alert("Live market data is paused in Settings.", "warning")
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
        render_alert("Live price unavailable; run Data Enrichment, then use manual fallback after enrichment failed: " + ", ".join(failed), "warning")


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
    render_section_card("Live valuation", "Estimated portfolio value, performance windows, and data-quality diagnostics.")
    render_alert("Internet prices are research estimates. Check final live buy/sell prices manually in Scalable Capital before execution.", "warning")
    refresh_controls("valuation_refresh")
    details, history = st.session_state.valuation_details, database.load_snapshots()
    total, invested, profit = calculate_total_value(details), calculate_total_invested(details), calculate_unrealised_pl(details)
    cash = float(details.loc[details["category"] == "Cash", "current_value_eur"].sum())
    gains = calculate_historical_gains(total, history)
    cards = st.columns(4)
    with cards[0]: render_metric_card("Portfolio value", f"€{total:,.2f}")
    for column, label, period in zip(cards[1:], ["Daily gain", "Weekly gain", "Monthly gain"], ["daily", "weekly", "monthly"]):
        gain = gains[period]
        with column:
            render_metric_card(label, "Not enough history" if gain is None else f"€{gain['eur']:+,.2f}",
                               None if gain is None else f"{gain['pct']:+.2f}%",
                               "positive" if gain and gain["eur"] >= 0 else "negative")
    if st.button("Save today's valuation snapshot"):
        now = datetime.now().astimezone()
        snapshot = {"date": now.date().isoformat(), "timestamp": now.isoformat(timespec="seconds"),
            "total_value_eur": total, "cash_eur": cash, "invested_value_eur": invested, "unrealized_pl_eur": profit,
            **{f"{period}_gain_eur": gains[period]["eur"] if gains[period] else 0 for period in ["daily", "weekly", "monthly", "yearly"]},
            **{f"{period}_gain_pct": gains[period]["pct"] if gains[period] else 0 for period in ["daily", "weekly", "monthly", "yearly"]}}
        database.save_snapshot(snapshot)
        safe_toast("Valuation snapshot saved to Supabase", "💾")
        history = database.load_snapshots()
    market_history = portfolio_market_history(details, st.session_state.quotes)
    if market_history.empty and not history.empty:
        market_history = history.rename(columns={"timestamp": "date", "total_value_eur": "portfolio_value_eur"})
        market_history["daily_gain_eur"] = market_history["portfolio_value_eur"].diff().fillna(0)
    left, right = st.columns(2)
    left.plotly_chart(create_portfolio_value_chart(market_history), width="stretch", key="valuation_history_chart")
    allocation = calculate_allocation(details)
    right.plotly_chart(create_allocation_chart(allocation), width="stretch", key="valuation_allocation_chart")
    comparison = st.session_state.drift.melt(id_vars="category",
        value_vars=["current_weight", "target_weight"], var_name="Allocation", value_name="Weight %")
    st.plotly_chart(create_current_vs_target_chart(comparison), width="stretch", key="valuation_target_chart")
    missing = details[details["price_source"] == "Missing"]
    fallback = details[(details["price_source"] == "Manual fallback") & (details["category"] != "Cash")]
    if not missing.empty:
        render_alert("Missing live and fallback prices: " + ", ".join(missing["instrument"]), "danger")
    if not fallback.empty:
        render_alert("Live price unavailable; using manual fallback after enrichment failed: " + ", ".join(fallback["instrument"]), "warning")
    chart_left, chart_right = st.columns(2)
    holdings_chart = details.sort_values("current_value_eur")
    holdings_figure = style_figure(px.bar(holdings_chart, x="current_value_eur", y="instrument", orientation="h",
                                   title="Holdings value", color_discrete_sequence=["#176B87"]), showlegend=False)
    chart_left.plotly_chart(holdings_figure, width="stretch", key="valuation_holdings_chart")
    winners = details.sort_values("daily_gain_eur")
    chart_right.plotly_chart(create_winners_losers_chart(winners), width="stretch", key="valuation_winners_chart")
    st.dataframe(details, width="stretch", hide_index=True)
    x, y = st.columns(2)
    x.download_button("Export valuation history CSV", history.to_csv(index=False), "valuation_history.csv", "text/csv")
    confirm = y.checkbox("Confirm clear history")
    if y.button("Clear valuation history", disabled=not confirm):
        database.clear_snapshots(); st.rerun()


def dashboard():
    details = st.session_state.valuation_details
    render_section_card("Portfolio structure", "How capital is distributed today compared with the strategy you selected.")
    left, right = st.columns(2)
    allocation = calculate_allocation(details)
    left.plotly_chart(create_allocation_chart(allocation), width="stretch", key="dashboard_allocation_chart")
    drift_chart = st.session_state.drift.melt(id_vars="category",
        value_vars=["current_weight", "target_weight"], var_name="Allocation", value_name="Weight %")
    right.plotly_chart(create_current_vs_target_chart(drift_chart), width="stretch", key="dashboard_target_chart")
    render_section_card("Priority actions", "A first look at what the optimizer considers relevant—not an instruction to trade.")
    order = recommendation_execution_order(st.session_state.recommendations)
    if order.empty:
        render_empty_state("No actions yet", "Run the full rebalance to create an evidence-backed recommendation set.")
    else:
        render_rebalance_summary(order)
        for _, row in order.head(3).iterrows():
            render_recommendation_card(row.get("Action"), row.get("Instrument"), row.get("Reason"),
                                       row.get("Score"), row.get("Data confidence"), isin=row.get("ISIN"),
                                       quantity=row.get("Quantity"), estimated_value=row.get("Est. value"),
                                       fee_issue=row.get("Fee issue"))


def current_portfolio():
    render_section_card("Current holdings", "Edit app records, refresh market estimates, or import a portfolio CSV. Saving writes to your private Supabase project.")
    refresh_controls("portfolio_refresh")
    existing = st.session_state.holdings.copy()
    show_advanced = st.toggle("Show advanced holding columns", value=False, key="portfolio_advanced_columns")
    compact_columns = ["instrument", "isin", "price_symbol", "asset_type", "category", "quantity",
                       "manual_current_price", "live_current_price", "price_source", "current_value_eur",
                       "buy_in_value_eur", "pl_eur", "pl_pct"]
    selected_columns = [column for column in (HOLDING_DISPLAY if show_advanced else compact_columns) if column in existing]
    display = existing[selected_columns].rename(columns=HOLDING_DISPLAY)
    source = existing.get("price_source", pd.Series("Missing", index=existing.index)).fillna("Missing").astype(str)
    display["Data quality"] = source.apply(
        lambda value: "● Manual fallback" if "manual" in value.lower() else "● Missing" if "missing" in value.lower() else "● Live")
    valuation_ready = existing.get("valuation_ready", pd.Series(False, index=existing.index)).fillna(False)
    recommendation_ready = existing.get("recommendation_ready", pd.Series(False, index=existing.index)).fillna(False)
    display["Readiness"] = ["● Recommendation ready" if rec else "● Valuation ready" if val else "● Review required"
                            for val, rec in zip(valuation_ready, recommendation_ready)]
    disabled_columns = [column for column in ["Live current price", "Price source", "Current value EUR", "P/L EUR", "P/L %", "Data quality", "Readiness"] if column in display]
    edited = st.data_editor(display, num_rows="dynamic", width="stretch", hide_index=True,
        disabled=disabled_columns,
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
        database.save_holdings(st.session_state.holdings); safe_toast("Portfolio saved to Supabase", "💾")
    if b.button("Reset sample holdings"):
        st.session_state.holdings = holdings_to_dataframe(SAMPLE_HOLDINGS); recompute_models(); st.rerun()
    c.download_button("Export holdings CSV", display.to_csv(index=False), "holdings_export.csv", "text/csv")


def upload_screenshots_page():
    render_section_card("Upload holdings screenshots")
    render_alert("Screenshots are uploaded to private Supabase Storage, never GitHub. No broker connection is used.", "info")
    files = st.file_uploader("Choose screenshots", type=["png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True, key="supabase_screenshots")
    storage = ScreenshotStorage(gateway, user_id)
    for index, image in enumerate(files):
        st.image(image, caption=image.name, width=380)
        if st.button(f"Save {image.name} privately", key=f"save_image_{index}_{image.name}"):
            path = storage.upload(image.name, image.getvalue(), image.type or "application/octet-stream")
            safe_toast(f"Saved privately as {path}", "💾")


def candidate_universe():
    render_section_card("Candidate assets", "Research assets you do not own yet without weakening buy/add readiness rules.")
    render_alert("The Market Data Engine enriches first. Unresolved or conflicting facts move to manual fallback after enrichment failed; incomplete candidates stay blocked from buy/add.", "info")
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
        safe_toast("Candidate universe saved to Supabase", "💾")
    if b.button("Reset sample candidates"):
        st.session_state.candidates = _normalise_candidates(pd.DataFrame(SAMPLE_CANDIDATES)); recompute_models(); st.rerun()
    c.download_button("Export candidate universe CSV", st.session_state.candidates.to_csv(index=False), "candidate_universe_export.csv", "text/csv")


def market_research_dashboard():
    render_section_card("Market research", "Rankings combine momentum, quality, cost, portfolio fit, and risk control.")
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
        render_section_card(title)
        columns = [c for c in ["instrument", "category", "trend_status", "momentum_score", "quality_score",
                               "cost_score", "portfolio_fit_score", "total_score", "score_band",
                               "data_confidence", "data_source", "last_updated"] if c in frame]
        st.dataframe(frame[columns], width="stretch", hide_index=True)
    drift_chart = st.session_state.drift.melt(id_vars="category", value_vars=["current_weight", "target_weight"],
                                               var_name="Allocation", value_name="Weight %")
    st.plotly_chart(create_current_vs_target_chart(drift_chart), width="stretch", key="research_target_chart")
    for score, title in [("total_score", "Candidate universe total score ranking"),
                         ("momentum_score", "Momentum score ranking"), ("quality_score", "Quality score ranking"),
                         ("cost_score", "Cost score ranking")]:
        chart = candidates.nlargest(15, score).sort_values(score)
        figure = style_figure(px.bar(chart, x=score, y="instrument", orientation="h", title=title,
                                     color_discrete_sequence=["#176B87"]), showlegend=False)
        st.plotly_chart(figure, width="stretch", key=f"research_{score}_chart")


def asset_quality_dashboard():
    render_section_card("Asset quality", "Explainable fund, stock, and crypto checks with visible source confidence.")
    render_alert("Review required means the engine will not recommend a new buy/add. Confirm facts from an official issuer source and retain the URL and date.", "warning")
    combined = pd.concat([st.session_state.scored_current, st.session_state.scored_candidates], ignore_index=True, sort=False)
    columns = [c for c in ["instrument", "asset_type", "category", "ter_pct", "fund_size_eur",
        "replication_method", "distribution_policy", "domicile", "manual_spread_estimate_pct",
        "liquidity_score", "quality_score", "quality_confidence", "manual_review_required",
        "missing_critical_data", "quality_reason", "data_source", "source_url", "last_updated"] if c in combined]
    st.dataframe(combined[columns].sort_values("quality_score", ascending=False), width="stretch", hide_index=True,
                 column_config={"source_url": st.column_config.LinkColumn("Source URL")})
    quality_figure = style_figure(px.bar(combined.nlargest(20, "quality_score").sort_values("quality_score"),
                           x="quality_score", y="instrument", orientation="h", title="Quality score ranking",
                           color_discrete_sequence=["#176B87"]), showlegend=False)
    st.plotly_chart(quality_figure, width="stretch", key="quality_ranking_chart")


def rebalance_engine():
    render_section_card("Immediate recommendations", "Buy, sell, hold, and defer decisions ordered by practical execution priority.")
    recommendations, order = st.session_state.recommendations, recommendation_execution_order(st.session_state.recommendations)
    if recommendations.empty:
        render_empty_state("No recommendations", "Run the full rebalance to build the current action set.")
        return
    if recommendations["Reason"].astype(str).str.contains("insufficient|cash", case=False, regex=True).any():
        render_alert("Cash shortfall: lower-priority buys were reduced or deferred.", "warning")
    if recommendations["Fee issue"].astype(str).str.contains("Below", case=False).any():
        render_alert("Fee inefficiency: trades below the configured minimum should normally use a savings plan.", "warning")
    if recommendations["Purpose"].astype(str).str.contains("Manual review", case=False).any():
        render_alert("Manual review required: incomplete assets remain blocked from buy/add recommendations.", "danger")
    for _, row in order.head(8).iterrows():
        render_recommendation_card(row.get("Action"), row.get("Instrument"), row.get("Reason"),
            row.get("Score"), row.get("Data confidence"), isin=row.get("ISIN"), quantity=row.get("Quantity"),
            estimated_value=f"€{float(row.get('Est. value') or 0):,.2f}", fee_issue=row.get("Fee issue"))
    with st.expander("Open complete recommendation table"):
        st.dataframe(recommendations, width="stretch", hide_index=True)


def savings_plan_page():
    render_section_card("Savings-plan optimizer", "Review contribution changes before creating a manual Scalable checklist.")
    render_alert("These changes are saved in this app only. You must manually update the actual savings plans in Scalable Capital.", "warning")
    st.session_state.plans = st.data_editor(st.session_state.plans, num_rows="dynamic", width="stretch", hide_index=True,
                                            key="plans_editor")
    recompute_models()
    result = st.session_state.optimized_savings
    result = result.copy()
    if "Priority" not in result: result["Priority"] = range(1, len(result) + 1)
    if "User approved" not in result: result["User approved"] = False
    budget_col, quality_col = st.columns(2)
    with budget_col: render_metric_card("Monthly budget", f"€{st.session_state.settings['monthly_savings_budget']:,.2f}")
    with quality_col: render_metric_card("Proposed plans", len(result), "Approval required", "warning")
    result = st.data_editor(result, width="stretch", hide_index=True,
                            disabled=[column for column in result.columns if column != "User approved"],
                            key="optimized_plan_approvals")
    budget_check = validate_savings_plan_budget(result, st.session_state.settings["monthly_savings_budget"])
    if not budget_check["valid"]:
        render_alert(f"Optimizer total differs from the monthly budget by €{budget_check['difference']:+,.2f}.", "warning")
    before = st.session_state.plans[["instrument", "current_plan"]].rename(columns={"instrument": "Instrument", "current_plan": "Amount"})
    before["Plan"] = "Before"
    after = result[["Instrument", "New plan"]].rename(columns={"New plan": "Amount"}); after["Plan"] = "After"
    chart = pd.concat([before, after], ignore_index=True)
    st.plotly_chart(create_savings_plan_before_after_chart(chart), width="stretch", key="savings_before_after_chart")
    checklist = create_savings_plan_execution_checklist(st.session_state.plans, result)
    a, b, c, d = st.columns(4)
    if a.button("Save savings plans to Supabase"):
        current_lookup = st.session_state.plans.set_index("isin")["current_plan"].to_dict()
        persisted = result.rename(columns={"Instrument": "instrument", "ISIN": "isin",
            "New plan": "new_plan", "Action": "action", "Reason": "reason", "Score": "score",
            "Priority": "priority", "User approved": "user_approved"})
        persisted["current_plan"] = persisted["isin"].map(current_lookup).fillna(0.0)
        database.save_savings_plans(persisted)
        safe_toast("Savings-plan review saved to Supabase", "💾")
    if b.button("Apply optimizer recommendation"):
        applied = normalize_savings_plan_rows(result)
        applied["current_plan"] = applied["new_plan"]
        st.session_state.plans = _plans_with_categories(applied)
        recompute_models(); safe_toast("Optimizer recommendations applied to app records", "✅")
    if c.button("Reset to current saved plans"):
        saved = database.load_savings_plans()
        st.session_state.plans = _plans_with_categories(saved if not saved.empty else pd.DataFrame(SAMPLE_SAVINGS_PLANS))
        recompute_models(); st.rerun()
    d.download_button("Export Scalable execution checklist CSV", checklist.to_csv(index=False),
                      "scalable_savings_plan_checklist.csv", "text/csv")


def recommendation_report_page():
    render_section_card("Recommendation report", "A source-aware record of portfolio and savings-plan decisions.")
    report = st.session_state.recommendation_report
    st.caption("Every recommendation includes source, timestamp, confidence, reason, and an execution-price warning.")
    st.dataframe(report, width="stretch", hide_index=True)
    a, b = st.columns(2)
    a.download_button("Export recommendation report CSV", report.to_csv(index=False), "recommendation_report.csv", "text/csv")
    if b.button("Save report to Supabase history"):
        database.save_recommendations(report); safe_toast("Recommendation report saved", "💾")


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
    render_section_card("Guided screenshot import", "A private five-step flow. Images go to Supabase Storage; visible text is parsed only after you paste it.")
    image_present = st.session_state.get("command_screenshot") is not None
    draft_present = bool(st.session_state.get("screenshot_draft"))
    render_flow_steps([
        {"label": "Upload screenshot", "status": "Done" if image_present else "Running"},
        {"label": "Preview", "status": "Done" if image_present else "Pending"},
        {"label": "Paste visible text", "status": "Running" if image_present and not draft_present else "Done" if draft_present else "Pending"},
        {"label": "Confirm parsed data", "status": "Running" if draft_present else "Pending"},
        {"label": "Save holding", "status": "Pending"},
    ])
    render_alert("Private upload: no broker connection, no automatic screenshot extraction, and no GitHub storage.", "info")
    image = st.file_uploader("Screenshot", type=["png", "jpg", "jpeg", "webp"], key="command_screenshot")
    if image:
        render_section_card("Screenshot preview")
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
                render_alert("; ".join(errors), "danger")
            else:
                holding = create_holding_from_screenshot_data(draft)
                if image:
                    holding["screenshot_path"] = ScreenshotStorage(gateway, user_id).upload(
                        image.name, image.getvalue(), image.type or "application/octet-stream")
                rows = update_holding_by_isin(st.session_state.holdings.to_dict("records"), holding)
                st.session_state.holdings = holdings_to_dataframe(rows)
                database.save_holdings(st.session_state.holdings)
                recompute_models(); safe_toast("Confirmed holding saved to Supabase", "💾")


def portfolio_section():
    render_flash_message()
    details = st.session_state.valuation_details
    total = calculate_total_value(details); invested = calculate_total_invested(details)
    profit = calculate_unrealised_pl(details)
    cash = float(details.loc[details["category"] == "Cash", "current_value_eur"].sum())
    history = database.load_snapshots(); gains = calculate_historical_gains(total, history)
    live = st.session_state.settings.get("live_enabled", True)
    render_page_header("Portfolio", "A composed view of your wealth, allocation, performance, and data quality.",
                       "Market data live" if live else "Live data paused")
    daily = gains.get("daily")
    render_hero_summary("Total portfolio value", f"€{total:,.2f}",
                        None if daily is None else f"{daily['pct']:+.2f}% today",
                        f"Last refreshed {st.session_state.last_price_fetch or 'not yet'} · Estimated valuation")
    cards = st.columns(7)
    metrics = [
        ("Daily", daily), ("Weekly", gains.get("weekly")), ("Monthly", gains.get("monthly")),
        ("Yearly", gains.get("yearly")),
    ]
    for column, (label, gain) in zip(cards[:4], metrics):
        with column:
            render_metric_card(label, "—" if gain is None else f"€{gain['eur']:+,.0f}",
                               "Not enough history" if gain is None else f"{gain['pct']:+.2f}%",
                               "positive" if gain and gain["eur"] >= 0 else "negative" if gain else "neutral")
    with cards[4]: render_metric_card("Unrealised P/L", f"€{profit:+,.0f}", f"{profit / invested * 100:+.2f}%" if invested else "—",
                                      "positive" if profit >= 0 else "negative")
    with cards[5]: render_metric_card("Cash", f"€{cash:,.0f}", f"{cash / total * 100:.1f}%" if total else "—")
    fallback_count = int(((details["price_source"] == "Manual fallback") & (details["category"] != "Cash")).sum())
    with cards[6]: render_metric_card("Data quality", f"{len(details)-fallback_count}/{len(details)} live", f"{fallback_count} fallback", "warning" if fallback_count else "positive")
    action_left, action_right = st.columns([1, 3])
    if action_left.button("Refresh all prices and metadata", type="primary", use_container_width=True):
        with st.spinner("Refreshing prices, FX, identifiers, and available metadata..."):
            refresh_live_data(True); _run_data_enrichment(False)
        set_flash_success("Portfolio market data refreshed"); st.rerun()
    action_right.caption("Prices are estimates for research. Scalable Capital remains the final execution source.")
    dashboard()
    current_portfolio()
    with st.expander("Add or update a holding from a Scalable screenshot", expanded=False):
        screenshot_workflow()
    with st.expander("Open detailed valuation analytics", expanded=False):
        valuation_dashboard()
    with st.expander("Open valuation snapshot history", expanded=False):
        render_section_card("Valuation snapshots", "A durable Supabase history used for daily, weekly, monthly, and yearly comparisons.")
        if history.empty: render_empty_state("No snapshots yet", "Save today’s valuation from Analytics to begin your performance history.")
        else: st.dataframe(history, width="stretch", hide_index=True)
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


def _legacy_market_data_news_section():
    sentiment_state = st.session_state.sentiment
    missing_summary = _missing_data_frame()
    engine = MarketDataEngine(st.session_state.settings.get("scraping_enabled", True),
                              st.session_state.settings.get("rate_limit_seconds", .25))
    provider_rows = st.session_state.provider_status or engine.provider_status_rows(
        st.session_state.settings.get("news_enabled", True))
    live_sources = sum(str(row.get("Status")) == "Enabled" for row in provider_rows)
    render_page_header("Market", "Live sources, identifier enrichment, repair workflows, and an evidence-ranked financial news feed.",
                       f"{live_sources} sources active")
    render_hero_summary("Market regime", sentiment_state.get("market_regime", "Neutral"),
                        sentiment_state.get("sentiment", "Neutral"),
                        f"{len(missing_summary)} assets need attention · Last refresh {st.session_state.last_price_fetch or 'not yet'}")
    render_alert("Web-scraped data may be incomplete or outdated. Confirm important facts from the issuer factsheet before investing.", "warning")
    tabs = [st.container() for _ in range(9)]
    with tabs[0]:
        render_section_card("Market Data Engine", "Free/no-key providers are tried first. Optional providers stay quiet when no key exists.")
        provider_columns = st.columns(4)
        for index, row in enumerate(provider_rows):
            with provider_columns[index % 4]:
                status = row.get("Status", "Unknown")
                render_metric_card(row.get("Provider"), row.get("Purpose"), status,
                                   "positive" if status == "Enabled" else "neutral")
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
        for warning in st.session_state.enrichment_warnings: render_alert(warning, "warning")
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
        if news.empty: render_empty_state("No headlines cached", "Refresh the feed to collect legal public RSS and available market headlines.", "Refresh news")
        else:
            categories = ["All"] + sorted(news.get("category", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
            selected_category = st.selectbox("Filter news by theme", categories, key="news_theme_filter")
            filtered = news if selected_category == "All" else news[news["category"] == selected_category]
            render_section_card("Latest market headlines", f"{len(filtered)} evidence items in this view.")
            for _, item in filtered.head(12).iterrows():
                render_news_card(item.get("title"), item.get("source"), item.get("published_at"),
                                 item.get("sentiment"), item.get("url"))
            with st.expander("Open compact news table"):
                columns = [c for c in ["title", "source", "published_at", "category", "sentiment", "confidence", "url"] if c in filtered]
                st.dataframe(filtered[columns], width="stretch", hide_index=True,
                             column_config={"url": st.column_config.LinkColumn("Link")})
    with tabs[6]:
        sentiment = st.session_state.sentiment
        render_hero_summary("Market sentiment", sentiment.get("sentiment", "Neutral"),
                            sentiment.get("market_regime", "Neutral"), sentiment.get("explanation", ""))
        render_data_quality_badge(sentiment.get("confidence", "Low") + " confidence")
        if st.button("Use news in strategy refresh"):
            _refresh_news_and_strategy(True); safe_toast("Strategy refreshed using current evidence", "🧠")
    with tabs[7]:
        missing = _missing_data_frame()
        render_section_card("Missing Data Repair Center", "Repair identifiers and fund facts through the full enrichment waterfall before using a manual fallback.")
        repair_labels = ["Price symbol", "TER/cost", "Category", "Factsheet URL", "Conflicting metadata"]
        repair_cards = st.columns(5)
        missing_text = missing.get("Missing / repair needed", pd.Series(dtype=str)).fillna("")
        for column, label in zip(repair_cards, repair_labels):
            count = int(missing_text.str.contains(label, case=False, regex=False).sum())
            with column: render_metric_card(label, count, "Repair now" if count else "Complete", "warning" if count else "positive")
        if missing.empty: render_empty_state("Data quality looks healthy", "No repair items are currently waiting.")
        else: st.dataframe(missing, width="stretch", hide_index=True)
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
                    except ValueError: render_alert("Enter TER as a number, for example 0.20", "danger"); st.stop()
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


def market_data_news_section():
    """Readable vertical Market workspace; advanced detail lives in expanders, not tabs."""
    render_flash_message()
    sentiment = st.session_state.sentiment
    missing = _missing_data_frame()
    engine = MarketDataEngine(st.session_state.settings.get("scraping_enabled", True),
                              st.session_state.settings.get("rate_limit_seconds", .25))
    providers = st.session_state.provider_status or engine.provider_status_rows(
        st.session_state.settings.get("news_enabled", True))
    active_sources = sum(str(row.get("Status")) == "Enabled" for row in providers)
    render_page_header("Market", "Market-data health, missing-data repair, public news, sentiment, and candidate research.",
                       "Live" if st.session_state.settings.get("live_enabled", True) else "Disabled")
    render_hero_summary("Market regime", sentiment.get("market_regime", "Neutral"),
                        sentiment.get("sentiment", "Neutral"),
                        "Evidence is informational and never triggers broker activity.")
    kpis = st.columns(5)
    with kpis[0]: render_metric_card("Regime", sentiment.get("market_regime", "Neutral"), tone="info")
    with kpis[1]: render_metric_card("Sentiment", sentiment.get("sentiment", "Neutral"), sentiment.get("confidence", "Low") + " confidence")
    with kpis[2]: render_metric_card("Active sources", active_sources, f"of {len(providers)} configured", "positive")
    with kpis[3]: render_metric_card("Missing items", len(missing), "Repair required" if len(missing) else "Complete", "warning" if len(missing) else "positive")
    with kpis[4]: render_metric_card("Last refresh", st.session_state.last_price_fetch or "Not yet")

    render_section_card("Main actions", "Refresh the evidence layer before reviewing repair suggestions or research rankings.")
    action_a, action_b, action_c, action_d = st.columns(4)
    if action_a.button("Refresh live prices", type="primary", use_container_width=True):
        with st.spinner("Refreshing prices and FX..."): refresh_live_data(True)
        set_flash_success("Live prices refreshed"); st.rerun()
    if action_b.button("Enrich missing ISIN data", use_container_width=True):
        with st.spinner("Running free identifier and metadata enrichment..."): _run_data_enrichment(True)
        set_flash_success("Internet enrichment completed"); st.rerun()
    if action_c.button("Fetch market news", use_container_width=True):
        with st.spinner("Fetching public market news..."): _refresh_news_and_strategy(False)
        set_flash_success("Market news refreshed"); st.rerun()
    if action_d.button("Repair missing data", use_container_width=True, disabled=missing.empty):
        with st.spinner("Trying all enabled repair sources..."): _run_data_enrichment(True)
        set_flash_success("Missing-data repair completed"); st.rerun()

    render_section_card("1. Market Data Status", "Provider availability, key requirements, and the latest recorded provider outcome.")
    provider_cols = st.columns(4)
    for index, row in enumerate(providers):
        with provider_cols[index % 4]:
            enabled = row.get("Status") == "Enabled"
            render_metric_card(row.get("Provider"), row.get("Status", "Unknown"), row.get("Purpose"),
                               "positive" if enabled else "neutral")
    with st.expander("Provider details and errors", expanded=False):
        st.dataframe(pd.DataFrame(providers), width="stretch", hide_index=True)

    render_section_card("2. Missing Data Repair", "Suggestions remain separate from entered facts until you explicitly accept or confirm them.")
    repair_labels = ["Price symbol", "TER/cost", "Category", "Factsheet URL", "Conflicting metadata"]
    repair_cols = st.columns(5)
    missing_text = missing.get("Missing / repair needed", pd.Series(dtype=str)).fillna("")
    for column, label in zip(repair_cols, repair_labels):
        count = int(missing_text.str.contains(label, case=False, regex=False).sum())
        with column: render_metric_card(label, count, "Needs attention" if count else "Complete", "warning" if count else "positive")
    if missing.empty:
        render_empty_state("No repair items", "The current holdings and candidate universe have no detected repair queue.")
    else:
        combined = pd.concat([st.session_state.holdings.assign(dataset="Holding"),
                              st.session_state.candidates.assign(dataset="Candidate")], ignore_index=True, sort=False)
        repair_rows = []
        for _, item in missing.iterrows():
            matches = combined[(combined["dataset"] == item["Dataset"]) &
                               (combined["isin"].astype(str) == str(item["ISIN"]))]
            asset = matches.iloc[0].to_dict() if not matches.empty else {}
            audit = asset.get("enrichment_audit") if isinstance(asset.get("enrichment_audit"), list) else []
            tried = ", ".join(dict.fromkeys(str(entry.get("provider", "")) for entry in audit if entry.get("provider"))) or "Not run yet"
            suggestions = asset.get("enrichment_suggestions") if isinstance(asset.get("enrichment_suggestions"), dict) else {}
            first = next(iter(suggestions.values()), {}) if suggestions else {}
            repair_rows.append({"Asset": item["Instrument"], "ISIN": item["ISIN"],
                                "Missing field": item["Missing / repair needed"], "Tried sources": tried,
                                "Suggested value": first.get("value", ""),
                                "Confidence": first.get("confidence", asset.get("web_scrape_confidence", "")),
                                "Action": "Review suggestion" if suggestions else "Auto repair"})
        st.dataframe(pd.DataFrame(repair_rows), width="stretch", hide_index=True)
        selected = st.selectbox("Choose an asset to repair", missing["ISIN"].astype(str).tolist(), key="market_repair_asset",
                                format_func=lambda value: missing.loc[missing["ISIN"].astype(str) == value, "Instrument"].iloc[0])
        selected_summary = missing.loc[missing["ISIN"].astype(str) == selected].iloc[0]
        dataset = selected_summary["Dataset"]
        source_frame = st.session_state.holdings if dataset == "Holding" else st.session_state.candidates
        asset = source_frame.loc[source_frame["isin"].astype(str) == selected].iloc[0].to_dict()
        repair_a, repair_b = st.columns(2)
        if repair_a.button("Auto repair selected asset", type="primary", use_container_width=True):
            with st.spinner("Trying provider and web enrichment sources..."): _run_data_enrichment(True, selected)
            st.rerun()
        if repair_b.button("Retry public web search", use_container_width=True):
            with st.spinner("Searching source-ranked public pages..."): _run_data_enrichment(True, selected)
            st.rerun()
        suggestions = asset.get("enrichment_suggestions") if isinstance(asset.get("enrichment_suggestions"), dict) else {}
        if suggestions:
            suggestion_field = st.selectbox("Suggested field", list(suggestions), key="market_suggestion_field")
            render_alert(f"Suggested {suggestion_field}: {suggestions[suggestion_field].get('value')} · "
                         f"{suggestions[suggestion_field].get('confidence', 'Unknown')} confidence", "info")
            if st.button("Accept suggested value", key="market_accept_suggestion"):
                _replace_asset(dataset, selected, accept_suggestion(asset, suggestion_field)); st.rerun()
        with st.expander("Enter a value manually and mark it confirmed", expanded=False):
            manual_fields = ["price_symbol", "ter_pct", "asset_type", "category", "factsheet_url",
                             "scalable_compatible", "issuer", "currency"]
            field = st.selectbox("Field", manual_fields, key="market_manual_field")
            manual_value = st.text_input("Confirmed value", key="market_manual_value")
            confirmed = st.checkbox("I verified this value", key="market_manual_confirmed")
            if st.button("Save confirmed value", key="market_save_manual", disabled=not (manual_value and confirmed)):
                updated = dict(asset)
                if field == "ter_pct":
                    try: updated[field] = float(manual_value.replace(",", "."))
                    except ValueError: render_alert("Enter TER as a number, for example 0.20", "danger"); st.stop()
                elif field == "scalable_compatible":
                    updated[field] = manual_value.strip().lower() in {"true", "yes", "1", "confirmed"}
                else: updated[field] = manual_value.strip()
                updated["confirmed_by_user"] = True
                _replace_asset(dataset, selected, updated); st.rerun()

    render_section_card("3. Internet Enrichment", "Every identifier, price, FX, metadata, and safe web attempt is retained for review.")
    audit = st.session_state.enrichment_audit
    audit_cols = st.columns(3)
    with audit_cols[0]: render_metric_card("Audit events", len(audit))
    with audit_cols[1]: render_metric_card("Warnings", len(st.session_state.enrichment_warnings), tone="warning" if st.session_state.enrichment_warnings else "positive")
    with audit_cols[2]: render_metric_card("Web enrichment", "Enabled" if st.session_state.settings.get("scraping_enabled") else "Disabled")
    for warning in st.session_state.enrichment_warnings: render_alert(warning, "warning")
    with st.expander("Open enrichment audit", expanded=False):
        if audit.empty: render_empty_state("No enrichment audit yet", "Run enrichment to create the provider-by-provider evidence trail.")
        else: st.dataframe(audit, width="stretch", hide_index=True)
        st.download_button("Export enrichment audit CSV", audit.to_csv(index=False), "enrichment_audit.csv", "text/csv")

    render_section_card("4. Latest Market News", "Public headlines ranked against your holdings, candidate assets, themes, and strategy.")
    news = pd.DataFrame(st.session_state.news_items)
    if news.empty:
        render_empty_state("No market news cached", "Use Fetch market news to build the current feed.")
    else:
        categories = ["All"] + sorted(news.get("category", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
        selected_category = st.selectbox("News theme", categories, key="vertical_news_filter")
        filtered = news if selected_category == "All" else news[news["category"] == selected_category]
        for _, item in filtered.head(10).iterrows():
            render_news_card(item.get("title"), item.get("source"), item.get("published_at"), item.get("sentiment"), item.get("url"))
        with st.expander("News table", expanded=False):
            columns = [column for column in ["title", "source", "published_at", "category", "sentiment", "confidence", "url"] if column in filtered]
            st.dataframe(filtered[columns], width="stretch", hide_index=True,
                         column_config={"url": st.column_config.LinkColumn("Link")})

    render_section_card("5. Market Sentiment", "An explainable blend of public-news language and observed market momentum.")
    sentiment_cols = st.columns(3)
    with sentiment_cols[0]: render_metric_card("Sentiment", sentiment.get("sentiment", "Neutral"), tone="info")
    with sentiment_cols[1]: render_metric_card("Regime", sentiment.get("market_regime", "Neutral"), tone="info")
    with sentiment_cols[2]: render_metric_card("Confidence", sentiment.get("confidence", "Low"), tone="warning")
    render_alert(sentiment.get("explanation", "Refresh market news to produce an explanation."), "info")
    if st.button("Use current sentiment in strategy refresh"):
        _refresh_news_and_strategy(True); set_flash_success("Strategy refreshed"); st.rerun()

    render_section_card("6. Candidate Asset Research", "Edit the candidate universe first; open rankings and detailed quality only when needed.")
    with st.expander("Candidate universe editor", expanded=False): candidate_universe()
    with st.expander("Market research rankings", expanded=False): market_research_dashboard()
    with st.expander("Detailed asset quality", expanded=False): asset_quality_dashboard()


def strategy_section():
    render_flash_message()
    strategy = st.session_state.strategy
    render_page_header("Strategy", "Your evidence-gated investment cockpit: allocation intent, market regime, themes, and risk posture.",
                       strategy.get("confidence", "Low") + " confidence")
    render_hero_summary("Current strategy", strategy.get("strategy_name", "Strategy not generated"),
                        strategy.get("market_regime", "Neutral"),
                        f"Risk profile {strategy.get('risk_profile', 'Aggressive')} · Refreshed {strategy.get('timestamp', 'not yet')}")
    cards = st.columns(4)
    with cards[0]: render_metric_card("Market regime", strategy.get("market_regime", "Neutral"), tone="info")
    with cards[1]: render_metric_card("Risk profile", strategy.get("risk_profile", "Aggressive"))
    with cards[2]: render_metric_card("Confidence", strategy.get("confidence", "Low"), tone="warning")
    with cards[3]: render_metric_card("Preferred themes", len(strategy.get("preferred_themes", [])), "Evidence-backed")
    render_strategy_summary_card(strategy)
    render_section_card("Strategy reasoning", create_strategy_explanation(strategy))
    render_section_card("Target allocation", "Current exposure beside the long-term allocation policy.")
    drift_chart = st.session_state.drift.melt(id_vars="category", value_vars=["current_weight", "target_weight"],
                                               var_name="Allocation", value_name="Weight %")
    chart_col, table_col = st.columns([1.45, 1])
    chart_col.plotly_chart(create_current_vs_target_chart(drift_chart), width="stretch", key="strategy_target_chart")
    table_col.dataframe(pd.DataFrame(strategy.get("target_allocations", st.session_state.targets).items(),
                                     columns=["Category", "Target %"]), hide_index=True, width="stretch")
    left, right = st.columns(2)
    with left:
        render_section_card("Preferred themes", "Themes supported by current momentum and news evidence.")
        preferred = strategy.get("preferred_themes", [])
        if preferred:
            for theme in preferred: render_status_pill(theme, "success")
        else: render_empty_state("No preferred theme confirmed", "The engine is deliberately avoiding a weak signal.")
    with right:
        render_section_card("Reduced / cautious themes", "Themes that deserve smaller contributions or closer review.")
        reduced = strategy.get("reduced_themes", [])
        if reduced:
            for theme in reduced: render_status_pill(theme, "warning")
        else: render_empty_state("No reduced theme confirmed", "No evidence-supported reduction is active.")
    render_alert("Current risks: " + ("; ".join(strategy.get("current_risks", [])) or "No additional evidence-backed risks."), "warning")
    render_section_card("Savings-plan priorities", ", ".join(strategy.get("savings_plan_priorities", [])) or "Follow underweight categories and quality scores.")
    a, b, c = st.columns(3)
    if a.button("Refresh market news and sentiment"):
        _refresh_news_and_strategy(False); set_flash_success("News and sentiment refreshed"); st.rerun()
    if b.button("Redesign strategy using latest market data", type="primary"):
        _refresh_news_and_strategy(True); st.rerun()
    if c.button("Save strategy snapshot"):
        database.save_strategy_snapshot(strategy); safe_toast("Strategy snapshot saved", "💾")
    history = database.load_strategy_snapshots()
    render_section_card("Strategy history", "Saved evidence snapshots create an audit trail without changing broker positions.")
    if history.empty: render_empty_state("No strategy snapshots", "Save the current strategy when you want a durable checkpoint.")
    else: st.dataframe(history, width="stretch", hide_index=True)


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
    render_flash_message()
    render_page_header("Rebalance", "One evidence-led superflow for prices, metadata, news, strategy, allocation, savings plans, and execution planning.",
                       "Decision support only")
    render_hero_summary("Full portfolio review", "Run full rebalance", "One guided workflow",
                        "Refreshes market evidence and produces a manual Scalable execution checklist. It never places an order.")
    render_alert("No broker connection, orders, or automatic savings-plan updates. Check the live Scalable price before every execution.", "warning")
    st.session_state.market_reasoning_notes = st.text_area(
        "Short market reasoning notes",
        value=st.session_state.get("market_reasoning_notes", ""),
        placeholder="Add your own interpretation, constraints, tax notes, or reasons to defer execution.")
    flow_labels = ["Refreshing prices", "Enriching missing data", "Reading market news",
                   "Calculating sentiment", "Refreshing strategy", "Running portfolio optimizer",
                   "Running savings-plan optimizer", "Building execution checklist", "Saving report"]
    flow_state = st.session_state.get("rebalance_flow_status", ["Pending"] * len(flow_labels))
    flow_slot = st.empty()
    def draw_flow():
        flow_slot.empty()
        with flow_slot.container():
            render_flow_steps([{"label": label, "status": flow_state[index]} for index, label in enumerate(flow_labels)])
    draw_flow()
    if st.button("Run full rebalance", type="primary", use_container_width=True):
        flow_state = ["Pending"] * len(flow_labels); st.session_state.rebalance_flow_status = flow_state
        progress = st.progress(0, "Starting Market Data Engine...")
        flow_map = {"refresh_prices": 0, "enrich_assets": 1, "repair_missing_metadata": 1,
                    "fetch_news": 2, "calculate_sentiment": 3, "redesign_strategy": 4,
                    "recalculate_valuation": 5, "recalculate_drift": 5, "score_assets": 5,
                    "run_portfolio_optimizer": 5, "run_savings_optimizer": 6,
                    "create_report": 7, "create_execution_checklist": 7, "save_run": 8}
        def progress_step(name, fraction, function):
            def wrapped(results):
                flow_state[flow_map[name]] = "Running"; draw_flow()
                progress.progress(fraction, name.replace("_", " ").title())
                try:
                    result = function(results); flow_state[flow_map[name]] = "Done"; draw_flow(); return result
                except Exception:
                    flow_state[flow_map[name]] = "Failed"; draw_flow(); raise
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
        st.session_state.rebalance_flow_status = flow_state
        progress.empty()
        if run["warnings"]: render_alert(run["run_status"] + ": " + "; ".join(run["warnings"]), "warning")
        else: safe_toast("Full rebalance completed", "✅")
    render_rebalance_summary(st.session_state.recommendations)
    rebalance_engine()
    render_section_card("Execution order", "Sells first, then cash-limited buys; lower-priority actions are deferred when funding is insufficient.")
    execution = recommendation_execution_order(st.session_state.recommendations)
    if execution.empty: render_empty_state("No execution steps", "Run the full rebalance to create an ordered checklist.")
    else: st.dataframe(execution[[column for column in ["Step", "Action", "Instrument", "Quantity", "Est. value", "Fee issue"] if column in execution]],
                       width="stretch", hide_index=True)
    savings_plan_page()
    render_section_card("Manual Scalable checklist", "These rows must be reviewed and applied manually in Scalable Capital.")
    manual_checklist = create_savings_plan_execution_checklist(st.session_state.plans, st.session_state.optimized_savings)
    if manual_checklist.empty: render_empty_state("No savings-plan changes", "The current optimizer output does not require a manual plan update.")
    else: st.dataframe(manual_checklist, width="stretch", hide_index=True)
    render_section_card("Allocation before and after", "Current exposure against the target policy after considering the recommendation set.")
    allocation_summary = allocation_table(st.session_state.drift)
    st.dataframe(allocation_summary, width="stretch", hide_index=True)
    with st.expander("Recommendation report and source detail", expanded=False): recommendation_report_page()


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
    render_flash_message()
    render_page_header("Settings", "Tune the experience, strategy guardrails, and Scalable assumptions without touching broker accounts.",
                       "Private configuration")
    s = st.session_state.settings
    render_section_card("App status", "The switches that determine which evidence systems are active.")
    status_columns = st.columns(4)
    status_items = [("Supabase", "Connected", "positive"),
                    ("Market data", "Enabled" if s.get("live_enabled") else "Paused", "positive" if s.get("live_enabled") else "warning"),
                    ("Internet enrichment", "Enabled" if s.get("scraping_enabled") else "Paused", "positive" if s.get("scraping_enabled") else "warning"),
                    ("News", "Enabled" if s.get("news_enabled") else "Paused", "positive" if s.get("news_enabled") else "warning")]
    for column, (label, value, tone) in zip(status_columns, status_items):
        with column: render_metric_card(label, value, tone=tone)
    def secret_status(name):
        try:
            return "Configured" if st.secrets.get(name) else "Not configured"
        except Exception:
            return "Not configured"
    required = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "APP_PASSWORD"]
    optional = ["OPENFIGI_API_KEY", "COINGECKO_API_KEY", "FMP_API_KEY", "TWELVE_DATA_API_KEY"]
    with st.expander("Secrets status"):
        st.dataframe(pd.DataFrame(
            [{"Secret": name, "Required": "Yes", "Status": secret_status(name)} for name in required] +
            [{"Secret": name, "Required": "No", "Status": secret_status(name)} for name in optional]),
            width="stretch", hide_index=True)
    render_section_card("Data providers", "Free sources lead the waterfall; paid-key adapters remain optional.")
    settings_engine = MarketDataEngine(s.get("scraping_enabled", True), s.get("rate_limit_seconds", .25))
    provider_rows = st.session_state.provider_status or settings_engine.provider_status_rows(s.get("news_enabled", True))
    st.dataframe(pd.DataFrame(provider_rows), width="stretch", hide_index=True)
    render_section_card("Strategy settings", "Long-term allocation and risk guardrails used by the optimizer.")
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
    render_section_card("Target allocation")
    target_df = pd.DataFrame([{"Category": key, "Target weight %": value} for key, value in st.session_state.targets.items()])
    targets = st.data_editor(target_df, num_rows="dynamic", width="stretch", hide_index=True,
                             column_config={"Category": st.column_config.SelectboxColumn(options=SUPPORTED_CATEGORIES)})
    if st.button("Apply settings", type="primary"):
        st.session_state.targets = dict(zip(targets["Category"], targets["Target weight %"]))
        recompute_models()
        database.save_settings({**st.session_state.settings, "target_allocations": st.session_state.targets})
        total = sum(st.session_state.targets.values())
        if abs(total - 100) < .01: safe_toast("Settings saved", "💾")
        else: render_alert(f"Targets total {total:.2f}%; adjust them to 100%.", "warning")
    render_section_card("Scalable assumptions", "PRIME+ · Preferred venue EIX/gettex · Avoid Xetra unless needed · €250 direct-trade threshold · €1.98 default below-threshold round trip · Whole units for stocks/ETFs/ETCs/ETPs · Fractional crypto allowed.")
    render_alert("Final prices, availability, fees, taxes, and savings-plan changes must be checked and applied manually in Scalable Capital.", "info")
    render_section_card("Danger zone", "Destructive actions require a separate confirmation and never affect your broker account.")
    danger_a, danger_b, danger_c = st.columns(3)
    clear_values = danger_a.checkbox("Confirm clear valuation history")
    if danger_a.button("Clear valuation history", disabled=not clear_values):
        database.clear_snapshots(); set_flash_success("Valuation history cleared"); st.rerun()
    clear_recs = danger_b.checkbox("Confirm clear recommendation history")
    if danger_b.button("Clear recommendation history", disabled=not clear_recs):
        database.clear_recommendations(); set_flash_success("Recommendation history cleared"); st.rerun()
    reset_demo = danger_c.checkbox("Confirm reset to sample data")
    if danger_c.button("Reset sample data", disabled=not reset_demo):
        st.session_state.holdings = holdings_to_dataframe(SAMPLE_HOLDINGS)
        st.session_state.candidates = _normalise_candidates(pd.DataFrame(SAMPLE_CANDIDATES))
        st.session_state.plans = _plans_with_categories(pd.DataFrame(SAMPLE_SAVINGS_PLANS))
        database.save_holdings(st.session_state.holdings); database.save_candidates(st.session_state.candidates)
        database.save_savings_plans(st.session_state.plans); recompute_models()
        set_flash_success("Sample data restored"); st.rerun()


user_id = require_authentication()
if not user_id:
    st.stop()
try:
    gateway = SupabaseGateway(get_supabase_client(user_id))
    database = Database(gateway, user_id)
    initialise_state(database)
except SupabaseConnectionError as exc:
    render_alert(str(exc), "danger")
    render_alert("Add SUPABASE_URL and SUPABASE_ANON_KEY to Streamlit secrets, then run supabase_schema.sql.", "info")
    st.stop()

PAGES = ["Portfolio", "Market", "Strategy", "Rebalance", "Settings"]
with st.sidebar:
    st.markdown('<div class="sidebar-brand"><div class="sidebar-title">Financial Hub</div>'
                '<div class="sidebar-subtitle">Wealth command center</div></div>', unsafe_allow_html=True)
    page = st.radio("Navigation", PAGES)
    market_status = "Error" if st.session_state.enrichment_warnings else "Live" if st.session_state.settings.get("live_enabled", True) else "Disabled"
    market_class = "danger-pill" if market_status == "Error" else "warning-pill" if market_status == "Disabled" else "info-pill"
    refresh_text = str(st.session_state.last_price_fetch or "Not yet")
    st.markdown(f'<div class="sidebar-status">'
                f'<div class="sidebar-status-row"><span>Supabase</span><span class="success-pill status-pill">Connected</span></div>'
                f'<div class="sidebar-status-row"><span>Market data</span><span class="{market_class} status-pill">{market_status}</span></div>'
                f'<div class="sidebar-status-row"><span>Last refresh</span><span>{refresh_text}</span></div></div>',
                unsafe_allow_html=True)
    render_alert("Decision support only. No broker connection or auto-trading.", "info")
    logout_button()

{"Portfolio": portfolio_section, "Market": market_data_news_section,
 "Strategy": strategy_section, "Rebalance": rebalance_section, "Settings": settings_page}[page]()
st.markdown('<div class="privacy-footer">Private app · Data saved in Supabase · No broker connection · No auto-trading</div>',
            unsafe_allow_html=True)
