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

    def __init__(self, yahoo_provider=None, alpha_vantage_provider=None):
        super().__init__()
        self.yahoo = yahoo_provider
        self.alpha = alpha_vantage_provider

    def get_rate_to_eur(self, currency: str) -> ProviderResult:
        raw_currency = str(currency or "")
        currency = "GBX" if raw_currency == "GBp" or raw_currency.upper() in {"GBX", "GBPENCE"} else raw_currency.upper()
        if currency == "EUR":
            return self.success({"currency": "EUR", "fx_rate_to_eur": 1.0}, "High")
        if not currency:
            return self.failure("Missing currency; FX manual review required")
        try:
            start = (date.today() - timedelta(days=14)).isoformat()
            ecb_currency = "GBP" if currency == "GBX" else currency
            url = (f"https://data-api.ecb.europa.eu/service/data/EXR/D.{ecb_currency}.EUR.SP00.A"
                   f"?startPeriod={start}&format=csvdata")
            with urlopen(Request(url, headers={"User-Agent": "wealth-manager/1.0"}), timeout=8) as response:
                rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8"))))
            observations = [float(row["OBS_VALUE"]) for row in rows if row.get("OBS_VALUE")]
            if observations and observations[-1]:
                rate = 1 / observations[-1]
                if currency == "GBX": rate /= 100.0
                return self.success({"currency": currency, "fx_rate_to_eur": rate}, "High")
        except Exception as exc:
            self.last_error = f"ECB failed: {exc}"
        if self.alpha and self.alpha.is_enabled():
            pair_currency = "GBP" if currency == "GBX" else currency
            fallback = self.alpha.get_fx_rate(pair_currency, "EUR")
            if fallback.success and fallback.data.get("rate"):
                rate = float(fallback.data["rate"])
                if currency == "GBX": rate /= 100.0
                return self.success({"currency": currency, "fx_rate_to_eur": rate,
                                     "fallback_provider": "Alpha Vantage"}, "Medium")
        if self.yahoo:
            pair_currency = "GBP" if currency == "GBX" else currency
            fallback = self.yahoo.get_price(f"EUR{pair_currency}=X")
            if fallback.success and fallback.data.get("price"):
                rate = 1 / fallback.data["price"]
                if currency == "GBX": rate /= 100.0
                return self.success({"currency": currency, "fx_rate_to_eur": rate,
                                     "fallback_provider": "yfinance"}, "Medium")
        return self.failure("ECB, Alpha Vantage, and yfinance FX failed; FX manual review required")
