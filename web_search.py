"""Best-effort no-key public web search. Failures are audit events, never blockers."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from source_ranker import classify_source_url, rank_source_urls


def build_asset_search_queries(asset: dict) -> list[str]:
    isin = str(asset.get("isin", "") or "").strip()
    name = str(asset.get("instrument", "") or "").strip()
    wkn = str(asset.get("wkn", "") or "").strip()
    queries = []
    if isin:
        queries += [f"{isin} TER factsheet fund size", f"{isin} KID UCITS ETF",
                    f"{isin} Yahoo Finance", f"{isin} exchange ticker"]
    if name:
        queries += [f'"{name}" ISIN', f'"{name}" factsheet TER', f'"{name}" issuer UCITS ETF ticker']
    if wkn:
        queries.append(f"{wkn} ETF factsheet")
    return list(dict.fromkeys(queries))


class _ResultParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "result__a" in attributes.get("class", ""):
            href = attributes.get("href", "")
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
            if href.startswith("http"):
                self.urls.append(href)


def search_public_web(query: str, max_results: int = 5) -> list[dict]:
    """Use DuckDuckGo's public HTML page politely; return [] if blocked or unavailable."""
    try:
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        request = Request(url, headers={"User-Agent": "wealth-manager/1.0"})
        with urlopen(request, timeout=15) as response:
            html = response.read(1_500_000).decode("utf-8", errors="ignore")
        parser = _ResultParser(); parser.feed(html)
        return [{"url": url, **classify_source_url(url), "query": query} for url in parser.urls[:max_results]]
    except Exception:
        return []


def find_candidate_source_urls(asset: dict, max_results: int = 5) -> list[str]:
    urls = []
    for query in build_asset_search_queries(asset):
        urls.extend(item["url"] for item in search_public_web(query, max_results))
        if len(urls) >= max_results * 2:
            break
    return rank_source_urls(urls)[:max_results]


def generate_yfinance_symbol_candidates(asset: dict) -> list[str]:
    candidates = []
    for field in ("price_symbol", "ticker_id", "suggested_price_symbol"):
        value = str(asset.get(field, "") or "").strip()
        if value:
            candidates.append(value)
    ticker = str(asset.get("ticker_id", "") or "").strip()
    if ticker and "." not in ticker:
        candidates.extend([ticker, f"{ticker}.DE", f"{ticker}.L", f"{ticker}.AS"])
    return list(dict.fromkeys(candidates))
