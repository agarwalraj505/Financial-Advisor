import pytest

from rebalancer_rulebook import (CONFIRMED_BASELINE_SUMMARY, HISTORICAL_CONTEXT,
                                 REQUIRED_REBALANCE_SECTIONS)
from rulebook_engine import (build_required_rebalance_sections, create_skip_conditions,
                             get_base_target_allocation, get_confirmed_baseline_holdings,
                             get_confirmed_savings_plan, get_current_rulebook,
                             validate_savings_plan_against_rulebook)
from rebalancer import calculate_total_invested, calculate_unrealised_pl


def test_confirmed_baseline_totals_match_rulebook():
    holdings = get_confirmed_baseline_holdings()
    invested = holdings[holdings["category"] != "Cash"]
    assert invested["current_value_eur"].sum() == pytest.approx(2038.83)
    assert holdings["current_value_eur"].sum() == pytest.approx(2109.29)
    assert invested["buy_in_value_eur"].sum() == pytest.approx(1968.51)
    assert CONFIRMED_BASELINE_SUMMARY["unrealized_pl_eur"] == 70.32
    assert calculate_total_invested(holdings) == 1968.51
    assert calculate_unrealised_pl(holdings) == 70.32


def test_confirmed_savings_plan_totals_300():
    plans = get_confirmed_savings_plan()
    assert plans["current_plan"].sum() == 300
    assert validate_savings_plan_against_rulebook(plans)["valid"]


def test_base_targets_sum_to_100_excluding_cash_range():
    targets = get_base_target_allocation()
    assert sum(value for category, value in targets.items() if category != "Cash") == 100
    assert targets["Cash"] == 0


def test_rulebook_has_required_sections_and_historical_context():
    assert build_required_rebalance_sections() == REQUIRED_REBALANCE_SECTIONS
    rulebook = get_current_rulebook()
    assert rulebook["historical_context"]["most_recent_proposed_rebalance_implemented"] is False
    assert HISTORICAL_CONTEXT["assume_later_recommendations_executed"] is False


def test_skip_conditions_are_always_present():
    assert create_skip_conditions({})
    assert any("Scalable" in condition for condition in create_skip_conditions({}))
