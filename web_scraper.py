"""Robots-aware, rate-limited public metadata extraction. No bypass techniques."""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from math import isnan
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

import streamlit as st

from source_ranker import classify_source_url, rank_source_urls
from rate_limiter import WEB_DOMAIN_LIMITER

USER_AGENT = "wealth-manager/1.0"
BLOCKED_HOST_HINTS = ["scalable.capital"]


def can_fetch_url(url: str) -> bool:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or any(hint in parsed.netloc.lower() for hint in BLOCKED_HOST_HINTS):
        return False
    try:
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        WEB_DOMAIN_LIMITER.acquire(robots_url)
        with urlopen(Request(robots_url, headers={"User-Agent": USER_AGENT}), timeout=5) as response:
            robots_text = response.read(500_000).decode("utf-8", errors="ignore")
        parser = RobotFileParser(); parser.set_url(robots_url); parser.parse(robots_text.splitlines())
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        return False  # uncertainty is treated conservatively


@st.cache_data(ttl=604800, show_spinner=False)
def fetch_page(url: str) -> str:
    if not can_fetch_url(url):
        return ""
    try:
        WEB_DOMAIN_LIMITER.acquire(url)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/pdf"})
        with urlopen(request, timeout=12) as response:
            content_type = response.headers.get("Content-Type", "")
            if "pdf" in content_type.lower() or str(url).lower().endswith(".pdf"):
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(BytesIO(response.read(8_000_000)))
                    return " ".join((page.extract_text() or "") for page in reader.pages[:40])
                except Exception:
                    return ""
            if "html" not in content_type.lower(): return ""
            return response.read(2_000_000).decode("utf-8", errors="ignore")
    except Exception:
        return ""


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.links = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text: self.parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href: self.links.append(href)


def extract_text(html: str) -> str:
    parser = _TextParser(); parser.feed(html or "")
    return " ".join(parser.parts)


def _number(text: str) -> float | None:
    if not text: return None
    cleaned = text.replace(" ", "").replace("€", "").replace("%", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try: return float(cleaned)
    except ValueError: return None


def extract_etf_metadata_from_text(text: str, source_url: str, isin: str | None = None) -> dict:
    normalized = " ".join((text or "").split())
    result = {"source_url": source_url, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    patterns = {
        "ter_percent": r"(?:TER|Total expense ratio|Ongoing charges|OCF)\s*[:\-]?\s*([0-9]+[\.,][0-9]+)\s*%",
        "ticker_id": r"(?:Ticker|Exchange ticker)\s*[:\-]?\s*([A-Z0-9\.\-]{1,15})",
        "inception_date": r"(?:Inception date|Launch date)\s*[:\-]?\s*([0-9]{1,2}[\./-][0-9]{1,2}[\./-][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, normalized, re.I)
        if match: result[field] = _number(match.group(1)) if field == "ter_percent" else match.group(1)
    found_isin = re.search(r"\b[A-Z]{2}[A-Z0-9]{10}\b", normalized)
    if found_isin: result["isin"] = found_isin.group(0)
    size = re.search(r"(?:Fund size|Assets under management|AUM)\s*[:\-]?\s*(?:EUR|€)?\s*([0-9]+[\.,]?[0-9]*)\s*(million|billion|m|bn)?", normalized, re.I)
    if size:
        value = _number(size.group(1)); unit = (size.group(2) or "").lower()
        multiplier = 1_000_000_000 if unit in {"billion", "bn"} else 1_000_000 if unit in {"million", "m"} else 1
        result["fund_size_eur"] = value * multiplier if value is not None else None
    if re.search(r"physical(?:ly)? replicated|physical replication", normalized, re.I): result["replication_method"] = "Physical"
    elif re.search(r"synthetic replication|swap based", normalized, re.I): result["replication_method"] = "Synthetic"
    if re.search(r"accumulating|capitalisation", normalized, re.I): result["distribution_policy"] = "Accumulating"
    elif re.search(r"distributing|distribution", normalized, re.I): result["distribution_policy"] = "Distributing"
    domicile = re.search(r"Domicile\s*[:\-]?\s*(Ireland|Luxembourg|Germany)", normalized, re.I)
    if domicile: result["domicile"] = domicile.group(1).title()
    isin_present = bool(isin and re.search(re.escape(isin), normalized, re.I))
    source = classify_source_url(source_url)
    confidence = source["confidence"]
    if not isin_present: confidence = "Low"
    result.update({"source_name": source["source_type"], "extraction_confidence": confidence,
                   "isin_present": isin_present, "extraction_method": "HTML label-pattern extraction"})
    return result


def extract_metadata_from_url(url: str, asset: dict) -> dict:
    html = fetch_page(url)
    if not html:
        return {"source_url": url, "error": "Fetch blocked or failed", "extraction_confidence": "Low"}
    metadata = extract_etf_metadata_from_text(extract_text(html), url, asset.get("isin"))
    parser = _TextParser(); parser.feed(html)
    for href in parser.links:
        absolute = urljoin(url, href)
        lower = absolute.lower()
        if "factsheet" in lower and not metadata.get("factsheet_url"): metadata["factsheet_url"] = absolute
        if ("kid" in lower or "kiid" in lower) and not metadata.get("kid_url"): metadata["kid_url"] = absolute
    return metadata


def scrape_multiple_sources(asset: dict, source_urls: list[str]) -> list[dict]:
    return [extract_metadata_from_url(url, asset) for url in rank_source_urls(source_urls)[:3]]


def merge_scraped_metadata(asset: dict, scraped_results: list[dict]) -> dict:
    """Never overwrite entered values. Store suggestions and conflicts instead."""
    output = dict(asset); conflicts = dict(output.get("metadata_conflicts") or {})
    suggestions = dict(output.get("enrichment_suggestions") or {})
    confidence_rank = {"Low": 1, "Medium": 2, "High": 3}
    def missing(value):
        return value in (None, "") or (isinstance(value, float) and isnan(value))
    for result in scraped_results:
        for field in ("isin", "price_symbol", "ticker_id", "ter_percent", "fund_size_eur", "replication_method",
                      "distribution_policy", "domicile", "inception_date", "issuer", "factsheet_url",
                      "kid_url", "currency", "asset_type"):
            value = result.get(field)
            if missing(value): continue
            app_field = {"ter_percent": "ter_pct"}.get(field, field)
            existing = output.get(app_field)
            if not missing(existing) and str(existing) != str(value):
                conflicts[app_field] = {"entered": existing, "suggested": value,
                                        "source_url": result.get("source_url"),
                                        "confidence": result.get("extraction_confidence")}
            elif missing(existing):
                proposed = {"value": value, "provider": result.get("source_name", "Web enrichment"),
                            "source_url": result.get("source_url"),
                            "source_title": result.get("source_name", "Public source"),
                            "fetched_at": result.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
                            "confidence": result.get("extraction_confidence", "Low")}
                current = suggestions.get(app_field, {})
                if confidence_rank.get(proposed["confidence"], 0) >= confidence_rank.get(current.get("confidence"), 0):
                    suggestions[app_field] = proposed
    output["metadata_conflicts"] = conflicts
    output["enrichment_suggestions"] = suggestions
    output["web_scrape_sources"] = [item.get("source_url") for item in scraped_results if item.get("source_url")]
    output["web_scrape_confidence"] = max((item.get("extraction_confidence", "Low") for item in scraped_results),
                                          key=lambda value: confidence_rank.get(value, 0), default="Low")
    output["web_scrape_status"] = "Success" if suggestions or conflicts else "Failed"
    output["web_scrape_last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return output


def scrape_asset_metadata(asset: dict, source_urls: list[str] | None = None) -> dict:
    from web_search import find_candidate_source_urls
    urls = source_urls if source_urls is not None else find_candidate_source_urls(asset)
    return merge_scraped_metadata(asset, scrape_multiple_sources(asset, urls))
