"""Non-personal sample data used for first launch and reset."""

TARGET_ALLOCATIONS = {"Core": 25.0, "EM": 15.0, "Growth": 40.0, "Defence": 5.0,
                      "Commodities": 10.0, "Crypto": 5.0, "Cash": 0.0}


def holding(instrument, isin, ticker, price_symbol, asset_type, category, quantity, value, buy_in, fractional=False):
    price, profit = (value / quantity if quantity else 0), value - buy_in
    return {"instrument": instrument, "isin": isin, "ticker_id": ticker, "price_symbol": price_symbol,
            "asset_type": asset_type, "category": category, "quantity": quantity,
            "manual_current_price": round(price, 4), "live_current_price": 0.0,
            "price_source": "Manual fallback", "currency": "EUR", "fx_rate_to_eur": 1.0,
            "current_value_eur": value, "buy_in_value_eur": buy_in, "pl_eur": profit,
            "pl_pct": round(profit / buy_in * 100, 2) if buy_in else 0,
            "direct_trading_allowed": True, "fractional_allowed": fractional, "notes": ""}


SAMPLE_HOLDINGS = [
    holding("Scalable MSCI AC World Xtrackers UCITS ETF", "LU2903252349", "ACWI", "", "ETF", "Core", 61, 724.56, 680),
    holding("iShares Core MSCI EM IMI UCITS ETF", "IE00BKM4GZ66", "EIMI", "EIMI.L", "ETF", "EM", 9, 452.84, 430),
    holding("EUWAX Gold II", "DE000EWG2LD7", "EWG2", "EWG2.DE", "ETC", "Commodities", 2, 240.94, 220),
    holding("Xtrackers Artificial Intelligence & Big Data UCITS ETF", "IE00BGV5VN51", "XAIX", "XAIX.DE", "ETF", "Growth", 1, 216.32, 195),
    holding("VanEck Semiconductor UCITS ETF", "IE00BMC38736", "SMH", "VVSM.DE", "ETF", "Growth", 2, 216.16, 190),
    holding("HANetf Future of Defence UCITS ETF", "IE000OJ5TQP4", "NATO", "ASWC.DE", "ETF", "Defence", 8, 141.58, 125),
    holding("WisdomTree Physical Crypto Mega Cap", "GB00BMTP1626", "WCRP", "WCRP.DE", "ETP", "Crypto", 14, 59.55, 65, True),
    holding("Cash", "CASH", "CASH", "", "Cash", "Cash", 1, 70.46, 70.46, True),
]

SAMPLE_SAVINGS_PLANS = [
    {"instrument": "Scalable MSCI AC World", "isin": "LU2903252349", "category": "Core", "current_plan": 75.0},
    {"instrument": "iShares Core MSCI EM IMI", "isin": "IE00BKM4GZ66", "category": "EM", "current_plan": 45.0},
    {"instrument": "VanEck Semiconductor", "isin": "IE00BMC38736", "category": "Growth", "current_plan": 45.0},
    {"instrument": "Microsoft", "isin": "US5949181045", "category": "Growth", "current_plan": 30.0},
    {"instrument": "ASML", "isin": "NL0010273215", "category": "Growth", "current_plan": 25.0},
    {"instrument": "Xtrackers AI & Big Data", "isin": "IE00BGV5VN51", "category": "Growth", "current_plan": 20.0},
    {"instrument": "HANetf Future of Defence", "isin": "IE000OJ5TQP4", "category": "Defence", "current_plan": 15.0},
    {"instrument": "EUWAX Gold II", "isin": "DE000EWG2LD7", "category": "Commodities", "current_plan": 25.0},
    {"instrument": "iShares Physical Silver", "isin": "IE00B4NCWG09", "category": "Commodities", "current_plan": 5.0},
    {"instrument": "WisdomTree Physical Crypto Mega Cap", "isin": "GB00BMTP1626", "category": "Crypto", "current_plan": 15.0},
]
