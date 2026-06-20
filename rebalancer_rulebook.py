"""Versioned, structured policy for every Financial Hub rebalance decision."""

from __future__ import annotations

from dataclasses import asdict, dataclass


RULEBOOK_VERSION = "2026.06-rulebook-1"
CONFIRMED_BASELINE_DATE = "Date not supplied"
CONFIRMED_BASELINE_SOURCE = "User-confirmed Rebalancer Rulebook"

INVESTOR_PROFILE = {
    "country": "Germany",
    "broker": "Scalable Capital",
    "horizon_years": "10+",
    "risk_profile": "Aggressive / high risk tolerance",
    "target_cagr_ambition_pct": 15.0,
    "accepts_volatility_and_drawdowns": True,
    "candidate_universe_not_limited_to_current_holdings": True,
}

BROKER_RULES = {
    "broker": "Scalable Capital", "membership": "PRIME+",
    "preferred_venue": "EIX/gettex", "avoid_venue": "Xetra unless explicitly needed",
    "execution_price_truth": "Scalable live buy/sell prices",
    "public_price_role": "Estimated valuation and research only",
}

DIRECT_TRADE_RULES = {
    "whole_quantities_only": True, "fractional_direct_buying": False,
    "fractional_direct_selling": False, "fractional_liquidation_instruction": "Liquidate full position",
    "minimum_efficient_trade_eur": 250.0, "below_threshold_fee_eur": 0.99,
    "buys_require_cash": True, "sells_fund_buys_first": True,
    "force_trade_because_cash_exists": False, "sell_only_because_red": False,
    "buy_only_because_popular": False,
}

SAVINGS_PLAN_RULES = {
    "monthly_budget_eur": 300.0, "execution_day": 1, "fractional_buying_allowed": True,
    "preferred_uses": ["Gradual allocation", "Inefficient small trades", "Volatile markets",
                       "Underweight long-term themes"],
}

BASE_TARGET_ALLOCATION = {
    "Core": 25.0, "EM": 15.0, "Growth": 40.0, "Defence": 5.0,
    "Commodities": 10.0, "Crypto": 5.0, "Cash": 0.0,
}
CASH_TARGET_RANGE = (0.0, 2.0)

COMMODITY_RULES = {"target_pct": 10.0, "gold_range_pct": (7.0, 8.0),
                   "silver_range_pct": (2.0, 3.0), "do_not_exceed_target": True}
CRYPTO_RULES = {"target_pct": 5.0, "cap_pct": 5.0, "build_only_if_trend_strong": True,
                "keep_controlled_in_risk_off": True}

THEMES_REQUIRED_FOR_REVIEW = [
    "AI infrastructure", "Utilities / grid", "Data centers", "Financials", "Healthcare",
    "Defence", "Gold", "Silver", "Crypto", "Emerging markets", "India", "China", "Japan",
    "Energy", "Materials", "Robotics", "Automation", "Cybersecurity",
]
REGIONS_REQUIRED_FOR_REVIEW = ["United States", "Europe", "Emerging markets", "India", "China", "Japan"]

REBALANCE_WORKFLOW = [
    "Refreshing Prices", "Enriching missing data", "Reading News", "Fresh market research",
    "Calculating Sentiments", "Refreshing Strategy", "Theme ranking", "Target allocation review",
    "Portfolio gap analysis", "Buy/sell plan", "Savings-plan changes", "Execution order",
]

REQUIRED_REBALANCE_SECTIONS = [
    "Market and strategy refresh", "Theme / sector ranking", "Target allocation review",
    "Portfolio gap analysis", "Immediate buy/sell table", "Execution order",
    "Savings-plan adjustment table", "Allocation table",
    "Themes considered but rejected / watchlisted", "Short market reasoning",
    "Skip conditions / when not to execute",
]

ALLOWED_TRADE_PURPOSES = ["Core", "Growth", "Trend", "Tactical", "Hedge", "Risk reduction", "Cleanup"]

CONFIRMED_BASELINE_SUMMARY = {
    "cash_eur": 70.46, "invested_value_eur": 2038.83, "total_portfolio_eur": 2109.29,
    "total_buy_in_eur": 1968.51, "unrealized_pl_eur": 70.32, "unrealized_return_pct": 3.57,
}


def _holding(instrument, isin, ticker, asset_type, category, quantity, value, buy_in, pl, pl_pct):
    return {"instrument": instrument, "isin": isin, "ticker_id": ticker, "price_symbol": "",
            "asset_type": asset_type, "category": category, "quantity": quantity,
            "manual_current_price": round(value / quantity, 8) if quantity else value,
            "live_current_price": 0.0, "price_source": "Confirmed rulebook baseline",
            "currency": "EUR", "fx_rate_to_eur": 1.0, "current_value_eur": value,
            "buy_in_value_eur": buy_in, "pl_eur": pl, "pl_pct": pl_pct,
            "direct_trading_allowed": True, "fractional_allowed": False,
            "source": CONFIRMED_BASELINE_SOURCE, "user_confirmed": True,
            "notes": "Confirmed baseline; refresh market data before recommendations."}


CONFIRMED_BASELINE_HOLDINGS = [
    _holding("Scalable MSCI AC World Xtrackers UCITS ETF 1C", "LU2903252349", "ACWI", "ETF", "Core", 61, 721.08, 700.14, 20.94, 2.99),
    _holding("iShares Core MSCI EM IMI UCITS ETF USD Acc", "IE00BKM4GZ66", "EIMI", "ETF", "EM", 9, 447.72, 400.35, 47.37, 11.83),
    _holding("EUWAX Gold II", "DE000EWG2LD7", "EWG2", "ETC", "Commodities", 2, 238.35, 290.36, -52.01, -17.91),
    _holding("Xtrackers Artificial Intelligence & Big Data UCITS ETF 1C", "IE00BGV5VN51", "XAIX", "ETF", "Growth", 1, 215.12, 151.96, 63.16, 41.57),
    _holding("VanEck Semiconductor UCITS ETF", "IE00BMC38736", "SMH", "ETF", "Growth", 2, 215.12, 206.08, 9.04, 4.39),
    _holding("HANetf Future of Defence UCITS ETF", "IE000OJ5TQP4", "NATO", "ETF", "Defence", 8, 141.64, 132.35, 9.29, 7.02),
    _holding("WisdomTree Physical Crypto Mega Cap", "GB00BMTP1626", "WCRP", "ETP", "Crypto", 14, 59.80, 87.27, -27.47, -31.48),
    {"instrument": "Cash", "isin": "CASH", "ticker_id": "CASH", "price_symbol": "",
     "asset_type": "Cash", "category": "Cash", "quantity": 1, "manual_current_price": 70.46,
     "live_current_price": 0.0, "price_source": "Confirmed rulebook baseline", "currency": "EUR",
     "fx_rate_to_eur": 1.0, "current_value_eur": 70.46, "buy_in_value_eur": 0.0,
     "pl_eur": 0.0, "pl_pct": 0.0, "direct_trading_allowed": False,
     "fractional_allowed": False, "source": CONFIRMED_BASELINE_SOURCE, "user_confirmed": True,
     "notes": "Confirmed cash baseline."},
]

CONFIRMED_ALLOCATION = {"Core": 34.2, "EM": 21.2, "Growth": 20.4, "Commodities": 11.3,
                        "Defence": 6.7, "Crypto": 2.8, "Cash": 3.3}

CONFIRMED_SAVINGS_PLAN = [
    {"instrument": "Scalable MSCI AC World Xtrackers UCITS ETF", "isin": "LU2903252349", "category": "Core", "current_plan": 75.0},
    {"instrument": "iShares Core MSCI EM IMI UCITS ETF USD Acc", "isin": "IE00BKM4GZ66", "category": "EM", "current_plan": 45.0},
    {"instrument": "VanEck Semiconductor UCITS ETF", "isin": "IE00BMC38736", "category": "Growth", "current_plan": 45.0},
    {"instrument": "Microsoft Corporation", "isin": "US5949181045", "category": "Growth", "current_plan": 30.0},
    {"instrument": "ASML Holding N.V.", "isin": "NL0010273215", "category": "Growth", "current_plan": 25.0},
    {"instrument": "Xtrackers Artificial Intelligence & Big Data UCITS ETF 1C", "isin": "IE00BGV5VN51", "category": "Growth", "current_plan": 20.0},
    {"instrument": "HANetf Future of Defence UCITS ETF", "isin": "IE000OJ5TQP4", "category": "Defence", "current_plan": 15.0},
    {"instrument": "EUWAX Gold II", "isin": "DE000EWG2LD7", "category": "Commodities", "current_plan": 25.0},
    {"instrument": "iShares Physical Silver ETC", "isin": "IE00B4NCWG09", "category": "Commodities", "current_plan": 5.0},
    {"instrument": "WisdomTree Physical Crypto Mega Cap", "isin": "GB00BMTP1626", "category": "Crypto", "current_plan": 15.0},
]

HISTORICAL_CONTEXT = {
    "older_executed_rebalance_reflected_in_baseline": True,
    "most_recent_proposed_rebalance_implemented": False,
    "assume_later_recommendations_executed": False,
    "review_rule": "Re-evaluate from scratch using fresh data; never blindly repeat an old recommendation.",
}


@dataclass(frozen=True)
class RebalancerRulebook:
    version: str = RULEBOOK_VERSION
    baseline_date: str = CONFIRMED_BASELINE_DATE
    baseline_source: str = CONFIRMED_BASELINE_SOURCE

    def as_dict(self) -> dict:
        base = asdict(self)
        base.update({"investor_profile": INVESTOR_PROFILE, "broker_rules": BROKER_RULES,
                     "direct_trade_rules": DIRECT_TRADE_RULES, "savings_plan_rules": SAVINGS_PLAN_RULES,
                     "base_target_allocation": BASE_TARGET_ALLOCATION, "cash_target_range": CASH_TARGET_RANGE,
                     "commodity_rules": COMMODITY_RULES, "crypto_rules": CRYPTO_RULES,
                     "required_workflow": REBALANCE_WORKFLOW,
                     "required_sections": REQUIRED_REBALANCE_SECTIONS,
                     "themes_required_for_review": THEMES_REQUIRED_FOR_REVIEW,
                     "regions_required_for_review": REGIONS_REQUIRED_FOR_REVIEW,
                     "historical_context": HISTORICAL_CONTEXT})
        return base


CURRENT_RULEBOOK = RebalancerRulebook()
