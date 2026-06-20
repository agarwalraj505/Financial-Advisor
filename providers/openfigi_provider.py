"""Unauthenticated OpenFIGI ISIN mapping with optional higher-limit key."""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from providers.base import BaseProvider, ProviderResult
from rate_limiter import OPENFIGI_LIMITER


def build_mapping_request(isins: list[str], api_key: str = "") -> Request:
    """Build an unauthenticated request by default; optional key only raises limits."""
    payload = [{"idType": "ID_ISIN", "idValue": str(isin).strip()} for isin in isins[:5]]
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "wealth-manager/1.0"}
    if api_key: headers["X-OPENFIGI-APIKEY"] = api_key
    return Request("https://api.openfigi.com/v3/mapping", data=json.dumps(payload).encode(), headers=headers, method="POST")


class OpenFIGIProvider(BaseProvider):
    name = "OpenFIGI"
    purpose = "ISIN mapping"
    key_name = "OPENFIGI_API_KEY"

    def map_isins(self, isins: list[str]) -> list[ProviderResult]:
        clean = [str(isin).strip() for isin in isins if str(isin).strip()]
        if not clean:
            return []
        results = []
        for offset in range(0, len(clean), 5):
            batch = clean[offset:offset + 5]
            try:
                OPENFIGI_LIMITER.acquire(); request = build_mapping_request(batch, self.api_key)
                with urlopen(request, timeout=8) as response:
                    body = json.loads(response.read().decode("utf-8"))
                for isin, item in zip(batch, body):
                    matches = item.get("data", []) if isinstance(item, dict) else []
                    if not matches: results.append(self.failure(f"No OpenFIGI match for {isin}")); continue
                    match = matches[0]
                    results.append(self.success({"isin": isin, "instrument": match.get("name"), "ticker_id": match.get("ticker"),
                        "exchange": match.get("exchCode"), "market_sector": match.get("marketSector"),
                        "security_type": match.get("securityType"), "security_type_2": match.get("securityType2"),
                        "provider": "OpenFIGI"}, "High"))
            except HTTPError as exc:
                message = "OpenFIGI rate limit reached; continue with other providers" if exc.code == 429 else f"OpenFIGI HTTP {exc.code}"
                results.extend(self.failure(message, exc.code) for _ in batch)
            except Exception as exc:
                results.extend(self.failure(str(exc) or "OpenFIGI unavailable") for _ in batch)
        return results

    def map_isin(self, isin: str) -> ProviderResult:
        results = self.map_isins([isin])
        return results[0] if results else self.failure("Missing ISIN")

    def search_name(self, name: str) -> ProviderResult:
        if not str(name or "").strip(): return self.failure("Missing instrument name")
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "wealth-manager/1.0"}
        if self.api_key: headers["X-OPENFIGI-APIKEY"] = self.api_key
        try:
            OPENFIGI_LIMITER.acquire()
            request = Request("https://api.openfigi.com/v3/search", data=json.dumps({"query": str(name)[:200]}).encode(),
                              headers=headers, method="POST")
            with urlopen(request, timeout=8) as response: body = json.loads(response.read().decode("utf-8"))
            matches = body.get("data", []) if isinstance(body, dict) else []
            if not matches: return self.failure("No OpenFIGI name match")
            match = matches[0]
            return self.success({"instrument": match.get("name"), "ticker_id": match.get("ticker"),
                                 "exchange": match.get("exchCode"), "security_type": match.get("securityType"),
                                 "security_type_2": match.get("securityType2"), "provider": "OpenFIGI"}, "Medium")
        except HTTPError as exc:
            return self.failure("OpenFIGI name search rate limited" if exc.code == 429 else f"OpenFIGI HTTP {exc.code}", exc.code)
        except Exception as exc:
            return self.failure(str(exc) or "OpenFIGI name search unavailable")
