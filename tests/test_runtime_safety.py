import ast
import importlib
from pathlib import Path

import pytest

from market_data_engine import MarketDataEngine
from providers.web_price_provider import WebPriceProvider


@pytest.mark.parametrize("module", [
    "market_data", "market_data_engine", "strategy_engine", "master_rebalance",
    "web_scraper", "symbol_resolver", "providers.base", "providers.yfinance_provider",
    "providers.openfigi_provider", "providers.ecb_provider", "providers.coingecko_provider",
    "providers.stooq_provider", "providers.web_price_provider",
])
def test_core_runtime_imports_resolve(module):
    assert importlib.import_module(module)


def test_market_data_engine_initializes_without_optional_keys(monkeypatch):
    monkeypatch.setattr("providers.base.read_secret", lambda *args: "")
    engine = MarketDataEngine(scraping_enabled=False)
    statuses = {row["Provider"]: row["Status"] for row in engine.provider_status_rows()}
    assert statuses["yfinance"] == "Enabled"
    assert statuses["FMP"] == "Disabled"
    assert statuses["Twelve Data"] == "Disabled"


def test_web_price_failure_is_non_fatal(monkeypatch):
    monkeypatch.setattr("web_search.find_candidate_source_urls", lambda *args, **kwargs: [])
    result = WebPriceProvider().get_price({"isin": "IE00TEST0001"})
    assert result.success is False
    assert result.error


def test_no_invalid_or_unwrapped_streamlit_toasts_remain():
    root = Path(__file__).parents[1]
    valid = {"✅", "⚠️", "❌", "ℹ️", "🔄", "💾", "📈", "📰", "🧠"}
    problems = []
    for path in root.rglob("*.py"):
        if ".venv" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "toast"):
                continue
            if path.name != "ui_components.py":
                problems.append(f"direct toast in {path}")
            for keyword in node.keywords:
                if keyword.arg == "icon" and isinstance(keyword.value, ast.Constant):
                    if keyword.value.value not in valid:
                        problems.append(f"invalid icon {keyword.value.value!r} in {path}")
    assert problems == []

