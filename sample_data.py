"""Non-personal sample data. Market and fund facts require user verification."""

SUPPORTED_CATEGORIES = ["Core", "EM", "India", "Growth", "AI", "Semiconductors", "Quality tech",
    "Defence", "Cybersecurity", "Healthcare innovation", "Robotics", "Energy", "Uranium",
    "Power grid/electrification", "Commodities", "Gold", "Silver", "Crypto", "Cash", "Other tactical"]

TARGET_ALLOCATIONS = {"Core": 25.0, "EM": 15.0, "Growth": 40.0, "Defence": 5.0,
                      "Commodities": 10.0, "Crypto": 5.0, "Cash": 0.0}

CANDIDATE_COLUMNS = ["instrument", "isin", "ticker_id", "price_symbol", "asset_type", "category",
    "theme", "region", "currency", "ter_pct", "fund_size_eur", "replication_method",
    "distribution_policy", "domicile", "savings_plan_available", "direct_trading_available",
    "fractional_allowed", "scalable_compatible", "preferred_venue", "manual_spread_estimate_pct",
    "liquidity_score", "quality_score", "momentum_score", "valuation_score", "cost_score",
    "portfolio_fit_score", "risk_control_score", "total_score", "data_source", "source_url",
    "data_confidence", "last_updated", "notes",
    "overlap_score", "tracking_quality_score", "inception_date", "revenue_growth_score",
    "earnings_quality_score", "valuation_fundamental_score", "profitability_score", "balance_sheet_score"]


def holding(instrument, isin, ticker, symbol, asset_type, category, quantity, value, buy_in, fractional=False):
    price, profit = (value / quantity if quantity else 0), value - buy_in
    return {"instrument": instrument, "isin": isin, "ticker_id": ticker, "price_symbol": symbol,
            "asset_type": asset_type, "category": category, "quantity": quantity,
            "manual_current_price": round(price, 4), "live_current_price": 0.0,
            "price_source": "Manual fallback", "currency": "EUR", "fx_rate_to_eur": 1.0,
            "current_value_eur": value, "buy_in_value_eur": buy_in, "pl_eur": profit,
            "pl_pct": round(profit / buy_in * 100, 2) if buy_in else 0,
            "direct_trading_allowed": True, "fractional_allowed": fractional, "notes": ""}


SAMPLE_HOLDINGS = [
    holding("Scalable MSCI AC World Xtrackers UCITS ETF", "LU2903252349", "ACWI", "SCWX.DE", "ETF", "Core", 61, 724.56, 680),
    holding("iShares Core MSCI EM IMI UCITS ETF", "IE00BKM4GZ66", "EIMI", "EIMI.L", "ETF", "EM", 9, 452.84, 430),
    holding("EUWAX Gold II", "DE000EWG2LD7", "EWG2", "EWG2.SG", "ETC", "Commodities", 2, 240.94, 220),
    holding("Xtrackers Artificial Intelligence & Big Data UCITS ETF", "IE00BGV5VN51", "XAIX", "XAIX.DE", "ETF", "Growth", 1, 216.32, 195),
    holding("VanEck Semiconductor UCITS ETF", "IE00BMC38736", "SMH", "IE00BMC38736.SG", "ETF", "Growth", 2, 216.16, 190),
    holding("HANetf Future of Defence UCITS ETF", "IE000OJ5TQP4", "NATO", "ASWC.DE", "ETF", "Defence", 8, 141.58, 125),
    holding("WisdomTree Physical Crypto Mega Cap", "GB00BMTP1626", "WCRP", "GB00BMTP1626.SG", "ETP", "Crypto", 14, 59.55, 65, True),
    holding("Cash", "CASH", "CASH", "", "Cash", "Cash", 1, 70.46, 70.46, True),
]


def candidate(instrument, isin, ticker, symbol, asset_type, category, theme, region, currency="EUR"):
    """Unknown facts intentionally stay blank and therefore block automated buy eligibility."""
    row = {column: "" for column in CANDIDATE_COLUMNS}
    row.update({"instrument": instrument, "isin": isin, "ticker_id": ticker, "price_symbol": symbol,
                "asset_type": asset_type, "category": category, "theme": theme, "region": region,
                "currency": currency, "savings_plan_available": False, "direct_trading_available": True,
                "fractional_allowed": asset_type == "Crypto", "scalable_compatible": False,
                "preferred_venue": "EIX/gettex", "data_source": "Yahoo symbol sample; quality facts unverified",
                "source_url": f"https://finance.yahoo.com/quote/{symbol}" if symbol else "",
                "last_updated": "", "notes": "Manual review required before recommendation."})
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

SAMPLE_SAVINGS_PLANS = [
    {"instrument": "Scalable MSCI AC World", "isin": "LU2903252349", "category": "Core", "current_plan": 75.0},
    {"instrument": "iShares Core MSCI EM IMI", "isin": "IE00BKM4GZ66", "category": "EM", "current_plan": 45.0},
    {"instrument": "VanEck Semiconductor", "isin": "IE00BMC38736", "category": "Semiconductors", "current_plan": 45.0},
    {"instrument": "Microsoft", "isin": "US5949181045", "category": "Quality tech", "current_plan": 30.0},
    {"instrument": "ASML", "isin": "NL0010273215", "category": "Semiconductors", "current_plan": 25.0},
    {"instrument": "Xtrackers AI & Big Data", "isin": "IE00BGV5VN51", "category": "AI", "current_plan": 20.0},
    {"instrument": "HANetf Future of Defence", "isin": "IE000OJ5TQP4", "category": "Defence", "current_plan": 15.0},
    {"instrument": "EUWAX Gold II", "isin": "DE000EWG2LD7", "category": "Gold", "current_plan": 25.0},
    {"instrument": "iShares Physical Silver", "isin": "IE00B4NCWG09", "category": "Silver", "current_plan": 5.0},
    {"instrument": "WisdomTree Physical Crypto Mega Cap", "isin": "GB00BMTP1626", "category": "Crypto", "current_plan": 15.0},
]
