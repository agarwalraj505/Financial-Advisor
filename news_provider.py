"""Legal/free RSS and yfinance news ingestion with graceful failure."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import streamlit as st
import yfinance as yf

from news_sources import GDELT_QUERY, MARKET_THEMES, RSS_SOURCES

RSS_FEEDS = RSS_SOURCES


def _normalise_gdelt_timestamp(value: str) -> str:
    """Convert GDELT's compact timestamp into a Postgres-friendly ISO value."""
    text = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            parsed = datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
            return parsed.isoformat(timespec="seconds")
        except ValueError:
            pass
    return text


def normalize_news_item(item: dict) -> dict:
    title = str(item.get("title", "") or "").strip()
    url = str(item.get("url") or item.get("link") or "").strip()
    return {"title": title, "url": url, "source": item.get("source", "Unknown"),
            "published_at": item.get("published_at") or item.get("pubDate") or "",
            "summary": str(item.get("summary", "") or ""), "category": item.get("category", "Global markets"),
            "related_symbols": item.get("related_symbols", []), "related_themes": item.get("related_themes", []),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def deduplicate_news(items: list[dict]) -> list[dict]:
    seen, output = set(), []
    for item in items:
        normalized = normalize_news_item(item)
        key = normalized["url"] or hashlib.sha256(normalized["title"].lower().encode()).hexdigest()
        if key not in seen and normalized["title"]:
            seen.add(key); output.append(normalized)
    return output


def _read_rss(source: str, url: str, category: str) -> list[dict]:
    try:
        with urlopen(Request(url, headers={"User-Agent": "wealth-manager/1.0"}), timeout=10) as response:
            root = ET.fromstring(response.read(2_000_000))
        items = []
        for node in root.findall(".//item")[:30]:
            items.append({"title": node.findtext("title", ""), "url": node.findtext("link", ""),
                          "summary": node.findtext("description", ""), "published_at": node.findtext("pubDate", ""),
                          "source": source, "category": category})
        return items
    except Exception:
        return []


def get_gdelt_news(query: str = GDELT_QUERY, max_records: int = 50) -> list[dict]:
    """Best-effort public GDELT DOC API; empty list on timeout/rate limit."""
    try:
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=" + quote_plus(query) +
               f"&mode=ArtList&maxrecords={min(75, max_records)}&format=json&sort=HybridRel")
        with urlopen(Request(url, headers={"User-Agent": "wealth-manager/1.0"}), timeout=10) as response:
            body = json.loads(response.read(3_000_000).decode("utf-8", errors="ignore"))
        items = []
        for article in body.get("articles", []):
            title = article.get("title", ""); lower = title.lower()
            themes = [theme for theme in MARKET_THEMES if theme.lower().split("/")[0] in lower]
            items.append({"title": title, "url": article.get("url", ""), "summary": "",
                          "published_at": _normalise_gdelt_timestamp(article.get("seendate", "")),
                          "source": article.get("domain", "GDELT"),
                          "category": themes[0] if themes else "Global markets", "related_themes": themes})
        return deduplicate_news(items)
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_market_news() -> list[dict]:
    items = get_gdelt_news()
    for source, url, category in RSS_FEEDS:
        items.extend(_read_rss(source, url, category))
    return deduplicate_news(items)


@st.cache_data(ttl=3600, show_spinner=False)
def get_asset_news(asset: dict) -> list[dict]:
    symbol = str(asset.get("price_symbol", "") or "")
    if not symbol: return []
    try:
        items = []
        for raw in yf.Ticker(symbol).news or []:
            content = raw.get("content", raw)
            canonical = content.get("canonicalUrl", {}) if isinstance(content.get("canonicalUrl"), dict) else {}
            items.append({"title": content.get("title", ""), "url": canonical.get("url", ""),
                          "summary": content.get("summary", ""), "published_at": content.get("pubDate", ""),
                          "source": content.get("provider", {}).get("displayName", "Yahoo Finance") if isinstance(content.get("provider"), dict) else "Yahoo Finance",
                          "category": asset.get("category", "Global markets"), "related_symbols": [symbol]})
        return deduplicate_news(items)
    except Exception:
        return []


def get_theme_news(theme: str) -> list[dict]:
    theme = str(theme or "").lower()
    return [item for item in get_market_news() if theme and theme in (item["title"] + " " + item["summary"]).lower()]


def get_macro_news() -> list[dict]:
    return [item for item in get_market_news() if item["category"] in {"Global markets", "Interest rates / central banks"}]


def get_crypto_news() -> list[dict]:
    return [item for item in get_market_news() if item["category"] == "Crypto"]


def rank_news_by_relevance(items: list[dict], holdings, candidates, strategy=None) -> list[dict]:
    terms = set()
    for frame in (holdings, candidates):
        if hasattr(frame, "iterrows"):
            for _, row in frame.iterrows():
                terms.update(str(row.get(field, "")).lower() for field in ("instrument", "theme", "category") if row.get(field))
    def score(item):
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        return sum(term in text for term in terms if len(term) > 2)
    return sorted(deduplicate_news(items), key=score, reverse=True)


def save_news_snapshot(items: list[dict]) -> list[dict]:
    return [normalize_news_item(item) for item in items]
