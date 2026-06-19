from asset_quality import calculate_asset_quality, critical_missing_fields


def test_etf_missing_critical_data_is_blocked():
    asset = {"asset_type": "ETF", "price_symbol": "TEST", "ter_pct": None,
             "fund_size_eur": None, "manual_spread_estimate_pct": None}
    result = calculate_asset_quality(asset)
    assert result["manual_review_required"]
    assert set(critical_missing_fields(asset)) == {"TER %", "Fund size EUR", "Manual spread estimate %"}
    assert "Manual review required" in result["quality_reason"]


def test_complete_low_cost_liquid_etf_scores_well():
    asset = {"asset_type": "ETF", "price_symbol": "TEST", "ter_pct": 0.12,
             "fund_size_eur": 2_000_000_000, "manual_spread_estimate_pct": 0.08,
             "liquidity_score": 9, "replication_method": "Physical", "domicile": "Ireland",
             "tracking_quality_score": 9, "overlap_score": 2}
    result = calculate_asset_quality(asset)
    assert not result["manual_review_required"]
    assert result["quality_score"] >= 8
    assert result["quality_confidence"] == "High"
