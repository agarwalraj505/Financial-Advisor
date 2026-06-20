import pandas as pd

from master_rebalance import PIPELINE_LABELS
from rebalancer_rulebook import REBALANCE_WORKFLOW, REQUIRED_REBALANCE_SECTIONS
from recommendation_engine import build_structured_rebalance_report
from rulebook_engine import (ALLOCATION_COLUMNS, IMMEDIATE_COLUMNS, SAVINGS_COLUMNS,
                             create_execution_order, format_allocation_table,
                             format_immediate_buy_sell_table, format_savings_plan_table)


def test_pipeline_and_report_sections_have_exact_rulebook_order():
    assert PIPELINE_LABELS == REBALANCE_WORKFLOW
    report = build_structured_rebalance_report(
        strategy={"target_allocations": {"Core": 100}}, theme_ranking=[], target_review=[],
        gap_analysis=[], recommendations=[], execution_order=[], savings_plans=[], allocation=[],
        watchlist=[], market_reasoning="No forced trade.", context={})
    assert list(report) == REQUIRED_REBALANCE_SECTIONS


def test_required_output_table_columns():
    immediate = format_immediate_buy_sell_table(pd.DataFrame([{
        "Action": "Buy new asset", "Purpose": "Growth", "Instrument": "ETF", "ISIN": "X",
        "Ticker/ID": "ETF", "Quantity": 2, "Est. value": 300, "Fee issue": "None", "Reason": "Underweight"}]))
    savings = format_savings_plan_table(pd.DataFrame([{
        "Instrument": "ETF", "ISIN": "X", "Current plan": 10, "New plan": 20, "Action": "Increase"}]))
    allocation = format_allocation_table(pd.DataFrame([{
        "category": "Core", "current_weight": 25, "target_weight": 25, "status": "On target"}]))
    assert immediate.columns.tolist() == IMMEDIATE_COLUMNS
    assert savings.columns.tolist() == SAVINGS_COLUMNS
    assert allocation.columns.tolist() == ALLOCATION_COLUMNS


def test_no_immediate_rebalance_is_valid_output():
    table = format_immediate_buy_sell_table(pd.DataFrame())
    assert table.iloc[0]["Action"] == "No immediate rebalance needed"


def test_execution_order_places_sells_before_buys_and_savings():
    order = create_execution_order([{"Action": "Sell partially", "Instrument": "A"}],
                                   [{"Action": "Buy new asset", "Instrument": "B"}],
                                   [{"Action": "Increase", "Instrument": "C"}])
    assert order["Stage"].tolist() == ["Sell first", "Buy after funded sells", "Update savings plans manually"]
