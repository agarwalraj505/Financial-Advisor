"""ECB Data Portal FX to EUR, with yfinance fallback."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from urllib.request import Request, urlopen

from providers.base import BaseProvider, ProviderResult


class ECBProvider(BaseProvider):
    name = "ECB"
    purpose = "FX rates"

    def __init__(self, yahoo_provider=None):
        super().__init__()
        self.yahoo = yahoo_provider

    def get_rate_to_eur(self, currency: str) -> ProviderResult:
        currency = str(currency or "").upper()
        if currency == "EUR":
            return self.success({"currency": "EUR", "fx_rate_to_eur": 1.0}, "High")
        if not currency:
            return self.failure("Missing currency; FX manual review required")
        try:
            start = (date.today() - timedelta(days=14)).isoformat()
            url = (f"https://data-api.ecb.europa.eu/service/data/EXR/D.{currency}.EUR.SP00.A"
                   f"?startPeriod={start}&format=csvdata")
            with urlopen(Request(url, headers={"User-Agent": "wealth-manager/1.0"}), timeout=20) as response:
                rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8"))))
            observations = [float(row["OBS_VALUE"]) for row in rows if row.get("OBS_VALUE")]
            if observations and observations[-1]:
                return self.success({"currency": currency, "fx_rate_to_eur": 1 / observations[-1]}, "High")
        except Exception as exc:
            self.last_error = f"ECB failed: {exc}"
        if self.yahoo:
            fallback = self.yahoo.get_price(f"EUR{currency}=X")
            if fallback.success and fallback.data.get("price"):
                return self.success({"currency": currency, "fx_rate_to_eur": 1 / fallback.data["price"],
                                     "fallback_provider": "yfinance"}, "Medium")
        return self.failure("ECB and yfinance FX failed; FX manual review required")
