"""Production-style Streamlit wealth manager backed by Supabase."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import logout_button, require_authentication
from asset_quality import assess_asset_readiness
from chart_components import (create_allocation_chart, create_current_vs_target_chart,
                              create_portfolio_value_chart, create_savings_plan_before_after_chart,
                              create_winners_losers_chart, style_figure)
from db import Database
from coverage_engine import (DeepScanEngine, calculate_data_coverage,
                             repair_missing_symbols as repair_symbol_batch)
from data_cache import SupabaseDataCache, is_stale, parse_timestamp, utc_now
from data_gap_report import generate_data_gap_report
from market_data import MarketQuote, get_fx_rate_to_eur, get_market_quote
from market_data_engine import MarketDataEngine
from market_research import build_market_research
from master_rebalance import PIPELINE_LABELS, run_full_rebalance_pipeline
from metadata_enrichment import accept_suggestion
from news_provider import deduplicate_news, get_asset_news, get_market_news, rank_news_by_relevance
from optimizer import generate_market_aware_recommendations, recommendation_execution_order
from provider_registry import get_provider_registry
from recommendation_engine import build_recommendation_report, build_structured_rebalance_report
from rebalancer_rulebook import (BROKER_RULES, CONFIRMED_BASELINE_DATE, CONFIRMED_BASELINE_SOURCE,
                                 CURRENT_RULEBOOK, DIRECT_TRADE_RULES, REBALANCE_WORKFLOW,
                                 SAVINGS_PLAN_RULES, THEMES_REQUIRED_FOR_REVIEW)
from rulebook_engine import (create_execution_order, create_rebalance_checklist,
                             format_allocation_table, format_immediate_buy_sell_table,
                             format_savings_plan_table, get_base_target_allocation,
                             get_confirmed_baseline_holdings, get_confirmed_savings_plan,
                             validate_rebalance_guardrails)
from rebalancer import (allocation_table, calculate_allocation, calculate_drift, calculate_total_invested,
                        calculate_total_value, calculate_unrealised_pl, holdings_to_dataframe)
from sample_data import (CANDIDATE_COLUMNS, SAMPLE_CANDIDATES, SAMPLE_HOLDINGS, SAMPLE_SAVINGS_PLANS,
                         SUPPORTED_CATEGORIES, TARGET_ALLOCATIONS)
from savings_plan_optimizer import optimize_savings_plans
from retry_queue import RetryQueue
from savings_plan_manager import (create_savings_plan_execution_checklist,
                                  normalize_savings_plan_rows, validate_savings_plan_budget)
from screenshot_parser import (create_holding_from_screenshot_data, parse_scalable_text,
                               update_holding_by_isin, validate_screenshot_holding)
from source_audit import suggestion_audit_rows
from scoring import score_assets
from sentiment_engine import classify_sentiment, create_market_sentiment_summary
from storage import ScreenshotStorage
from symbol_resolver import (SymbolResolver, fresh_bad_symbols, is_probably_invalid_symbol_error,
                             store_symbol_resolution as cache_symbol_resolution)
from styles import inject_premium_css
from strategy_engine import (create_strategy_explanation, get_current_strategy,
                             refresh_market_strategy)
from supabase_client import SupabaseConnectionError, SupabaseGateway, get_supabase_client
from ui_components import (render_alert,
                           render_empty_state, render_flow_steps, render_hero_summary,
                           render_metric_card, render_news_card, render_page_header,
                           render_rebalance_summary, render_recommendation_card,
                           render_section_card, render_status_pill, render_strategy_summary_card,
                           render_flash_message, safe_toast, set_flash_success,
                           gap_card)
from valuation import calculate_historical_gains, portfolio_market_history, valuate_holdings

st.set_page_config(page_title="Financial Hub", page_icon="◆", layout="wide",
                   initial_sidebar_state="expanded")
inject_premium_css()

HOLDING_DISPLAY = {"instrument": "Instrument", "isin": "ISIN", "ticker_id": "Ticker/ID",
    "price_symbol": "Price Symbol", "asset_type": "Asset type", "category": "Category", "quantity": "Quantity",
    "resolved_price_symbol": "Resolved market symbol",
    "alpha_vantage_symbol": "Alpha Vantage symbol",
    "alpha_vantage_last_price": "Alpha Vantage last price",
    "alpha_vantage_previous_close": "Alpha Vantage previous close",
    "alpha_vantage_currency": "Alpha Vantage currency",
    "alpha_vantage_last_updated": "Alpha Vantage last updated",
    "alpha_vantage_confidence": "Alpha Vantage confidence",
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


@st.cache_data(ttl=900, show_spinner=False)
def cached_quote(symbol: str, bucket: int, alpha_vantage_symbol: str = "",
                 alpha_vantage_currency: str = ""):
    return get_market_quote(symbol, alpha_vantage_symbol, alpha_vantage_currency)


@st.cache_data(ttl=43200, show_spinner=False)
def cached_fx(currency: str, bucket: int):
    rate = get_fx_rate_to_eur(currency)
    return rate, "" if rate else "FX rate unavailable"


_STRUCTURED_DISPLAY_COLUMNS = {
    "conflict", "metadata_conflicts", "provider_status", "enrichment_audit",
    "web_scrape_sources", "enrichment_suggestions", "suggested_price_symbols",
    "warnings", "strategy_snapshot", "valuation_snapshot", "recommendations",
    "savings_plan_changes", "news_inputs", "sentiment_summary",
}


def _display_safe_frame(frame) -> pd.DataFrame:
    """Return an Arrow-safe copy without changing the stored application data."""
    safe = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    for column in safe.columns:
        values = safe[column]
        has_nested = values.map(lambda value: isinstance(value, (dict, list, tuple, set))).any()
        if has_nested or str(column).lower() in _STRUCTURED_DISPLAY_COLUMNS:
            safe[column] = values.map(
                lambda value: json.dumps(value, ensure_ascii=False, default=str)
                if isinstance(value, (dict, list, tuple, set))
                else "" if value is None or (isinstance(value, float) and pd.isna(value))
                else str(value)
            )
    return safe


def safe_dataframe(frame, **kwargs):
    """Display a DataFrame after serializing nested audit values for Arrow."""
    return st.dataframe(_display_safe_frame(frame), **kwargs)


def _normalise_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    numeric = ["ter_pct", "fund_size_eur", "manual_spread_estimate_pct", "liquidity_score",
               "quality_score", "momentum_score", "valuation_score", "cost_score",
               "portfolio_fit_score", "risk_control_score", "total_score",
               "alpha_vantage_last_price", "alpha_vantage_previous_close"]
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
    app_settings = {"base_currency": "EUR", "monthly_savings_budget": SAVINGS_PLAN_RULES["monthly_budget_eur"],
                    "max_single_holding_weight": 25.0, "max_crypto_weight": 5.0,
                    "cash_min_pct": 0.0, "cash_max_pct": 2.0,
                    "direct_trade_minimum": DIRECT_TRADE_RULES["minimum_efficient_trade_eur"],
                    "small_trade_round_trip_fee": DIRECT_TRADE_RULES["below_threshold_fee_eur"],
                    "live_enabled": True, "scraping_enabled": True, "news_enabled": True,
                    "rate_limit_seconds": 0.25, "refresh_interval": 300, "risk_profile": "Aggressive"}
    app_settings.update({key: value for key, value in saved_settings.items() if key in app_settings})
    app_settings["direct_trade_minimum"] = DIRECT_TRADE_RULES["minimum_efficient_trade_eur"]
    app_settings["small_trade_round_trip_fee"] = DIRECT_TRADE_RULES["below_threshold_fee_eur"]
    try: provider_failures = database.load_provider_failures()
    except (AttributeError, SupabaseConnectionError): provider_failures = []
    try: deep_job = database.load_active_enrichment_job()
    except (AttributeError, SupabaseConnectionError): deep_job = None
    try: source_audit = database.load_data_audit()
    except (AttributeError, SupabaseConnectionError): source_audit = pd.DataFrame()
    try: symbol_cache = database.load_symbol_resolutions()
    except (AttributeError, SupabaseConnectionError): symbol_cache = []
    for cached_resolution in symbol_cache:
        cache_symbol_resolution(cached_resolution.get("asset_key", ""), cached_resolution)
    cached_quotes, cached_fx_rates, cached_fetches = {}, {"EUR": 1.0}, []
    try:
        for row in database.load_market_data_cache():
            payload = row.get("payload") or {}; key = str(row.get("cache_key", ""))
            fetched_at = payload.get("fetched_at") or row.get("fetched_at", "")
            if row.get("data_kind") == "price" and key.startswith("price:"):
                symbol = key.removeprefix("price:")
                if symbol not in cached_quotes:
                    expires_at = parse_timestamp(row.get("expires_at"))
                    cached_quotes[symbol] = MarketQuote(
                        symbol=symbol, latest_price=payload.get("latest_price"),
                        previous_close=payload.get("previous_close"), currency=payload.get("currency", ""),
                        fetched_at=fetched_at, histories={},
                        stale=bool(expires_at <= utc_now()) if expires_at else is_stale(fetched_at, "price"),
                        provider=payload.get("provider") or row.get("provider", ""),
                        confidence=payload.get("confidence", ""),
                        provider_symbol=payload.get("provider_symbol", ""))
                    if fetched_at: cached_fetches.append(str(fetched_at))
            elif row.get("data_kind") == "fx" and key.startswith("fx:"):
                currency = key.removeprefix("fx:")
                if currency not in cached_fx_rates and payload.get("rate"):
                    cached_fx_rates[currency] = float(payload["rate"])
    except (AttributeError, SupabaseConnectionError, TypeError, ValueError):
        pass
    try:
        cached_news = database.load_news()
        cached_news_items = cached_news.to_dict("records") if not cached_news.empty else []
    except (AttributeError, SupabaseConnectionError): cached_news_items = []
    cached_sentiment = (create_market_sentiment_summary(cached_news_items, pd.DataFrame()) if cached_news_items else
                        {"sentiment": "Neutral", "market_regime": "Neutral", "confidence": "Low",
                         "explanation": "News has not been refreshed yet."})
    defaults = {
        "holdings": db_holdings if not db_holdings.empty else holdings_to_dataframe(SAMPLE_HOLDINGS),
        "candidates": _normalise_candidates(db_candidates if not db_candidates.empty else pd.DataFrame(SAMPLE_CANDIDATES)),
        "targets": saved_settings.get("target_allocations", TARGET_ALLOCATIONS.copy()),
        "quotes": cached_quotes, "fx_rates": cached_fx_rates,
        "last_price_fetch": max(cached_fetches, default=None), "enrichment_audit": pd.DataFrame(), "enrichment_warnings": [],
        "provider_status": [], "provider_failures": provider_failures, "deep_scan_job": deep_job,
        "deep_scan_progress": [], "data_gap_report": pd.DataFrame(), "source_audit": source_audit,
        "symbol_resolution_cache": symbol_cache,
        "news_items": cached_news_items, "sentiment": cached_sentiment,
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
    details = pd.DataFrame([{**row.to_dict(), **assess_asset_readiness(row, False)}
                            for _, row in details.iterrows()])
    st.session_state.valuation_details = details
    st.session_state.holdings = holdings_to_dataframe(details.to_dict("records"))
    drift = calculate_drift(st.session_state.holdings, st.session_state.targets)
    research = build_market_research(st.session_state.quotes)
    score_settings = st.session_state.settings.copy()
    score_settings["portfolio_total_eur"] = calculate_total_value(st.session_state.holdings)
    score_settings["current_category_counts"] = details[details["category"] != "Cash"].groupby("category").size().to_dict()
    scored_candidates = score_assets(st.session_state.candidates, research, drift, score_settings, False)
    for index, asset in scored_candidates.iterrows():
        quote = st.session_state.quotes.get(str(asset.get("resolved_price_symbol") or asset.get("price_symbol", "")))
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
    optimizer_settings["etf_candidate_ter_coverage"] = calculate_data_coverage(
        pd.DataFrame(), scored_candidates).get("ter_coverage", 0.0)
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
    symbol_inputs = {}
    for frame in (st.session_state.holdings, st.session_state.candidates):
        for _, asset in frame.iterrows():
            alpha_symbol = str(asset.get("alpha_vantage_symbol") or "").strip()
            symbol = str(asset.get("resolved_price_symbol") or asset.get("price_symbol") or alpha_symbol).strip()
            if symbol:
                symbol_inputs.setdefault(symbol, {
                    "alpha_symbol": alpha_symbol,
                    "alpha_currency": str(asset.get("alpha_vantage_currency") or "").strip(),
                })
    cooling_down = fresh_bad_symbols(st.session_state.get("symbol_resolution_cache", []))
    quick_retry = RetryQueue()
    quick_retry.memory = list(st.session_state.get("provider_failures", []))
    initial_quick_failures = len(quick_retry.memory)
    symbols = sorted(symbol for symbol in symbol_inputs
                     if symbol and symbol.lower() != "nan" and symbol not in cooling_down
                     and quick_retry.can_retry("Quick price", symbol))
    with ThreadPoolExecutor(max_workers=4) as executor:
        quotes = dict(zip(symbols, executor.map(
            lambda symbol: cached_quote(symbol, bucket, symbol_inputs[symbol]["alpha_symbol"],
                                        symbol_inputs[symbol]["alpha_currency"]), symbols)))
    currencies = {quote.currency for quote in quotes.values() if quote.currency}
    fx_rates = {"EUR": 1.0}
    pending_currencies = sorted(currencies - {"EUR"})
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(pending_currencies)))) as executor:
        rates = list(executor.map(lambda currency: cached_fx(currency, bucket), pending_currencies))
    for currency, (rate, _) in zip(pending_currencies, rates):
        if rate: fx_rates[currency] = rate
    st.session_state.quotes, st.session_state.fx_rates = quotes, fx_rates
    successful = [quote.fetched_at for quote in quotes.values() if quote.is_available]
    if successful:
        st.session_state.last_price_fetch = max(successful)
    recompute_models()
    try:
        cache = SupabaseDataCache(database.gateway, database.user_id)
        for symbol, quote in quotes.items():
            if quote.is_available:
                cache.set(f"price:{symbol}", {"latest_price": quote.latest_price,
                          "previous_close": quote.previous_close, "currency": quote.currency,
                          "fetched_at": quote.fetched_at, "provider": quote.provider,
                          "confidence": quote.confidence, "provider_symbol": quote.provider_symbol},
                          quote.provider or "Market Data Engine", "price")
        for currency, rate in fx_rates.items():
            cache.set(f"fx:{currency}", {"rate": rate}, "ECB/Alpha Vantage/yfinance", "fx")
        database.save_holdings(st.session_state.holdings)
    except (AttributeError, SupabaseConnectionError):
        pass  # Cache schema may not be installed yet; valuation remains usable in session.
    failed = [symbol for symbol, quote in quotes.items() if not quote.is_available]
    for symbol in failed:
        quote = quotes[symbol]
        quick_retry.record_failure("Quick price", {"instrument": symbol}, symbol,
                                   "Provider timeout" if "timeout" in str(quote.error).lower() else "Price unavailable",
                                   quote.error or "No verified live price")
    for failure in quick_retry.memory[initial_quick_failures:]:
        try: database.save_provider_failure(failure)
        except (AttributeError, SupabaseConnectionError): pass
    if len(quick_retry.memory) > initial_quick_failures:
        st.session_state.provider_failures = quick_retry.memory
    if failed:
        resolver = SymbolResolver()
        new_cache = list(st.session_state.get("symbol_resolution_cache", []))
        for frame in (st.session_state.holdings, st.session_state.candidates):
            for _, asset in frame.iterrows():
                symbol = str(asset.get("resolved_price_symbol") or asset.get("price_symbol") or "").strip()
                quote = quotes.get(symbol)
                if symbol in failed and quote and is_probably_invalid_symbol_error(quote.error):
                    record = asset.to_dict(); resolver.mark_bad_symbol(record, symbol, quote.error)
                    key = str(record.get("id") or record.get("isin") or record.get("wkn") or record.get("instrument") or "")
                    resolution = resolver.load_cached_symbol_resolution(key)
                    if resolution:
                        payload = {**resolution, "asset_key": key, "isin": record.get("isin", ""),
                                   "instrument": record.get("instrument", "")}
                        try: database.save_symbol_resolution(payload)
                        except (AttributeError, SupabaseConnectionError): pass
                        new_cache = [item for item in new_cache if item.get("asset_key") != key]
                        new_cache.insert(0, payload)
        st.session_state.symbol_resolution_cache = new_cache
    if cooling_down:
        st.caption(f"Skipped {len(cooling_down)} symbol candidate(s) still inside the seven-day failure cooldown.")
    if failed:
        render_alert("Live price unavailable; run Data Enrichment, then use manual fallback after enrichment failed: " + ", ".join(failed), "warning")


def valuation_dashboard():
    render_section_card("Live valuation", "Estimated portfolio value, performance windows, and data-quality diagnostics.")
    render_alert("Internet prices are research estimates. Check final live buy/sell prices manually in Scalable Capital before execution.", "warning")
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
    stale = details[(details.get("price_stale", pd.Series(False, index=details.index)).fillna(False)) &
                    (details["category"] != "Cash")]
    if not missing.empty:
        render_alert("Missing live and fallback prices: " + ", ".join(missing["instrument"]), "danger")
    if not fallback.empty:
        render_alert("Live price unavailable; using manual fallback after enrichment failed: " + ", ".join(fallback["instrument"]), "warning")
    if not stale.empty:
        render_alert("Stale market quote ignored for valuation: " + ", ".join(stale["instrument"]), "warning")
    chart_left, chart_right = st.columns(2)
    holdings_chart = details.sort_values("current_value_eur")
    holdings_figure = style_figure(px.bar(holdings_chart, x="current_value_eur", y="instrument", orientation="h",
                                   title="Holdings value", color_discrete_sequence=["#176B87"]), showlegend=False)
    chart_left.plotly_chart(holdings_figure, width="stretch", key="valuation_holdings_chart")
    winners = details.sort_values("daily_gain_eur")
    chart_right.plotly_chart(create_winners_losers_chart(winners), width="stretch", key="valuation_winners_chart")
    safe_dataframe(details, width="stretch", hide_index=True)
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
    existing = st.session_state.holdings.copy()
    show_advanced = st.toggle("Show advanced holding columns", value=False, key="portfolio_advanced_columns")
    compact_columns = ["instrument", "isin", "price_symbol", "resolved_price_symbol", "asset_type", "category", "quantity",
                       "manual_current_price", "live_current_price", "price_source", "current_value_eur",
                       "buy_in_value_eur", "pl_eur", "pl_pct"]
    selected_columns = [column for column in (HOLDING_DISPLAY if show_advanced else compact_columns) if column in existing]
    display = existing[selected_columns].rename(columns=HOLDING_DISPLAY)
    source = existing.get("price_source", pd.Series("Missing", index=existing.index)).fillna("Missing").astype(str)
    stale_flags = existing.get("price_stale", pd.Series(False, index=existing.index)).fillna(False).astype(bool)
    display["Data quality"] = [
        "● Manual fallback · live quote stale" if stale and "manual" in value.lower()
        else "● Scalable screenshot · live quote stale" if stale and "scalable" in value.lower()
        else "● Stale live price" if stale and "live" in value.lower()
        else "● Scalable screenshot" if "scalable" in value.lower()
        else "● Manual fallback" if "manual" in value.lower()
        else "● Missing" if "missing" in value.lower() else f"● {value or 'Live market data'}"
        for value, stale in zip(source, stale_flags)]
    valuation_ready = existing.get("valuation_ready", pd.Series(False, index=existing.index)).fillna(False)
    recommendation_ready = existing.get("recommendation_ready", pd.Series(False, index=existing.index)).fillna(False)
    display["Readiness"] = ["● Recommendation ready" if rec else "● Valuation ready" if val else "● Review required"
                            for val, rec in zip(valuation_ready, recommendation_ready)]
    disabled_columns = [column for column in ["Live current price", "Price source", "Current value EUR", "P/L EUR", "P/L %",
                        "Alpha Vantage last price", "Alpha Vantage previous close", "Alpha Vantage currency",
                        "Alpha Vantage last updated", "Alpha Vantage confidence", "Data quality", "Readiness"]
                        if column in display]
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


def candidate_universe():
    render_section_card("Candidate assets", "Research assets you do not own yet without weakening buy/add readiness rules.")
    render_alert("The Market Data Engine enriches first. Unresolved or conflicting facts move to manual fallback after enrichment failed; incomplete candidates stay blocked from buy/add.", "info")
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
    provider_columns = ["Alpha Vantage Last Price", "Alpha Vantage Previous Close",
                        "Alpha Vantage Currency", "Alpha Vantage Last Updated", "Alpha Vantage Confidence"]
    edited = st.data_editor(display, num_rows="dynamic", width="stretch", hide_index=True,
        disabled=SCORE_COLUMNS + [column for column in provider_columns if column in display],
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
        safe_dataframe(frame[columns], width="stretch", hide_index=True)
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
    safe_dataframe(combined[columns].sort_values("quality_score", ascending=False), width="stretch", hide_index=True,
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
        safe_dataframe(recommendations, width="stretch", hide_index=True)


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
    safe_dataframe(report, width="stretch", hide_index=True)
    a, b = st.columns(2)
    a.download_button("Export recommendation report CSV", report.to_csv(index=False), "recommendation_report.csv", "text/csv")
    if b.button("Save report to Supabase history"):
        database.save_recommendations(report); safe_toast("Recommendation report saved", "💾")


def _asset_matches(row, identifier: str) -> bool:
    return str(row.get("isin") or row.get("instrument") or "") == str(identifier)


def _run_data_enrichment(force_web: bool = False, selected_identifier: str | None = None,
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
    if selected_identifier:
        holding_mask = holdings.apply(lambda row: _asset_matches(row, selected_identifier), axis=1)
        candidate_mask = candidates.apply(lambda row: _asset_matches(row, selected_identifier), axis=1)
        if holding_mask.any():
            enriched, audit = engine.enrich_assets(holdings.loc[holding_mask], False, force_web)
            replacement = enriched.iloc[0].to_dict()
            records = [replacement if _asset_matches(row, selected_identifier) else row
                       for row in holdings.to_dict("records")]
            holdings = pd.DataFrame(records)
        elif candidate_mask.any():
            enriched, audit = engine.enrich_assets(candidates.loc[candidate_mask], True, force_web)
            replacement = enriched.iloc[0].to_dict()
            records = [replacement if _asset_matches(row, selected_identifier) else row
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
    enrichment_source_rows = []
    for frame in (holdings, candidates):
        for _, asset in frame.iterrows():
            enrichment_source_rows.extend(suggestion_audit_rows(asset.to_dict()))
            resolution = asset.get("symbol_resolution")
            if isinstance(resolution, dict):
                payload = {**resolution, "asset_key": str(asset.get("isin") or asset.get("instrument")),
                           "isin": asset.get("isin", ""), "instrument": asset.get("instrument", "")}
                try: database.save_symbol_resolution(payload)
                except (AttributeError, SupabaseConnectionError): pass
    try:
        database.save_data_audit(enrichment_source_rows)
        if enrichment_source_rows:
            st.session_state.source_audit = pd.concat(
                [pd.DataFrame(enrichment_source_rows), st.session_state.source_audit], ignore_index=True).head(2000)
    except (AttributeError, SupabaseConnectionError): pass
    st.session_state.holdings = holdings_to_dataframe(holdings.to_dict("records"))
    st.session_state.candidates = _normalise_candidates(candidates)
    st.session_state.enrichment_audit = audit
    st.session_state.enrichment_warnings = engine.warnings
    st.session_state.provider_status = engine.provider_status_rows(settings.get("news_enabled", True))
    recompute_models()


def _merge_scanned_asset(result: dict) -> None:
    """Persist one completed deep-scan asset immediately for rerun/cancellation safety."""
    asset = result["asset"]; key = str(result["asset_key"])
    if result.get("symbol_resolution"):
        try: database.save_symbol_resolution({**result["symbol_resolution"], "asset_key": key,
                                               "isin": asset.get("isin", ""), "instrument": asset.get("instrument", "")})
        except (AttributeError, SupabaseConnectionError): pass
    if result.get("news_items"):
        merged_news = deduplicate_news(list(st.session_state.get("news_items", [])) + result["news_items"])
        st.session_state.news_items = merged_news
        try: database.save_news(merged_news)
        except (AttributeError, SupabaseConnectionError): pass
    if result["is_candidate"]:
        rows = [asset if str(row.get("isin") or row.get("instrument")) == key else row
                for row in st.session_state.candidates.to_dict("records")]
        st.session_state.candidates = _normalise_candidates(pd.DataFrame(rows))
        database.save_candidates(st.session_state.candidates)
    else:
        rows = [asset if str(row.get("isin") or row.get("instrument")) == key else row
                for row in st.session_state.holdings.to_dict("records")]
        st.session_state.holdings = holdings_to_dataframe(rows)
        database.save_holdings(st.session_state.holdings)
    audit_rows = []
    for field in ("price_symbol", "live_current_price", "currency", "fx_rate_to_eur", "ter_pct",
                  "fund_size_eur", "factsheet_url", "issuer", "asset_type", "category"):
        value = asset.get(field)
        if value not in (None, ""):
            audit_rows.append({"asset_key": key, "isin": asset.get("isin", ""), "field_name": field,
                "field_value": value, "provider": asset.get("data_source", "Market Data Engine"),
                "source_url": asset.get("source_url", ""), "source_title": asset.get("issuer", ""),
                "fetched_at": asset.get("last_updated") or datetime.now(timezone.utc).isoformat(),
                "confidence": asset.get("data_confidence", "Low"), "extraction_method": "staged source waterfall",
                "user_confirmed": bool(asset.get("confirmed_by_user", False)),
                "conflict": (asset.get("metadata_conflicts") or {}).get(field)})
    audit_rows.extend(suggestion_audit_rows(asset))
    try:
        database.save_data_audit(audit_rows)
        st.session_state.source_audit = pd.concat([pd.DataFrame(audit_rows), st.session_state.source_audit],
                                                   ignore_index=True).head(2000)
    except (AttributeError, SupabaseConnectionError): pass


def _repair_symbols_on_demand(progress_callback=None) -> dict:
    resolver = SymbolResolver()
    assets = st.session_state.holdings.to_dict("records") + st.session_state.candidates.to_dict("records")
    results = repair_symbol_batch(assets, resolver, max_workers=4, progress_callback=progress_callback)
    for item in results:
        saved_resolution = {**item["resolution"], "asset_key": str(item["asset"].get("isin") or item["asset"].get("instrument")),
                            "isin": item["asset"].get("isin", ""),
                            "instrument": item["asset"].get("instrument", "")}
        try: database.save_symbol_resolution(saved_resolution)
        except (AttributeError, SupabaseConnectionError): pass
        cache_rows = [row for row in st.session_state.get("symbol_resolution_cache", [])
                      if row.get("asset_key") != saved_resolution["asset_key"]]
        st.session_state.symbol_resolution_cache = [saved_resolution] + cache_rows
    chosen = {str(item["asset"].get("isin") or item["asset"].get("instrument")): item["resolution"].get("chosen_symbol")
              for item in results if item["resolution"].get("chosen_symbol")}
    if chosen:
        holdings = st.session_state.holdings.copy(); candidates = st.session_state.candidates.copy()
        for index, row in holdings.iterrows():
            key = str(row.get("isin") or row.get("instrument"))
            if chosen.get(key):
                holdings.loc[index, "resolved_price_symbol"] = chosen[key]
                if not str(row.get("price_symbol", "") or "").strip(): holdings.loc[index, "price_symbol"] = chosen[key]
        for index, row in candidates.iterrows():
            key = str(row.get("isin") or row.get("instrument"))
            if chosen.get(key):
                candidates.loc[index, "resolved_price_symbol"] = chosen[key]
                if not str(row.get("price_symbol", "") or "").strip(): candidates.loc[index, "price_symbol"] = chosen[key]
        st.session_state.holdings = holdings_to_dataframe(holdings.to_dict("records"))
        st.session_state.candidates = _normalise_candidates(candidates)
        database.save_holdings(st.session_state.holdings); database.save_candidates(st.session_state.candidates)
        recompute_models()
    return {"tested": len(results), "resolved": len(chosen), "results": results}


def _run_deep_scan_chunk(max_assets: int = 5, progress_callback=None) -> dict:
    total = len(st.session_state.holdings) + len(st.session_state.candidates)
    job = st.session_state.get("deep_scan_job") or {"job_type": "deep_scan", "status": "Pending",
        "total_assets": total, "processed_assets": 0, "current_asset": "", "warnings": [],
        "completed_keys": [], "started_at": datetime.now(timezone.utc).isoformat()}
    job["status"] = "Running"; job["updated_at"] = datetime.now(timezone.utc).isoformat()
    try: job = database.save_enrichment_job(job)
    except (AttributeError, SupabaseConnectionError): pass
    retry_queue = RetryQueue()
    retry_queue.memory = list(st.session_state.get("provider_failures", []))
    initial_failure_count = len(retry_queue.memory)
    engine = MarketDataEngine(
        st.session_state.settings.get("scraping_enabled", True),
        st.session_state.settings.get("rate_limit_seconds", .25), retry_queue=retry_queue)
    scanner = DeepScanEngine(engine, SymbolResolver(), max_workers=4, max_asset_seconds=45,
                             news_fetcher=get_asset_news)
    def save_partial(result):
        _merge_scanned_asset(result)
        job["processed_assets"] = int(job.get("processed_assets", 0)) + 1
        job["current_asset"] = result["asset"].get("instrument", result["asset_key"])
        job["completed_keys"] = sorted(set(job.get("completed_keys", [])) | {result["asset_key"]})
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        try: database.save_enrichment_job(job)
        except (AttributeError, SupabaseConnectionError): pass
    result = scanner.run_chunk(st.session_state.holdings, st.session_state.candidates, max_assets,
                               set(job.get("completed_keys", [])), progress_callback, save_partial)
    for failure in retry_queue.memory[initial_failure_count:]:
        try: database.save_provider_failure(failure)
        except (AttributeError, SupabaseConnectionError): pass
    recompute_models()
    gaps = generate_data_gap_report(st.session_state.scored_current, st.session_state.scored_candidates,
                                    st.session_state.get("provider_failures", []),
                                    st.session_state.get("symbol_resolution_cache", []))
    st.session_state.data_gap_report = gaps; job["warnings"] = list(job.get("warnings", [])) + result["warnings"]
    job["status"] = "Completed" if result["remaining"] == 0 else "Paused"
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    if job["status"] == "Completed": job["completed_at"] = job["updated_at"]
    try: job = database.save_enrichment_job(job)
    except (AttributeError, SupabaseConnectionError): pass
    st.session_state.deep_scan_job = job; st.session_state.enrichment_audit = pd.DataFrame(engine.audit)
    try: st.session_state.provider_failures = database.load_provider_failures()
    except (AttributeError, SupabaseConnectionError): st.session_state.provider_failures = retry_queue.memory
    return {**result, "job": job, "gap_report": gaps}


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
                    holding["screenshot_path"] = ScreenshotStorage(database.gateway, database.user_id).upload(
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
    non_cash = details[details["category"] != "Cash"]
    live_count = int((~non_cash["price_source"].isin(["Manual fallback", "Scalable screenshot", "Missing", ""])).sum())
    fallback_count = int(non_cash["price_source"].isin(["Manual fallback", "Scalable screenshot"]).sum())
    with cards[6]: render_metric_card("Data quality", f"{live_count}/{len(non_cash)} live",
                                      f"{fallback_count} confirmed fallback", "warning" if fallback_count else "positive")
    action_left, action_right = st.columns([1, 3])
    if action_left.button("Quick Refresh Prices", type="primary", use_container_width=True):
        with st.spinner("Refreshing verified prices and FX..."):
            refresh_live_data(True)
        set_flash_success("Portfolio prices refreshed"); st.rerun()
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
        else: safe_dataframe(history, width="stretch", hide_index=True)
        st.download_button("Export valuation snapshots CSV", history.to_csv(index=False),
                           "valuation_history.csv", "text/csv")


def _missing_data_frame(gaps: pd.DataFrame | None = None) -> pd.DataFrame:
    if gaps is None:
        gaps = generate_data_gap_report(st.session_state.scored_current, st.session_state.scored_candidates,
                                        st.session_state.get("provider_failures", []),
                                        st.session_state.get("symbol_resolution_cache", []))
    gaps = gaps[gaps.get("Dataset", pd.Series(dtype=str)).isin(["Holding", "Candidate"])]
    if gaps.empty:
        return pd.DataFrame(columns=["Dataset", "Instrument", "ISIN",
                                     "Missing / repair needed", "Last auto repair"])
    grouped = gaps.groupby(["Dataset", "Asset", "ISIN"], dropna=False).agg({
        "Missing field": lambda values: ", ".join(dict.fromkeys(map(str, values))),
        "Last attempt": "max"}).reset_index()
    return grouped.rename(columns={"Asset": "Instrument", "Missing field": "Missing / repair needed",
                                   "Last attempt": "Last auto repair"})


def _replace_asset(dataset: str, identifier: str, updated: dict):
    if dataset == "Holding":
        records = [updated if _asset_matches(row, identifier) else row
                   for row in st.session_state.holdings.to_dict("records")]
        st.session_state.holdings = holdings_to_dataframe(records)
        database.save_holdings(st.session_state.holdings)
    else:
        records = [updated if _asset_matches(row, identifier) else row
                   for row in st.session_state.candidates.to_dict("records")]
        st.session_state.candidates = _normalise_candidates(pd.DataFrame(records))
        database.save_candidates(st.session_state.candidates)
    recompute_models()


def market_data_news_section():
    """Readable vertical Market workspace; advanced detail lives in expanders, not tabs."""
    render_flash_message()
    sentiment = st.session_state.sentiment
    providers = get_provider_registry()
    runtime_provider_status = {str(row.get("Provider")): row for row in st.session_state.get("provider_status", [])}
    for row in providers:
        runtime = runtime_provider_status.get(str(row.get("Provider")), {})
        row["Last success"] = runtime.get("Last success", row.get("Last success", ""))
        row["Last error"] = runtime.get("Last error", row.get("Last error", ""))
    coverage = calculate_data_coverage(st.session_state.scored_current, st.session_state.scored_candidates,
                                       st.session_state.news_items)
    gap_report = generate_data_gap_report(st.session_state.scored_current, st.session_state.scored_candidates,
                                          st.session_state.get("provider_failures", []),
                                          st.session_state.get("symbol_resolution_cache", []))
    missing = _missing_data_frame(gap_report)
    st.session_state.data_gap_report = gap_report
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
    with kpis[3]: render_metric_card("Missing items", len(gap_report), "Repair required" if len(gap_report) else "Complete", "warning" if len(gap_report) else "positive")
    with kpis[4]: render_metric_card("Last refresh", st.session_state.last_price_fetch or "Not yet")

    render_section_card("Staged refresh", "Cached Supabase values load immediately. Network work runs only when you choose a stage.")
    progress_display = st.empty()
    def progress_event(event):
        elapsed = f" · {event.get('elapsed', 0):.1f}s" if event.get("elapsed") is not None else ""
        progress_display.info(f"{event.get('asset', '')} · {event.get('provider', '')} · {event.get('status', '')}{elapsed}")
    action_a, action_b, action_c = st.columns(3)
    if action_a.button("Quick Refresh Prices", type="primary", use_container_width=True):
        with st.spinner("Refreshing prices and FX..."): refresh_live_data(True)
        set_flash_success("Live prices refreshed"); st.rerun()
    if action_b.button("Repair Missing Symbols", use_container_width=True):
        with st.spinner("Testing bounded symbol candidates..."): result = _repair_symbols_on_demand(progress_event)
        set_flash_success(f"Symbol repair finished: {result['resolved']} resolved"); st.rerun()
    if action_c.button("Refresh News & Sentiment", use_container_width=True):
        with st.spinner("Fetching public market news..."): _refresh_news_and_strategy(False)
        set_flash_success("Market news refreshed"); st.rerun()

    render_section_card("1. Market Data Engine", "Provider availability, capabilities, timeout budgets, and optional-key status.")
    provider_cols = st.columns(4)
    for index, row in enumerate(providers):
        with provider_cols[index % 4]:
            enabled = row.get("Status") == "Enabled"
            render_metric_card(row.get("Provider"), row.get("Status", "Unknown"), row.get("Purpose"),
                               "positive" if enabled else "neutral")
    with st.expander("Provider details and errors", expanded=False):
        safe_dataframe(pd.DataFrame(providers), width="stretch", hide_index=True)

    render_section_card("2. Data Coverage", "Coverage is calculated from cached holdings and candidates; it does not trigger network requests.")
    render_metric_card("Total assets", int(coverage.get("total_assets", 0)), "Holdings and candidates")
    alpha_assets = pd.concat([st.session_state.scored_current, st.session_state.scored_candidates],
                             ignore_index=True, sort=False)
    alpha_successes = int((alpha_assets.get("data_source", pd.Series(dtype=str)).astype(str) == "Alpha Vantage").sum())
    alpha_failures = sum(str(item.get("provider", "")) == "Alpha Vantage"
                         for item in st.session_state.get("provider_failures", []))
    alpha_cols = st.columns(2)
    with alpha_cols[0]: render_metric_card("Alpha Vantage successes", alpha_successes, "Cached asset records", "positive" if alpha_successes else "neutral")
    with alpha_cols[1]: render_metric_card("Alpha Vantage failures", alpha_failures, "Stored retry/audit records", "warning" if alpha_failures else "positive")
    coverage_items = [("Price", "price_coverage"), ("Symbol", "symbol_coverage"),
                      ("Metadata", "metadata_coverage"), ("TER/cost", "ter_coverage"),
                      ("FX", "fx_coverage"), ("Factsheet", "factsheet_coverage"), ("News", "news_coverage"),
                      ("Recommendation-ready", "recommendation_ready"), ("Valuation-ready", "valuation_ready")]
    for start in range(0, len(coverage_items), 4):
        coverage_cols = st.columns(4)
        for column, (label, key) in zip(coverage_cols, coverage_items[start:start + 4]):
            value = float(coverage.get(key, 0)); tone = "positive" if value >= 90 else "warning" if value >= 75 else "negative"
            with column: render_metric_card(label, f"{value:.1f}%", tone=tone)
    if coverage["price_coverage"] < 90: render_alert("Price coverage is below 90%; valuation confidence is reduced.", "warning")
    if coverage["metadata_coverage"] < 75: render_alert("Metadata coverage is below 75%; strategy and scoring confidence are reduced.", "warning")
    if coverage["ter_coverage"] < 75: render_alert("ETF TER/cost coverage is below 75%; incomplete ETF candidates remain blocked from buy/add.", "danger")
    if not gap_report.empty:
        preview_columns = st.columns(min(3, len(gap_report)))
        for column, (_, gap) in zip(preview_columns, gap_report.head(3).iterrows()):
            with column:
                gap_card(gap.get("Asset"), gap.get("Missing field"), gap.get("Error"),
                         gap.get("Suggested next action"), "Low")
    with st.expander("Open precise Data Gap Report", expanded=False):
        if gap_report.empty: render_empty_state("No detected gaps", "Cached data currently satisfies the configured coverage checks.")
        else: safe_dataframe(gap_report, width="stretch", hide_index=True)

    render_section_card("3. Missing Data Repair", "Suggestions remain separate from entered facts until you explicitly accept or confirm them.")
    repair_labels = [("Price symbol", "symbol"), ("TER/cost", "TER/cost"),
                     ("Category", "category"), ("Factsheet URL", "factsheet"),
                     ("Metadata conflicts", "metadata conflict")]
    repair_cols = st.columns(5)
    missing_text = missing.get("Missing / repair needed", pd.Series(dtype=str)).fillna("")
    for column, (label, token) in zip(repair_cols, repair_labels):
        count = int(missing_text.str.contains(token, case=False, regex=False).sum())
        with column: render_metric_card(label, count, "Needs attention" if count else "Complete", "warning" if count else "positive")
    if missing.empty:
        render_empty_state("No repair items", "The current holdings and candidate universe have no detected repair queue.")
    else:
        combined = pd.concat([st.session_state.holdings.assign(dataset="Holding"),
                              st.session_state.candidates.assign(dataset="Candidate")], ignore_index=True, sort=False)
        repair_rows = []
        for _, item in missing.iterrows():
            identifier = str(item["ISIN"] or item["Instrument"])
            matches = combined[(combined["dataset"] == item["Dataset"]) &
                               combined.apply(lambda row: _asset_matches(row, identifier), axis=1)]
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
        safe_dataframe(pd.DataFrame(repair_rows), width="stretch", hide_index=True)
        selected_row = st.selectbox("Choose an asset to repair", list(missing.index), key="market_repair_asset",
                                    format_func=lambda index: f"{missing.loc[index, 'Instrument']} · {missing.loc[index, 'ISIN'] or 'No ISIN'}")
        selected_summary = missing.loc[selected_row]
        dataset = selected_summary["Dataset"]
        selected = str(selected_summary["ISIN"] or selected_summary["Instrument"])
        source_frame = st.session_state.holdings if dataset == "Holding" else st.session_state.candidates
        asset = source_frame.loc[source_frame.apply(lambda row: _asset_matches(row, selected), axis=1)].iloc[0].to_dict()
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
            enrichment_attempted = bool(asset.get("manual_review_attempted", False))
            if not enrichment_attempted:
                render_alert("Run Auto repair first. Manual fallback unlocks after the source waterfall has been attempted.", "warning")
            manual_fields = ["price_symbol", "ter_pct", "asset_type", "category", "factsheet_url",
                             "scalable_compatible", "issuer", "currency"]
            field = st.selectbox("Field", manual_fields, key="market_manual_field")
            manual_value = st.text_input("Confirmed value", key="market_manual_value")
            confirmed = st.checkbox("I verified this value", key="market_manual_confirmed")
            if st.button("Save confirmed value", key="market_save_manual",
                         disabled=not (manual_value and confirmed and enrichment_attempted)):
                updated = dict(asset)
                if field == "ter_pct":
                    try: updated[field] = float(manual_value.replace(",", "."))
                    except ValueError: render_alert("Enter TER as a number, for example 0.20", "danger"); st.stop()
                elif field == "scalable_compatible":
                    updated[field] = manual_value.strip().lower() in {"true", "yes", "1", "confirmed"}
                else: updated[field] = manual_value.strip()
                updated["confirmed_by_user"] = True
                _replace_asset(dataset, selected, updated); st.rerun()

    render_section_card("4. Deep Data Scan", "Deep mode skips fresh complete assets and processes a small parallel chunk. Each completed asset is saved immediately.")
    job = st.session_state.get("deep_scan_job") or {}
    job_cols = st.columns(4)
    with job_cols[0]: render_metric_card("Status", job.get("status", "Not started"))
    with job_cols[1]: render_metric_card("Processed", int(job.get("processed_assets", 0) or 0))
    with job_cols[2]: render_metric_card("Total assets", int(job.get("total_assets", coverage["total_assets"]) or 0))
    with job_cols[3]: render_metric_card("Current asset", job.get("current_asset", "—") or "—")
    total_assets = max(1, int(job.get("total_assets", coverage["total_assets"]) or 1))
    st.progress(min(1.0, float(job.get("processed_assets", 0) or 0) / total_assets),
                text="Partial progress is stored in Supabase after every completed asset.")
    chunk_size = st.number_input("Assets per scan chunk", min_value=1, max_value=10, value=5, step=1)
    deep_a, deep_b = st.columns(2)
    deep_label = "Continue Deep Scan" if job.get("status") == "Paused" else "Run Deep Data Scan"
    if deep_a.button(deep_label, type="primary", use_container_width=True):
        with st.spinner("Running the next bounded deep-scan chunk..."): scan_result = _run_deep_scan_chunk(int(chunk_size), progress_event)
        set_flash_success(f"Deep scan saved {scan_result['processed']} assets; {scan_result['remaining']} remain"); st.rerun()
    if deep_b.button("Restart deep-scan queue", use_container_width=True, disabled=not bool(job)):
        cancelled = {**job, "status": "Cancelled", "completed_at": datetime.now(timezone.utc).isoformat(),
                     "updated_at": datetime.now(timezone.utc).isoformat()}
        try: database.save_enrichment_job(cancelled)
        except (AttributeError, SupabaseConnectionError): pass
        st.session_state.deep_scan_job = None; set_flash_success("Deep-scan queue reset"); st.rerun()
    render_alert("Streamlit Cloud does not guarantee background workers. Keep this page open during a chunk; cached portfolio views remain fast between chunks.", "info")

    render_section_card("Internet Enrichment", "Provider and safe-web attempts are cached and retained for review.")
    audit = st.session_state.enrichment_audit
    audit_cols = st.columns(3)
    with audit_cols[0]: render_metric_card("Audit events", len(audit))
    with audit_cols[1]: render_metric_card("Warnings", len(st.session_state.enrichment_warnings), tone="warning" if st.session_state.enrichment_warnings else "positive")
    with audit_cols[2]: render_metric_card("Web enrichment", "Enabled" if st.session_state.settings.get("scraping_enabled") else "Disabled")
    for warning in st.session_state.enrichment_warnings: render_alert(warning, "warning")
    with st.expander("Open enrichment audit", expanded=False):
        if audit.empty: render_empty_state("No enrichment audit yet", "Run enrichment to create the provider-by-provider evidence trail.")
        else: safe_dataframe(audit, width="stretch", hide_index=True)
        st.download_button("Export enrichment audit CSV", audit.to_csv(index=False), "enrichment_audit.csv", "text/csv")

    render_section_card("5. News & Sentiment", "GDELT, public RSS, and available yfinance headlines ranked against your portfolio and themes.")
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
            safe_dataframe(filtered[columns], width="stretch", hide_index=True,
                           column_config={"url": st.column_config.LinkColumn("Link")})

    render_section_card("Sentiment summary", "A transparent, recency-weighted blend of public-news language and observed market momentum.")
    sentiment_cols = st.columns(3)
    with sentiment_cols[0]: render_metric_card("Sentiment", sentiment.get("sentiment", "Neutral"), tone="info")
    with sentiment_cols[1]: render_metric_card("Regime", sentiment.get("market_regime", "Neutral"), tone="info")
    with sentiment_cols[2]: render_metric_card("Confidence", sentiment.get("confidence", "Low"), tone="warning")
    render_alert(sentiment.get("explanation", "Refresh market news to produce an explanation."), "info")
    if st.button("Use current sentiment in strategy refresh"):
        _refresh_news_and_strategy(True); set_flash_success("Strategy refreshed"); st.rerun()

    render_section_card("6. Source Audit", "Field-level source records, conflicts, failures, cooldowns, and the latest in-session enrichment trace.")
    failure_frame = pd.DataFrame(st.session_state.get("provider_failures", []))
    audit_tabs = st.columns(3)
    with audit_tabs[0]: render_metric_card("Audit events", len(audit))
    with audit_tabs[1]: render_metric_card("Provider failures", len(failure_frame), tone="warning" if len(failure_frame) else "positive")
    with audit_tabs[2]: render_metric_card("Retry queue", len(RetryQueue().due(failure_frame.to_dict("records") if not failure_frame.empty else [])))
    with st.expander("Provider failures and retry cooldowns", expanded=False):
        if failure_frame.empty: render_empty_state("No stored provider failures", "Failures will appear here without stopping the remaining waterfall.")
        else: safe_dataframe(failure_frame, width="stretch", hide_index=True)
    with st.expander("Field-level source audit", expanded=False):
        source_audit = st.session_state.get("source_audit", pd.DataFrame())
        if source_audit.empty: render_empty_state("No field audit yet", "Deep scans record provider, URL, confidence, extraction method, and conflicts here.")
        else: safe_dataframe(source_audit, width="stretch", hide_index=True)

    render_section_card("Candidate Asset Research", "Edit the candidate universe first; open rankings and detailed quality only when needed.")
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
    else: safe_dataframe(history, width="stretch", hide_index=True)


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


def _theme_ranking() -> pd.DataFrame:
    assets = pd.concat([st.session_state.scored_current, st.session_state.scored_candidates],
                       ignore_index=True, sort=False)
    if assets.empty:
        return pd.DataFrame(columns=["Theme", "Average score", "Assets"])
    assets["_theme"] = assets.get("theme", assets.get("category", "Other")).fillna("").replace("", "Other")
    score = pd.to_numeric(assets.get("total_score", 0), errors="coerce").fillna(0)
    assets["_score"] = score
    return (assets.groupby("_theme", as_index=False).agg(**{"Average score": ("_score", "mean"),
                                                            "Assets": ("_theme", "size")})
            .rename(columns={"_theme": "Theme"}).sort_values("Average score", ascending=False).round(2))


def _rulebook_context() -> dict:
    recommendations = st.session_state.recommendations
    direct = format_immediate_buy_sell_table(recommendations)
    bought = recommendations[recommendations.get("Action", pd.Series(dtype=str)).astype(str).str.contains("buy", case=False)] if not recommendations.empty else pd.DataFrame()
    watchlisted = recommendations[recommendations.get("Action", pd.Series(dtype=str)).astype(str).str.contains("watchlist|no trade", case=False, regex=True)] if not recommendations.empty else pd.DataFrame()
    return {"baseline_source": "Latest saved Supabase holdings; confirmed rulebook baseline is the reset reference",
            "last_recommendation_assumed_implemented": False,
            "market_data_refreshed": bool(st.session_state.get("last_price_fetch")),
            "news_refreshed": bool(st.session_state.get("news_items")),
            "themes_considered": list(THEMES_REQUIRED_FOR_REVIEW),
            "regions_considered": st.session_state.strategy.get("regions_considered", []),
            "themes_bought": bought.get("Instrument", pd.Series(dtype=str)).astype(str).tolist(),
            "themes_watchlisted": watchlisted.get("Instrument", pd.Series(dtype=str)).astype(str).tolist(),
            "trades": direct.to_dict("records"), "savings_plan_reviewed": True,
            "scalable_price_check_required": True, "emotional_selling": False,
            "popularity_only_buying": False,
            "price_coverage": calculate_data_coverage(st.session_state.scored_current,
                                                       st.session_state.scored_candidates).get("price_coverage", 0)}


def _build_rulebook_report() -> dict:
    recommendations = st.session_state.recommendations
    ordered = recommendation_execution_order(recommendations)
    sells = ordered[ordered.get("Action", pd.Series(dtype=str)).astype(str).str.contains("sell|liquidate", case=False, regex=True)] if not ordered.empty else pd.DataFrame()
    buys = ordered[ordered.get("Action", pd.Series(dtype=str)).astype(str).str.contains("buy", case=False)] if not ordered.empty else pd.DataFrame()
    execution = create_execution_order(sells, buys, st.session_state.optimized_savings)
    gaps = generate_data_gap_report(st.session_state.scored_current, st.session_state.scored_candidates,
                                    st.session_state.get("provider_failures", []),
                                    st.session_state.get("symbol_resolution_cache", []))
    watchlist = recommendations[recommendations.get("Action", pd.Series(dtype=str)).astype(str).str.contains(
        "watchlist|no trade", case=False, regex=True)] if not recommendations.empty else pd.DataFrame()
    context = _rulebook_context()
    report = build_structured_rebalance_report(
        strategy=st.session_state.strategy, theme_ranking=_theme_ranking(),
        target_review=st.session_state.drift, gap_analysis=gaps,
        recommendations=recommendations, execution_order=execution,
        savings_plans=st.session_state.optimized_savings,
        allocation=st.session_state.drift, watchlist=watchlist,
        market_reasoning=st.session_state.get("market_reasoning_notes") or st.session_state.strategy.get("reasoning", ""),
        context=context)
    st.session_state.rulebook_report = report
    st.session_state.rulebook_guardrails = validate_rebalance_guardrails(context)
    return report


def rebalance_section():
    render_flash_message()
    render_page_header("Rebalance", "One evidence-led superflow for prices, metadata, news, strategy, allocation, savings plans, and execution planning.",
                       "Decision support only")
    render_hero_summary("Full portfolio review", "Run Full Rebalance", "One guided workflow",
                        "Refreshes market evidence and produces a manual Scalable execution checklist. It never places an order.")
    render_alert("No broker connection, orders, or automatic savings-plan updates. Check the live Scalable price before every execution.", "warning")
    coverage = calculate_data_coverage(st.session_state.scored_current, st.session_state.scored_candidates,
                                       st.session_state.news_items)
    gaps = generate_data_gap_report(st.session_state.scored_current, st.session_state.scored_candidates,
                                    st.session_state.get("provider_failures", []),
                                    st.session_state.get("symbol_resolution_cache", []))
    if not gaps.empty:
        render_alert(f"Recommendation quality reduced because {len(gaps)} fields or provider checks are unresolved.", "warning")
    if coverage["price_coverage"] < 90:
        render_alert(f"Price coverage is {coverage['price_coverage']:.1f}% (below the 90% caution threshold).", "warning")
    if coverage["metadata_coverage"] < 75:
        render_alert(f"Metadata coverage is {coverage['metadata_coverage']:.1f}% (below the 75% caution threshold).", "warning")
    if coverage["ter_coverage"] < 75:
        render_alert("ETF cost coverage is below 75%; incomplete ETF candidates are blocked from buy/add.", "danger")
    st.session_state.market_reasoning_notes = st.text_area(
        "Short market reasoning notes",
        value=st.session_state.get("market_reasoning_notes", ""),
        placeholder="Add your own interpretation, constraints, tax notes, or reasons to defer execution.")
    flow_labels = list(PIPELINE_LABELS)
    flow_state = st.session_state.get("rebalance_flow_status", ["Pending"] * len(flow_labels))
    flow_slot = st.empty()
    def draw_flow():
        flow_slot.empty()
        with flow_slot.container():
            render_flow_steps([{"label": label, "status": flow_state[index]} for index, label in enumerate(flow_labels)])
    draw_flow()
    if st.button("Run Full Rebalance", type="primary", use_container_width=True):
        flow_state = ["Pending"] * len(flow_labels); st.session_state.rebalance_flow_status = flow_state
        progress = st.progress(0, "Starting Market Data Engine...")
        flow_map = {name: index for index, name in enumerate([
            "refresh_prices", "enrich_missing_data", "read_news", "fresh_market_research",
            "calculate_sentiment", "refresh_strategy", "theme_ranking", "target_allocation_review",
            "portfolio_gap_analysis", "buy_sell_plan", "savings_plan_changes", "execution_order"])}
        def progress_step(name, fraction, function):
            def wrapped(results):
                flow_state[flow_map[name]] = "Running"; draw_flow()
                progress.progress(fraction, name.replace("_", " ").title())
                try:
                    result = function(results); flow_state[flow_map[name]] = "Done"; draw_flow(); return result
                except Exception:
                    flow_state[flow_map[name]] = "Failed"; draw_flow(); raise
            return wrapped
        def enrich_missing(_):
            symbols = _repair_symbols_on_demand()
            metadata = _run_deep_scan_chunk(5)
            return {"symbols": symbols, "metadata": metadata}
        steps = {
            "refresh_prices": progress_step("refresh_prices", 1 / 12, lambda _: refresh_live_data(True)),
            "enrich_missing_data": progress_step("enrich_missing_data", 2 / 12, enrich_missing),
            "read_news": progress_step("read_news", 3 / 12, lambda _: _refresh_news_and_strategy(False)),
            "fresh_market_research": progress_step("fresh_market_research", 4 / 12, lambda _: recompute_models()),
            "calculate_sentiment": progress_step("calculate_sentiment", 5 / 12, lambda _: st.session_state.sentiment),
            "refresh_strategy": progress_step("refresh_strategy", 6 / 12, lambda _: _refresh_news_and_strategy(True)),
            "theme_ranking": progress_step("theme_ranking", 7 / 12, lambda _: _theme_ranking().to_dict("records")),
            "target_allocation_review": progress_step("target_allocation_review", 8 / 12, lambda _: st.session_state.targets),
            "portfolio_gap_analysis": progress_step("portfolio_gap_analysis", 9 / 12, lambda _: st.session_state.drift.to_dict("records")),
            "buy_sell_plan": progress_step("buy_sell_plan", 10 / 12, lambda _: (recompute_models(), st.session_state.recommendations.to_dict("records"))[1]),
            "savings_plan_changes": progress_step("savings_plan_changes", 11 / 12, lambda _: st.session_state.optimized_savings.to_dict("records")),
            "execution_order": progress_step("execution_order", 1.0, lambda _: _build_rulebook_report()["Execution order"].to_dict("records")),
            "save_run": lambda results: _save_master_run(results),
        }
        run = run_full_rebalance_pipeline(steps)
        st.session_state.last_rebalance_run = run
        st.session_state.rebalance_flow_status = flow_state
        progress.empty()
        if run["warnings"]: render_alert(run["run_status"] + ": " + "; ".join(run["warnings"]), "warning")
        else: safe_toast("Full rebalance completed", "✅")
    report = _build_rulebook_report()
    render_section_card("1. Market and strategy refresh")
    render_strategy_summary_card(report["Market and strategy refresh"])
    render_alert(st.session_state.sentiment.get("explanation", "Sentiment evidence remains incomplete."), "info")

    render_section_card("2. Theme / sector ranking")
    safe_dataframe(report["Theme / sector ranking"], width="stretch", hide_index=True)

    render_section_card("3. Target allocation review")
    safe_dataframe(report["Target allocation review"], width="stretch", hide_index=True)

    render_section_card("4. Portfolio gap analysis")
    if report["Portfolio gap analysis"].empty:
        render_empty_state("No unresolved gaps", "Current cached records satisfy the gap checks.")
    else:
        safe_dataframe(report["Portfolio gap analysis"], width="stretch", hide_index=True)

    render_section_card("5. Immediate buy/sell table")
    safe_dataframe(report["Immediate buy/sell table"], width="stretch", hide_index=True)

    render_section_card("6. Execution order", "Sells fund buys first; savings-plan changes remain manual.")
    if report["Execution order"].empty:
        render_empty_state("No execution steps", "No fee-efficient immediate trade is justified.")
    else:
        safe_dataframe(report["Execution order"], width="stretch", hide_index=True)
    manual_checklist = create_savings_plan_execution_checklist(st.session_state.plans, st.session_state.optimized_savings)
    with st.expander("Manual Scalable execution checklist"):
        if manual_checklist.empty: render_empty_state("No savings-plan changes", "No manual plan update is currently required.")
        else: safe_dataframe(manual_checklist, width="stretch", hide_index=True)

    render_section_card("7. Savings-plan adjustment table")
    safe_dataframe(report["Savings-plan adjustment table"], width="stretch", hide_index=True)
    with st.expander("Edit and approve savings-plan records"):
        savings_plan_page()

    render_section_card("8. Allocation table")
    safe_dataframe(report["Allocation table"], width="stretch", hide_index=True)

    render_section_card("9. Themes considered but rejected / watchlisted")
    watchlist = report["Themes considered but rejected / watchlisted"]
    if isinstance(watchlist, pd.DataFrame) and not watchlist.empty:
        safe_dataframe(watchlist, width="stretch", hide_index=True)
    else:
        render_empty_state("No explicit watchlist rows", "The rulebook theme universe was reviewed; no additional asset passed watchlist gates.")

    render_section_card("10. Short market reasoning")
    render_alert(str(report["Short market reasoning"] or "Evidence is incomplete; do not force a trade."), "info")

    render_section_card("11. Skip conditions / when not to execute")
    for condition in report["Skip conditions / when not to execute"]:
        st.markdown(f"- {condition}")
    guardrails = st.session_state.rulebook_guardrails
    failed_checks = [item for item in guardrails["checks"] if not item["passed"]]
    render_alert("All rulebook guardrails passed." if not failed_checks else
                 f"{len(failed_checks)} guardrail checks remain incomplete; treat recommendations as estimated.",
                 "success" if not failed_checks else "warning")
    with st.expander("Guardrail checklist"):
        safe_dataframe(pd.DataFrame(guardrails["checks"]), width="stretch", hide_index=True)
    with st.expander("Recommendation report and source detail", expanded=False): recommendation_report_page()


def _save_master_run(results):
    valuation_snapshot = _save_current_valuation_snapshot()
    _build_rulebook_report()
    database.save_strategy_snapshot(st.session_state.strategy)
    database.save_recommendations(st.session_state.recommendation_report)
    guardrails = st.session_state.rulebook_guardrails
    failed_guardrails = [item["check_name"] for item in guardrails["checks"] if not item["passed"]]
    payload = {"run_status": "Completed", "strategy_snapshot": st.session_state.strategy,
               "valuation_snapshot": valuation_snapshot,
               "recommendations": st.session_state.recommendation_report.to_dict("records"),
               "savings_plan_changes": st.session_state.optimized_savings.to_dict("records"),
               "news_inputs": st.session_state.news_items, "sentiment_summary": st.session_state.sentiment,
               "warnings": st.session_state.enrichment_warnings +
                           (["Incomplete rulebook guardrails: " + ", ".join(failed_guardrails)] if failed_guardrails else []) +
                           (["User market notes: " + st.session_state.market_reasoning_notes]
                            if st.session_state.get("market_reasoning_notes") else [])}
    saved_run = database.save_rebalance_run(payload)
    run_id = saved_run.get("id") if isinstance(saved_run, dict) else None
    try:
        database.save_guardrail_checks(guardrails["checks"], run_id)
        database.save_rulebook_version(CURRENT_RULEBOOK.version, CURRENT_RULEBOOK.as_dict(),
                                       {"holdings": get_confirmed_baseline_holdings().to_dict("records"),
                                        "savings_plans": get_confirmed_savings_plan().to_dict("records")})
    except (AttributeError, SupabaseConnectionError) as exc:
        st.session_state.enrichment_warnings.append(f"Rulebook audit was not saved: {exc}")
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
    optional = ["ALPHA_VANTAGE_API_KEY", "OPENFIGI_API_KEY", "COINGECKO_API_KEY",
                "FMP_API_KEY", "TWELVE_DATA_API_KEY"]
    with st.expander("Secrets status"):
        safe_dataframe(pd.DataFrame(
            [{"Secret": name, "Required": "Yes", "Status": secret_status(name)} for name in required] +
            [{"Secret": name, "Required": "No", "Status": secret_status(name)} for name in optional]),
            width="stretch", hide_index=True)
    render_section_card("Data providers", "Alpha Vantage is used when configured; existing free fallbacks remain available.")
    provider_rows = get_provider_registry()
    safe_dataframe(pd.DataFrame(provider_rows), width="stretch", hide_index=True)

    render_section_card("Rebalancer Rulebook", "The versioned policy controlling baseline, guardrails, workflow, execution, and report format.")
    rulebook_cols = st.columns(3)
    with rulebook_cols[0]: render_metric_card("Version", CURRENT_RULEBOOK.version)
    with rulebook_cols[1]: render_metric_card("Baseline date", CONFIRMED_BASELINE_DATE)
    with rulebook_cols[2]: render_metric_card("Baseline source", CONFIRMED_BASELINE_SOURCE)
    with st.expander("Base targets and broker rules"):
        safe_dataframe(pd.DataFrame([{"Category": key, "Target %": value}
                                     for key, value in get_base_target_allocation().items()]),
                       width="stretch", hide_index=True)
        st.markdown("**Broker rules**")
        for key, value in BROKER_RULES.items(): st.markdown(f"- {key.replace('_', ' ').title()}: {value}")
    with st.expander("Direct-trade and savings-plan rules"):
        for key, value in DIRECT_TRADE_RULES.items(): st.markdown(f"- {key.replace('_', ' ').title()}: {value}")
        st.markdown("**Savings plans**")
        for key, value in SAVINGS_PLAN_RULES.items(): st.markdown(f"- {key.replace('_', ' ').title()}: {value}")
    with st.expander("Required workflow and guardrail checklist"):
        for index, label in enumerate(REBALANCE_WORKFLOW, 1): st.markdown(f"{index}. {label}")
        checklist = create_rebalance_checklist(_rulebook_context())
        safe_dataframe(pd.DataFrame(checklist["guardrails"]["checks"]), width="stretch", hide_index=True)
    reset_col, plan_col = st.columns(2)
    confirm_baseline = reset_col.checkbox("Confirm overwrite current app holdings", key="confirm_rulebook_baseline")
    if reset_col.button("Reset app portfolio to confirmed rulebook baseline", disabled=not confirm_baseline,
                        use_container_width=True):
        st.session_state.holdings = holdings_to_dataframe(get_confirmed_baseline_holdings().to_dict("records"))
        st.session_state.targets = get_base_target_allocation()
        database.save_holdings(st.session_state.holdings)
        database.save_settings({"target_allocations": st.session_state.targets})
        recompute_models(); set_flash_success("Confirmed rulebook baseline loaded"); st.rerun()
    confirm_plans = plan_col.checkbox("Confirm overwrite current app savings plans", key="confirm_rulebook_plans")
    if plan_col.button("Load rulebook savings plan", disabled=not confirm_plans, use_container_width=True):
        st.session_state.plans = _plans_with_categories(get_confirmed_savings_plan())
        database.save_savings_plans(st.session_state.plans)
        recompute_models(); set_flash_success("Rulebook savings plan loaded"); st.rerun()

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
    s["direct_trade_minimum"] = c.number_input("Direct trade minimum EUR", min_value=0.0,
                                                  value=float(DIRECT_TRADE_RULES["minimum_efficient_trade_eur"]), disabled=True)
    s["small_trade_round_trip_fee"] = a.number_input("Below-threshold assumed trading fee EUR", min_value=0.0,
                                                        value=float(DIRECT_TRADE_RULES["below_threshold_fee_eur"]), disabled=True)
    intervals = [60, 300, 600, 900]
    current_interval = int(s.get("refresh_interval", 300))
    interval_index = intervals.index(current_interval) if current_interval in intervals else 1
    s["refresh_interval"] = b.selectbox("Data refresh interval", intervals, index=interval_index,
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
    render_section_card("Scalable assumptions", "PRIME+ · Preferred venue EIX/gettex · Avoid Xetra unless needed · €250 direct-trade threshold · €0.99 assumed below-threshold trading fee · Whole units for all direct orders · Fractional buying only through savings plans.")
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


PAGES = ["Portfolio", "Market", "Strategy", "Rebalance", "Settings"]


def main() -> None:
    """Authenticate, load cached state, and render the selected page."""
    global database
    user_id = require_authentication()
    if not user_id:
        st.stop()
    try:
        gateway = SupabaseGateway(get_supabase_client(user_id))
        database = Database(gateway, user_id)
        initialise_state(database)
    except SupabaseConnectionError as exc:
        render_alert(str(exc), "danger")
        render_alert(
            "Add SUPABASE_URL and SUPABASE_ANON_KEY to Streamlit secrets, then run supabase_schema.sql.",
            "info",
        )
        st.stop()

    with st.sidebar:
        st.markdown('<div class="sidebar-brand"><div class="sidebar-title">Financial Hub</div>'
                    '<div class="sidebar-subtitle">Wealth command center</div></div>', unsafe_allow_html=True)
        page = st.radio("Navigation", PAGES)
        market_status = (
            "Error" if st.session_state.enrichment_warnings
            else "Live" if st.session_state.settings.get("live_enabled", True)
            else "Disabled"
        )
        market_class = (
            "danger-pill" if market_status == "Error"
            else "warning-pill" if market_status == "Disabled"
            else "info-pill"
        )
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
    st.markdown(
        '<div class="privacy-footer">Private app · Data saved in Supabase · No broker connection · No auto-trading</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
