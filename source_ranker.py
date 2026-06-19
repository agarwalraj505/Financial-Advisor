"""Reliability ranking for public metadata sources."""

from __future__ import annotations

from urllib.parse import urlparse

ISSUER_HINTS = ["ishares.com", "vanguard", "xtrackers", "vaneck", "wisdomtree", "hanetf",
                "amundietf", "invesco", "ssga.com", "jpmorgan", "ubs.com"]
EXCHANGE_HINTS = ["deutsche-boerse", "londonstockexchange", "euronext", "six-group", "boerse-"]
AGGREGATORS = ["justetf.com", "extraetf.com"]
FINANCE_PORTALS = ["finance.yahoo", "morningstar", "marketscreener", "investing.com"]


def classify_source_url(url: str) -> dict:
    host = urlparse(str(url)).netloc.lower()
    path = urlparse(str(url)).path.lower()
    if any(hint in host for hint in ISSUER_HINTS) or "factsheet" in path:
        return {"source_type": "Official issuer / factsheet", "rank": 1, "confidence": "High"}
    if any(hint in host for hint in EXCHANGE_HINTS):
        return {"source_type": "Official exchange", "rank": 2, "confidence": "High"}
    if any(hint in host for hint in AGGREGATORS):
        return {"source_type": "ETF aggregator", "rank": 3, "confidence": "Medium"}
    if any(hint in host for hint in FINANCE_PORTALS):
        return {"source_type": "Finance portal", "rank": 4, "confidence": "Low"}
    return {"source_type": "Public web source", "rank": 5, "confidence": "Low"}


def rank_source_urls(urls: list[str]) -> list[str]:
    return sorted(dict.fromkeys(urls), key=lambda url: classify_source_url(url)["rank"])
