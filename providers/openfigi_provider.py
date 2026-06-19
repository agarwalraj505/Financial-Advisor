"""Unauthenticated OpenFIGI ISIN mapping with optional higher-limit key."""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from providers.base import BaseProvider, ProviderResult


class OpenFIGIProvider(BaseProvider):
    name = "OpenFIGI"
    purpose = "ISIN mapping"
    key_name = "OPENFIGI_API_KEY"

    def map_isins(self, isins: list[str]) -> list[ProviderResult]:
        clean = [str(isin).strip() for isin in isins if str(isin).strip()][:10]
        if not clean:
            return []
        payload = [{"idType": "ID_ISIN", "idValue": isin} for isin in clean]
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "wealth-manager/1.0"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        try:
            request = Request("https://api.openfigi.com/v3/mapping", data=json.dumps(payload).encode(),
                              headers=headers, method="POST")
            with urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
            results = []
            for isin, item in zip(clean, body):
                matches = item.get("data", []) if isinstance(item, dict) else []
                if not matches:
                    results.append(self.failure(f"No OpenFIGI match for {isin}"))
                    continue
                match = matches[0]
                data = {"isin": isin, "instrument": match.get("name"), "ticker_id": match.get("ticker"),
                        "exchange": match.get("exchCode"), "market_sector": match.get("marketSector"),
                        "security_type": match.get("securityType"), "security_type_2": match.get("securityType2"),
                        "provider": "OpenFIGI"}
                results.append(self.success(data, "High"))
            return results
        except HTTPError as exc:
            message = "OpenFIGI rate limit reached; continue with other providers" if exc.code == 429 else f"OpenFIGI HTTP {exc.code}"
            return [self.failure(message, exc.code) for _ in clean]
        except Exception as exc:
            return [self.failure(str(exc) or "OpenFIGI unavailable") for _ in clean]

    def map_isin(self, isin: str) -> ProviderResult:
        results = self.map_isins([isin])
        return results[0] if results else self.failure("Missing ISIN")
