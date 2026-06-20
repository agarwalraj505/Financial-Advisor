from rulebook_engine import (create_rebalance_checklist, validate_rebalance_guardrails,
                             validate_trade_against_rulebook)


def test_trade_below_250_is_flagged_unless_justified():
    trade = {"Action": "Buy new asset", "Purpose": "Growth", "Quantity": 2,
             "Est. value": 200, "scalable_compatible": True, "Reason": "Underweight"}
    assert validate_trade_against_rulebook(trade)["blocked"]
    trade["strongly_justified"] = True
    assert validate_trade_against_rulebook(trade)["valid"]


def test_direct_trade_quantities_must_be_whole():
    trade = {"Action": "Buy new asset", "Quantity": 1.5, "Est. value": 300,
             "scalable_compatible": True, "Reason": "Underweight"}
    result = validate_trade_against_rulebook(trade)
    assert any("whole number" in warning for warning in result["warnings"])


def test_candidate_buy_is_blocked_without_scalable_confirmation():
    trade = {"Action": "Buy new asset", "Quantity": 2, "Est. value": 300,
             "scalable_compatible": False, "Reason": "Underweight"}
    assert validate_trade_against_rulebook(trade)["blocked"]


def test_guardrails_do_not_assume_unimplemented_recommendation():
    context = {"baseline_source": "Confirmed baseline", "last_recommendation_assumed_implemented": False,
               "market_data_refreshed": True, "news_refreshed": True,
               "themes_considered": ["AI infrastructure", "Utilities / grid", "Data centers", "Financials",
                   "Healthcare", "Defence", "Gold", "Silver", "Crypto", "Emerging markets", "India",
                   "China", "Japan", "Energy", "Materials", "Robotics", "Automation", "Cybersecurity"],
               "regions_considered": ["United States", "Europe", "Emerging markets", "India", "China", "Japan"],
               "themes_bought": [], "themes_watchlisted": [], "trades": [],
               "savings_plan_reviewed": True, "scalable_price_check_required": True}
    result = validate_rebalance_guardrails(context)
    check = next(item for item in result["checks"] if item["check_name"] == "Last recommendation not assumed implemented")
    assert check["passed"] is True
    assert create_rebalance_checklist(context)["skip_conditions"]
