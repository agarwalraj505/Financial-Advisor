import json
from io import BytesIO
from urllib.error import HTTPError

import pandas as pd

from asset_quality import assess_asset_readiness
from master_rebalance import PIPELINE_STEPS, run_full_rebalance_pipeline
from metadata_enrichment import merge_provider_data
from news_provider import get_market_news
from providers.ecb_provider import ECBProvider
from providers.fmp_provider import FMPProvider
from providers.openfigi_provider import OpenFIGIProvider
from providers.twelvedata_provider import TwelveDataProvider
from providers.base import ProviderResult
from screenshot_parser import (calculate_spread_from_bid_ask, normalize_euro_number,
                               parse_scalable_text, update_holding_by_isin)
from savings_plan_manager import (apply_savings_plan_updates, create_savings_plan_execution_checklist,
                                  validate_savings_plan_budget)
from sentiment_engine import create_market_sentiment_summary
from strategy_engine import get_current_strategy, refresh_market_strategy
from web_scraper import (extract_etf_metadata_from_text, extract_metadata_from_url,
                         merge_scraped_metadata)


def complete_asset(**updates):
    row = {"quantity": 2, "live_current_price": 100, "currency": "EUR", "fx_rate_to_eur": 1,
           "category": "Core", "asset_type": "ETF", "ter_pct": .2,
           "scalable_compatible": True, "data_source": "Issuer", "data_confidence": "High"}
    row.update(updates)
    return row


def test_optional_paid_providers_start_disabled_without_keys(monkeypatch):
    monkeypatch.setattr("providers.base.read_secret", lambda *args: "")
    assert FMPProvider().enabled is False
    assert TwelveDataProvider().enabled is False


def test_openfigi_works_without_api_key(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self):
            return json.dumps([{"data": [{"name": "Example ETF", "ticker": "TEST",
                                           "exchCode": "GR", "marketSector": "Equity",
                                           "securityType": "ETF", "securityType2": "Mutual Fund"}]}]).encode()
    monkeypatch.setattr("providers.openfigi_provider.urlopen", lambda request, timeout: Response())
    monkeypatch.setattr("providers.base.read_secret", lambda *args: "")
    result = OpenFIGIProvider().map_isin("IE00TEST0001")
    assert result.success and result.confidence == "High" and result.data["ticker_id"] == "TEST"


def test_missing_openfigi_key_and_rate_limit_do_not_crash(monkeypatch):
    monkeypatch.setattr("providers.base.read_secret", lambda *args: "")
    monkeypatch.setattr("providers.openfigi_provider.urlopen",
                        lambda *args, **kwargs: (_ for _ in ()).throw(HTTPError("x", 429, "limit", {}, None)))
    result = OpenFIGIProvider().map_isin("IE00TEST0001")
    assert not result.success and result.status_code == 429


def test_existing_holding_without_ter_is_valuation_ready_not_recommendation_ready():
    result = assess_asset_readiness(complete_asset(ter_pct=None), is_candidate=False)
    assert result["valuation_ready"] is True
    assert result["recommendation_ready"] is False


def test_candidate_etf_without_ter_is_not_recommendation_ready():
    result = assess_asset_readiness(complete_asset(ter_pct=None), is_candidate=True)
    assert result["recommendation_ready"] is False


def test_candidate_stock_does_not_require_ter():
    result = assess_asset_readiness(complete_asset(asset_type="Stock", ter_pct=None), is_candidate=True)
    assert result["recommendation_ready"] is True


def test_ecb_uses_yfinance_fallback(monkeypatch):
    monkeypatch.setattr("providers.ecb_provider.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down")))
    class Yahoo:
        def get_price(self, symbol):
            return ProviderResult(True, "yfinance", {"price": 1.2}, "Medium")
    result = ECBProvider(Yahoo()).get_rate_to_eur("USD")
    assert result.success and round(result.data["fx_rate_to_eur"], 4) == round(1 / 1.2, 4)


def test_ecb_failure_requests_fx_review(monkeypatch):
    monkeypatch.setattr("providers.ecb_provider.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down")))
    class Yahoo:
        def get_price(self, symbol): return ProviderResult(False, "yfinance", error="down")
    result = ECBProvider(Yahoo()).get_rate_to_eur("USD")
    assert not result.success and "manual review" in result.error.lower()


def test_etf_metadata_patterns_and_high_confidence():
    text = ("ISIN IE00TEST0001 TER: 0.20% Fund size EUR 1.5 billion Physical replication "
            "Accumulating Domicile: Ireland")
    result = extract_etf_metadata_from_text(text, "https://www.ishares.com/factsheet", "IE00TEST0001")
    assert result["ter_percent"] == .2
    assert result["fund_size_eur"] == 1_500_000_000
    assert result["replication_method"] == "Physical"
    assert result["distribution_policy"] == "Accumulating"
    assert result["extraction_confidence"] == "High"


def test_missing_isin_reduces_extraction_confidence():
    result = extract_etf_metadata_from_text("TER 0.20%", "https://www.ishares.com/factsheet", "IE00MISSING1")
    assert result["extraction_confidence"] == "Low"


def test_user_entered_value_is_not_overwritten_and_conflict_is_stored():
    result = merge_provider_data({"instrument": "User name"}, {"name": "Provider name"}, "OpenFIGI", "High")
    assert result["instrument"] == "User name"
    assert result["metadata_conflicts"]["instrument"]["suggested"] == "Provider name"


def test_scraped_conflict_is_stored():
    result = merge_scraped_metadata({"ter_pct": .2}, [{"ter_percent": .3, "source_url": "x",
                                                        "extraction_confidence": "High"}])
    assert result["ter_pct"] == .2
    assert result["metadata_conflicts"]["ter_pct"]["suggested"] == .3


def test_high_confidence_ter_suggestion_can_complete_candidate_readiness():
    asset = complete_asset(ter_pct=None, enrichment_suggestions={"ter_pct": {"value": .2, "confidence": "High"}})
    assert assess_asset_readiness(asset, True)["recommendation_ready"] is True


def test_low_confidence_ter_suggestion_keeps_candidate_in_review():
    asset = complete_asset(ter_pct=None, enrichment_suggestions={"ter_pct": {"value": .2, "confidence": "Low"}})
    assert assess_asset_readiness(asset, True)["recommendation_ready"] is False


def test_scraper_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr("web_scraper.fetch_page", lambda url: "")
    result = extract_metadata_from_url("https://example.com/fund", {"isin": "IE00TEST0001"})
    assert result["error"]


def test_news_provider_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr("news_provider._read_rss", lambda *args: [])
    get_market_news.clear()
    assert get_market_news() == []


def test_sentiment_engine_returns_confidence_and_explanation():
    result = create_market_sentiment_summary([{"title": "Strong growth rally", "summary": "record gain"}], pd.DataFrame())
    assert result["confidence"] in {"Low", "Medium", "High"}
    assert result["explanation"]


def test_strategy_changes_themes_only_with_sufficient_evidence():
    settings = {"risk_profile": "Aggressive"}; targets = {"Core": 100}
    research = pd.DataFrame([{"category": "AI", "momentum_score": 9}])
    low = refresh_market_strategy(None, None, targets, {"market_regime": "Risk-on", "confidence": "Low"}, research, settings)
    high = refresh_market_strategy(None, None, targets, {"market_regime": "Risk-on", "confidence": "High"}, research, settings)
    assert low["preferred_themes"] == []
    assert high["preferred_themes"] == ["AI"]


def test_full_pipeline_calls_every_stage_in_order():
    called = []
    steps = {name: (lambda results, stage=name: called.append(stage) or stage) for name in PIPELINE_STEPS}
    result = run_full_rebalance_pipeline(steps)
    assert called == PIPELINE_STEPS
    assert result["run_status"] == "Completed"


def test_european_number_parsing():
    assert normalize_euro_number("721,08 €") == 721.08
    assert normalize_euro_number("+2,99 %") == 2.99
    assert normalize_euro_number("11,82 € / Share") == 11.82


def test_screenshot_parses_identifiers_values_and_pl():
    text = "Example ETF\nISIN IE00TEST0001\nWKN ABC123\nQuantity 61\nCurrent position value 721,08 €\nAbsolute P/L +20,94 €\nRelative P/L +2,99 %"
    result = parse_scalable_text(text)
    assert result["isin"] == "IE00TEST0001" and result["wkn"] == "ABC123"
    assert result["quantity"] == 61 and result["current_value_eur"] == 721.08
    assert result["pl_eur"] == 20.94 and result["pl_pct"] == 2.99


def test_spread_calculation():
    result = calculate_spread_from_bid_ask(11.782, 11.860)
    assert result["spread_eur"] == .078
    assert result["spread_percent"] > 0


def test_existing_holding_update_by_isin_preserves_protected_fields():
    rows = [{"isin": "X", "category": "Core", "asset_type": "ETF", "price_symbol": "OLD", "quantity": 1}]
    result = update_holding_by_isin(rows, {"isin": "X", "category": "AI", "quantity": 2})
    assert result[0]["category"] == "Core" and result[0]["quantity"] == 2


def test_savings_plan_budget_validation():
    frame = pd.DataFrame([{"isin": "A", "new_plan": 100}, {"isin": "B", "new_plan": 200}])
    assert validate_savings_plan_budget(frame, 300)["valid"] is True


def test_optimizer_output_applies_to_editable_plans():
    current = pd.DataFrame([{"isin": "A", "instrument": "A", "current_plan": 100}])
    edited = pd.DataFrame([{"isin": "A", "instrument": "A", "current_plan": 100, "new_plan": 150}])
    result = apply_savings_plan_updates(current, edited)
    assert result.loc[0, "new_plan"] == 150 and result.loc[0, "last_updated"]


def test_savings_plan_execution_checklist_generation():
    current = pd.DataFrame([{"isin": "A", "instrument": "A", "current_plan": 100}])
    optimized = pd.DataFrame([{"isin": "A", "instrument": "A", "new_plan": 0}])
    checklist = create_savings_plan_execution_checklist(current, optimized)
    assert checklist.loc[0, "Action"] == "Pause"
    assert "manually" in checklist.loc[0, "Warning"]
