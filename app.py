"""Local Streamlit interface for valuation and portfolio rebalancing support."""

from datetime import datetime
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from insights import generate_insights
from market_data import fetch_fx_rate_to_eur, fetch_market_quote
from rebalancer import (allocation_table, calculate_allocation, calculate_drift,
    calculate_total_invested, calculate_total_value, calculate_unrealised_pl, execution_order,
    generate_rebalance_trades, holdings_to_dataframe, recommend_savings_plans, savings_plans_to_dataframe)
from sample_data import SAMPLE_HOLDINGS, SAMPLE_SAVINGS_PLANS, TARGET_ALLOCATIONS
from storage import (clear_valuation_history, load_portfolio, load_valuation_history, save_portfolio,
                     save_uploaded_file, save_valuation_snapshot)
from valuation import calculate_historical_gains, portfolio_market_history, valuate_holdings

st.set_page_config(page_title="Scalable Wealth Rebalancer", page_icon="⚖️", layout="wide")

DISPLAY_COLUMNS = {"instrument": "Instrument", "isin": "ISIN", "ticker_id": "Ticker/ID",
    "price_symbol": "Price Symbol", "asset_type": "Asset type", "category": "Category",
    "quantity": "Quantity", "manual_current_price": "Manual current price",
    "live_current_price": "Live current price", "price_source": "Price source", "currency": "Currency",
    "fx_rate_to_eur": "FX rate to EUR", "current_value_eur": "Current value EUR",
    "buy_in_value_eur": "Buy-in value EUR", "pl_eur": "P/L EUR", "pl_pct": "P/L %",
    "direct_trading_allowed": "Direct trading allowed", "fractional_allowed": "Fractional allowed", "notes": "Notes"}
READ_ONLY_COLUMNS = ["Live current price", "Price source", "Current value EUR", "P/L EUR", "P/L %"]


@st.cache_data(ttl=3600, show_spinner=False)
def cached_market_quote(symbol: str, refresh_bucket: int):
    return fetch_market_quote(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fx_rate(currency: str, refresh_bucket: int):
    return fetch_fx_rate_to_eur(currency)


def initialise_state():
    if "holdings" not in st.session_state:
        st.session_state.holdings = load_portfolio(fallback=SAMPLE_HOLDINGS)
    if "targets" not in st.session_state:
        st.session_state.targets = TARGET_ALLOCATIONS.copy()
    if "plans" not in st.session_state:
        st.session_state.plans = savings_plans_to_dataframe(SAMPLE_SAVINGS_PLANS)
    if "settings" not in st.session_state:
        st.session_state.settings = {"base_currency": "EUR", "refresh_interval": 300,
                                     "live_enabled": True, "fee_threshold": 250.0,
                                     "cash_min_pct": 0.0, "cash_max_pct": 2.0}
    if "quotes" not in st.session_state:
        st.session_state.quotes = {}
    if "fx_rates" not in st.session_state:
        st.session_state.fx_rates = {"EUR": 1.0}
    if "last_price_fetch" not in st.session_state:
        st.session_state.last_price_fetch = None
    refresh_valuation_details()


def refresh_valuation_details():
    st.session_state.valuation_details = valuate_holdings(
        st.session_state.holdings, st.session_state.quotes, st.session_state.fx_rates)
    st.session_state.holdings = holdings_to_dataframe(st.session_state.valuation_details.to_dict("records"))


def refresh_live_prices(force: bool = False):
    if not st.session_state.settings["live_enabled"]:
        st.warning("Live price fetching is disabled in Settings.")
        refresh_valuation_details()
        return
    if force:
        cached_market_quote.clear()
        cached_fx_rate.clear()
    interval = max(int(st.session_state.settings["refresh_interval"]), 30)
    bucket = int(time.time() // interval)
    symbols = sorted({str(value).strip() for value in st.session_state.holdings["price_symbol"] if str(value).strip()})
    quotes = {symbol: cached_market_quote(symbol, bucket) for symbol in symbols}
    currencies = {quote.currency for quote in quotes.values() if quote.currency}
    fx_rates, fx_errors = {"EUR": 1.0}, {}
    for currency in currencies - {"EUR"}:
        rate, error = cached_fx_rate(currency, bucket)
        if rate:
            fx_rates[currency] = rate
        else:
            fx_errors[currency] = error
    st.session_state.quotes, st.session_state.fx_rates = quotes, fx_rates
    successful = [quote.fetched_at for quote in quotes.values() if quote.is_available and quote.fetched_at]
    if successful:
        st.session_state.last_price_fetch = max(successful)
    refresh_valuation_details()
    failures = [symbol for symbol, quote in quotes.items() if not quote.is_available]
    if failures:
        st.warning("Live price unavailable, using manual price. Affected symbols: " + ", ".join(failures))
    if fx_errors:
        st.warning("FX rate unavailable; stored manual FX rate retained for: " + ", ".join(fx_errors))


def dashboard():
    st.header("Dashboard")
    holdings = st.session_state.holdings
    total, invested, profit = calculate_total_value(holdings), calculate_total_invested(holdings), calculate_unrealised_pl(holdings)
    cash = float(holdings.loc[holdings["category"] == "Cash", "current_value_eur"].sum())
    columns = st.columns(4)
    for column, label, value in zip(columns, ["Portfolio value", "Total buy-in", "Unrealised P/L", "Cash balance"], [total, invested, profit, cash]):
        column.metric(label, f"€{value:,.2f}")
    allocation, drift = calculate_allocation(holdings), calculate_drift(holdings, st.session_state.targets)
    left, right = st.columns(2)
    with left:
        st.subheader("Allocation by category")
        st.bar_chart(allocation.set_index("category")["current_weight"])
        st.dataframe(allocation, width="stretch", hide_index=True)
    with right:
        st.subheader("Current versus target")
        st.dataframe(allocation_table(drift), width="stretch", hide_index=True)


def _gain_metric(column, label: str, gain):
    if gain is None:
        column.metric(label, "Not enough history yet")
    else:
        column.metric(label, f"€{gain['eur']:+,.2f}", f"{gain['pct']:+.2f}%")


def valuation_dashboard():
    st.header("Valuation Dashboard")
    st.warning("Internet prices are estimates and may be delayed. Scalable Capital's live buy/sell prices are final for order execution. This app never places orders.")
    action_a, action_b, action_c = st.columns([1, 1, 2])
    if action_a.button("Refresh live prices", type="primary"):
        with st.spinner("Fetching estimated internet prices..."):
            refresh_live_prices(force=True)
    history = load_valuation_history()
    details = st.session_state.valuation_details
    total = calculate_total_value(details)
    invested = calculate_total_invested(details)
    profit = calculate_unrealised_pl(details)
    profit_pct = profit / invested * 100 if invested else 0.0
    cash = float(details.loc[details["category"] == "Cash", "current_value_eur"].sum())
    gains = calculate_historical_gains(total, history)
    if action_b.button("Save today's valuation snapshot"):
        now = datetime.now().astimezone()
        snapshot = {"date": now.date().isoformat(), "timestamp": now.isoformat(timespec="seconds"),
                    "total_value_eur": total, "cash_eur": cash, "invested_value_eur": invested,
                    "unrealized_pl_eur": profit,
                    "daily_gain_eur": gains["daily"]["eur"] if gains["daily"] else 0.0,
                    "weekly_gain_eur": gains["weekly"]["eur"] if gains["weekly"] else 0.0,
                    "monthly_gain_eur": gains["monthly"]["eur"] if gains["monthly"] else 0.0,
                    "yearly_gain_eur": gains["yearly"]["eur"] if gains["yearly"] else 0.0}
        save_valuation_snapshot(snapshot)
        st.success("Today's valuation snapshot was saved locally.")
        history = load_valuation_history()
    last_fetch = st.session_state.last_price_fetch or "No successful live fetch yet"
    action_c.caption(f"Last successful price fetch: {last_fetch}")

    first = st.columns(4)
    first[0].metric("Live portfolio value EUR", f"€{total:,.2f}")
    _gain_metric(first[1], "Daily gain", gains["daily"])
    _gain_metric(first[2], "Weekly gain", gains["weekly"])
    _gain_metric(first[3], "Monthly gain", gains["monthly"])
    second = st.columns(3)
    _gain_metric(second[0], "Yearly gain", gains["yearly"])
    second[1].metric("Total unrealised P/L", f"€{profit:+,.2f}", f"{profit_pct:+.2f}%")
    second[2].metric("Cash balance", f"€{cash:,.2f}")

    fallback_symbols = details[(details["price_source"] == "Manual fallback") & (details["price_symbol"].str.strip() != "")]
    if not fallback_symbols.empty:
        st.warning("Live price unavailable, using manual price. " + ", ".join(fallback_symbols["instrument"]))

    market_history = portfolio_market_history(details, st.session_state.quotes)
    if market_history.empty and not history.empty:
        market_history = history.rename(columns={"timestamp": "date", "total_value_eur": "portfolio_value_eur"})
        market_history["daily_gain_eur"] = market_history["portfolio_value_eur"].diff().fillna(0)
    chart_a, chart_b = st.columns(2)
    with chart_a:
        st.plotly_chart(px.line(market_history, x="date", y="portfolio_value_eur", title="Portfolio value over time"), width="stretch")
    with chart_b:
        st.plotly_chart(px.bar(market_history, x="date", y="daily_gain_eur", title="Daily gain/loss",
                               color="daily_gain_eur", color_continuous_scale=["#b91c1c", "#e5e7eb", "#15803d"]), width="stretch")
    allocation = details.groupby("category", as_index=False)["current_value_eur"].sum()
    chart_c, chart_d = st.columns(2)
    with chart_c:
        st.plotly_chart(px.pie(allocation, names="category", values="current_value_eur", hole=.45,
                               title="Allocation by category"), width="stretch")
    with chart_d:
        holdings_chart = details.sort_values("current_value_eur")
        st.plotly_chart(px.bar(holdings_chart, x="current_value_eur", y="instrument", orientation="h",
                               title="Holdings value"), width="stretch")
    winners = details.sort_values("daily_gain_eur")
    st.plotly_chart(px.bar(winners, x="instrument", y="daily_gain_eur", color="daily_gain_eur",
                           title="Daily winners and losers", color_continuous_scale=["#b91c1c", "#e5e7eb", "#15803d"]), width="stretch")

    st.subheader("Portfolio insights")
    drift = calculate_drift(details, st.session_state.targets)
    for insight in generate_insights(details, drift, st.session_state.settings["fee_threshold"], st.session_state.settings["cash_max_pct"]):
        st.write("• " + insight)
    st.subheader("Valuation history")
    st.dataframe(history, width="stretch", hide_index=True)
    export_col, clear_col = st.columns(2)
    export_col.download_button("Export valuation history CSV", history.to_csv(index=False), "valuation_history.csv", "text/csv")
    confirm = clear_col.checkbox("Confirm clear valuation history")
    if clear_col.button("Clear valuation history", disabled=not confirm):
        clear_valuation_history()
        st.success("Local valuation history cleared.")
        st.rerun()


def upload_page():
    st.header("Upload Holdings Screenshots")
    st.success("Privacy: screenshots stay on this computer in data/uploads/. No OCR, cloud upload, or broker connection is used.")
    uploads = st.file_uploader("Choose one or more screenshots", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
    for index, uploaded in enumerate(uploads):
        path = save_uploaded_file(uploaded.name, uploaded.getvalue())
        st.image(uploaded, caption=f"Saved locally: {path}", width=420)
        with st.expander(f"Manually confirm holding from {uploaded.name}", expanded=True):
            with st.form(f"screenshot_{index}_{uploaded.name}"):
                a, b, c = st.columns(3)
                instrument, isin, ticker = a.text_input("Instrument name"), b.text_input("ISIN"), c.text_input("Ticker/ID")
                price_symbol = a.text_input("Yahoo Finance Price Symbol")
                asset_type = b.selectbox("Asset type", ["ETF", "Stock", "ETC", "ETP", "Crypto", "Cash", "Other"])
                category = c.selectbox("Category", list(st.session_state.targets))
                quantity = a.number_input("Quantity", min_value=0.0, format="%.6f")
                manual_price = b.number_input("Manual current price", min_value=0.0)
                currency = c.text_input("Currency", value="EUR").upper()
                fx_rate = a.number_input("FX rate to EUR", min_value=0.0, value=1.0, format="%.6f")
                buy_in = b.number_input("Buy-in value EUR", min_value=0.0)
                notes = c.text_input("Notes")
                if st.form_submit_button("Add confirmed holding", type="primary"):
                    row = {"instrument": instrument, "isin": isin, "ticker_id": ticker, "price_symbol": price_symbol,
                           "asset_type": asset_type, "category": category, "quantity": quantity,
                           "manual_current_price": manual_price, "currency": currency, "fx_rate_to_eur": fx_rate,
                           "current_value_eur": quantity * manual_price * fx_rate, "buy_in_value_eur": buy_in,
                           "direct_trading_allowed": asset_type != "Cash", "fractional_allowed": asset_type == "Crypto", "notes": notes}
                    st.session_state.holdings = pd.concat([st.session_state.holdings, holdings_to_dataframe([row])], ignore_index=True)
                    refresh_valuation_details()
                    st.success("Added to the working table. Use Save portfolio to persist it.")


def holdings_page():
    st.header("Manual Holdings Table")
    display = st.session_state.holdings.rename(columns=DISPLAY_COLUMNS)
    edited = st.data_editor(display, num_rows="dynamic", width="stretch", hide_index=True, disabled=READ_ONLY_COLUMNS,
                            column_config={"Asset type": st.column_config.SelectboxColumn(options=["ETF", "Stock", "ETC", "ETP", "Crypto", "Cash", "Other"]),
                                           "Category": st.column_config.SelectboxColumn(options=list(st.session_state.targets))}, key="holdings_editor")
    st.session_state.holdings = holdings_to_dataframe(edited.rename(columns={v: k for k, v in DISPLAY_COLUMNS.items()}).to_dict("records"))
    refresh_valuation_details()
    a, b, c = st.columns(3)
    if a.button("Save portfolio", type="primary"):
        save_portfolio(st.session_state.holdings)
        st.success("Portfolio saved locally to data/portfolio_data.json.")
    if b.button("Reset to sample data"):
        st.session_state.holdings = holdings_to_dataframe(SAMPLE_HOLDINGS)
        st.session_state.quotes, st.session_state.fx_rates = {}, {"EUR": 1.0}
        st.rerun()
    c.download_button("Export holdings CSV", st.session_state.holdings.rename(columns=DISPLAY_COLUMNS).to_csv(index=False), "holdings.csv", "text/csv")


def rebalance_page():
    st.header("Rebalance Report")
    st.info("Decision support only. No orders are placed. Prefer EIX/gettex; avoid Xetra unless explicitly needed. Scalable Capital prices are final for execution.")
    notes = st.text_area("Short market reasoning notes", placeholder="Write your own market context here...")
    drift = calculate_drift(st.session_state.holdings, st.session_state.targets)
    trades = generate_rebalance_trades(st.session_state.holdings, drift, st.session_state.settings["fee_threshold"])
    order, savings, allocation = execution_order(trades), recommend_savings_plans(st.session_state.plans, drift), allocation_table(drift)
    for heading, frame in [("A. Immediate buy/sell table", trades), ("B. Execution order", order),
                           ("C. Savings-plan adjustments", savings), ("D. Allocation table", allocation)]:
        st.subheader(heading)
        st.dataframe(frame, width="stretch", hide_index=True)
    if notes:
        st.subheader("Market reasoning notes")
        st.write(notes)
    for label, frame, filename in [("Trades CSV", trades, "rebalance_trades.csv"), ("Execution CSV", order, "execution_order.csv"),
                                    ("Savings CSV", savings, "savings_adjustments.csv"), ("Allocation CSV", allocation, "allocation.csv")]:
        st.download_button(label, frame.to_csv(index=False), filename, "text/csv")


def savings_page():
    st.header("Savings Plans")
    st.session_state.plans = st.data_editor(st.session_state.plans, num_rows="dynamic", width="stretch", hide_index=True)
    drift = calculate_drift(st.session_state.holdings, st.session_state.targets)
    st.subheader("Suggested adjustments")
    st.dataframe(recommend_savings_plans(st.session_state.plans, drift), width="stretch", hide_index=True)


def settings_page():
    st.header("Settings")
    settings = st.session_state.settings
    a, b = st.columns(2)
    settings["base_currency"] = a.selectbox("Base currency", ["EUR"], index=0)
    settings["refresh_interval"] = b.selectbox("Default live price refresh interval", [60, 300, 600, 900],
                                              index=[60, 300, 600, 900].index(settings["refresh_interval"]), format_func=lambda x: f"{x // 60} minute(s)")
    settings["live_enabled"] = a.toggle("Enable live price fetching", value=settings["live_enabled"])
    settings["fee_threshold"] = b.number_input("Fee-efficient direct-order threshold EUR", min_value=0.0, value=float(settings["fee_threshold"]))
    settings["cash_min_pct"] = a.number_input("Cash target minimum %", min_value=0.0, value=float(settings["cash_min_pct"]))
    settings["cash_max_pct"] = b.number_input("Cash target maximum %", min_value=0.0, value=float(settings["cash_max_pct"]))
    st.session_state.settings = settings
    st.subheader("Target allocations")
    target_df = pd.DataFrame([{"Category": k, "Target weight %": v} for k, v in st.session_state.targets.items()])
    edited = st.data_editor(target_df, num_rows="dynamic", width="stretch", hide_index=True)
    if st.button("Apply settings", type="primary"):
        st.session_state.targets = dict(zip(edited["Category"], edited["Target weight %"]))
        total = sum(st.session_state.targets.values())
        (st.success if abs(total - 100) < 0.01 else st.warning)(f"Targets total {total:.2f}%.")
    st.markdown("**Trading assumptions:** Germany · Scalable Capital PRIME+ · EIX/gettex preferred · whole units for stocks/ETFs/ETCs/ETPs · fractional crypto · no automatic trading.")


initialise_state()
with st.sidebar:
    st.title("Wealth Rebalancer")
    pages = ["Dashboard", "Valuation Dashboard", "Upload Holdings Screenshots", "Manual Holdings Table", "Rebalance Report", "Savings Plans", "Settings"]
    page = st.radio("Navigation", pages)
    st.warning("Local decision support only — never auto-trades or connects to Scalable Capital.")

{"Dashboard": dashboard, "Valuation Dashboard": valuation_dashboard, "Upload Holdings Screenshots": upload_page,
 "Manual Holdings Table": holdings_page, "Rebalance Report": rebalance_page,
 "Savings Plans": savings_page, "Settings": settings_page}[page]()
