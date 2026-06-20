"""Non-personal sample data. Market and fund facts require user verification."""

from copy import deepcopy

from rebalancer_rulebook import (BASE_TARGET_ALLOCATION, CONFIRMED_BASELINE_HOLDINGS,
                                 CONFIRMED_SAVINGS_PLAN)

SUPPORTED_CATEGORIES = ["Core", "EM", "India", "Growth", "AI", "Semiconductors", "Quality tech",
    "Defence", "Cybersecurity", "Healthcare innovation", "Robotics", "Energy", "Uranium",
    "Power grid/electrification", "Commodities", "Gold", "Silver", "Crypto", "Cash", "Other tactical"]

TARGET_ALLOCATIONS = dict(BASE_TARGET_ALLOCATION)

CANDIDATE_COLUMNS = ["instrument", "isin", "wkn", "ticker_id", "price_symbol", "resolved_price_symbol",
    "alpha_vantage_symbol", "alpha_vantage_last_price", "alpha_vantage_previous_close",
    "alpha_vantage_currency", "alpha_vantage_last_updated", "alpha_vantage_confidence",
    "exchange", "asset_type", "category",
    "theme", "region", "currency", "ter_pct", "fund_size_eur", "replication_method",
    "distribution_policy", "domicile", "savings_plan_available", "direct_trading_available",
    "fractional_allowed", "scalable_compatible", "preferred_venue", "manual_spread_estimate_pct",
    "liquidity_score", "quality_score", "momentum_score", "valuation_score", "cost_score",
    "portfolio_fit_score", "risk_control_score", "total_score", "data_source", "source_url",
    "data_confidence", "last_updated", "notes", "valuation_ready", "recommendation_ready",
    "valuation_review_reasons", "recommendation_review_reasons", "provider_status", "enrichment_audit",
    "web_scrape_status", "web_scrape_last_run", "web_scrape_sources", "web_scrape_confidence",
    "factsheet_url", "kid_url", "issuer", "metadata_conflicts", "enrichment_suggestions",
    "confirmed_by_user", "suggested_price_symbols", "suggested_asset_type", "suggested_category",
    "manual_review_attempted", "last_auto_repair_at", "last_updated_date"]

SAMPLE_HOLDINGS = deepcopy(CONFIRMED_BASELINE_HOLDINGS)


def candidate(instrument, isin, ticker, symbol, asset_type, category, theme, region, currency="EUR"):
    """Unknown facts intentionally stay blank and therefore block automated buy eligibility."""
    row = {column: "" for column in CANDIDATE_COLUMNS}
    row.update({"instrument": instrument, "isin": isin, "ticker_id": ticker, "price_symbol": symbol,
                "asset_type": asset_type, "category": category, "theme": theme, "region": region,
                "currency": currency, "savings_plan_available": False, "direct_trading_available": True,
                "fractional_allowed": asset_type == "Crypto", "scalable_compatible": False,
                "preferred_venue": "EIX/gettex", "data_source": "Yahoo symbol sample; quality facts unverified",
                "source_url": f"https://finance.yahoo.com/quote/{symbol}" if symbol else "",
                "last_updated": "", "notes": "Data enrichment required before recommendation."})
    return row


SAMPLE_CANDIDATES = [
    candidate("Vanguard FTSE All-World UCITS ETF", "IE00BK5BQT80", "VWCE", "IE00BK5BQT80.SG", "ETF", "Core", "Global equity", "Global"),
    candidate("Xtrackers MSCI Emerging Markets UCITS ETF", "PLACEHOLDER-EM", "EM ETF", "", "ETF", "EM", "Emerging markets", "Emerging markets"),
    candidate("iShares MSCI India UCITS ETF", "IE00BZCQB185", "NDIA", "NDIA.L", "ETF", "India", "India growth", "India", "GBX"),
    candidate("iShares Nasdaq 100 UCITS ETF", "IE00B53SZB19", "CSNDX", "CSNDX.SW", "ETF", "Quality tech", "Nasdaq 100", "United States", "USD"),
    candidate("VanEck Semiconductor UCITS ETF", "IE00BMC38736", "SMH", "SMH.L", "ETF", "Semiconductors", "Semiconductors", "Global", "USD"),
    candidate("WisdomTree Artificial Intelligence UCITS ETF", "IE00BDVPNG13", "WTAI", "WTAI.MI", "ETF", "AI", "Artificial intelligence", "Global"),
    candidate("iShares Digital Security UCITS ETF", "IE00BG0J4C88", "LOCK", "LOCK.L", "ETF", "Cybersecurity", "Cybersecurity", "Global", "USD"),
    candidate("VanEck Defense UCITS ETF", "IE000YYE6WK5", "DFEN", "DFEN.DE", "ETF", "Defence", "Defence", "Global"),
    candidate("iShares Physical Gold ETC", "IE00B4ND3602", "SGLN", "", "ETC", "Gold", "Physical gold", "Global", "USD"),
    candidate("iShares Physical Silver ETC", "IE00B4NCWG09", "SSLN", "", "ETC", "Silver", "Physical silver", "Global", "USD"),
    candidate("WisdomTree Physical Bitcoin", "GB00BJYDH287", "WBIT", "GB00BJYDH287.SG", "ETP", "Crypto", "Bitcoin", "Global"),
    candidate("Microsoft", "US5949181045", "MSFT", "MSFT", "Stock", "Quality tech", "Cloud and AI", "United States", "USD"),
    candidate("ASML", "NL0010273215", "ASML", "ASML.AS", "Stock", "Semiconductors", "Semiconductor equipment", "Europe"),
    candidate("NVIDIA", "US67066G1040", "NVDA", "NVDA", "Stock", "AI", "AI accelerators", "United States", "USD"),
    candidate("Broadcom", "US11135F1012", "AVGO", "AVGO", "Stock", "Semiconductors", "Semiconductors and infrastructure", "United States", "USD"),
    candidate("Uranium / Energy ETF – confirm exact product", "PLACEHOLDER-URANIUM", "URNM", "", "ETF", "Uranium", "Uranium miners", "Global"),
]

SAMPLE_SAVINGS_PLANS = deepcopy(CONFIRMED_SAVINGS_PLAN)
