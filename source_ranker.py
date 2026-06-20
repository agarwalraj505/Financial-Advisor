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
    issuer = any(hint in host for hint in ISSUER_HINTS)
    if issuer and not any(term in path for term in ("factsheet", "kid", "kiid")):
        return {"source_type": "Official issuer", "rank": 1, "confidence": "High"}
    if "factsheet" in path or (issuer and path.endswith(".pdf")):
        return {"source_type": "Official factsheet PDF", "rank": 2, "confidence": "High"}
    if any(term in path for term in ("kid", "kiid")):
        return {"source_type": "KID/KIID PDF", "rank": 3, "confidence": "High" if issuer else "Medium"}
    if any(hint in host for hint in EXCHANGE_HINTS):
        return {"source_type": "Official exchange", "rank": 4, "confidence": "High"}
    if any(hint in host for hint in AGGREGATORS):
        return {"source_type": "ETF aggregator", "rank": 5, "confidence": "Medium"}
    if any(hint in host for hint in FINANCE_PORTALS):
        return {"source_type": "Finance portal", "rank": 6, "confidence": "Low"}
    return {"source_type": "Public web source", "rank": 7, "confidence": "Low"}


def rank_source_urls(urls: list[str]) -> list[str]:
    return sorted(dict.fromkeys(urls), key=lambda url: classify_source_url(url)["rank"])
