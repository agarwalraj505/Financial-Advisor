"""Best-effort public-page price fallback; low-confidence snippets are never valued."""

from __future__ import annotations

from providers.base import BaseProvider


class WebPriceProvider(BaseProvider):
    name = "Web price"
    purpose = "Public product-page price fallback"

    def get_price(self, asset: dict):
        from web_search import find_candidate_source_urls
        from web_scraper import extract_metadata_from_url

        try:
            urls = find_candidate_source_urls(asset, max_results=5)
            attempts = []
            for url in urls[:3]:
                metadata = extract_metadata_from_url(url, asset)
                attempts.append({"url": url, "error": metadata.get("error", ""),
                                 "confidence": metadata.get("extraction_confidence", "Low")})
                price = metadata.get("price")
                confidence = metadata.get("extraction_confidence", "Low")
                if price and float(price) > 0 and confidence in {"High", "Medium"}:
                    return self.success({"price": float(price), "currency": metadata.get("currency", ""),
                                         "source_url": url, "attempts": attempts}, confidence)
            return self.failure("No verified public-page price; attempts=" + str(attempts)[:1200])
        except Exception as exc:
            return self.failure(str(exc) or "Web price lookup failed")

