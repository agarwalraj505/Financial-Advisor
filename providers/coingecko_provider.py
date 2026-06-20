"""Optional CoinGecko public/demo crypto fallback. No key is required."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from providers.base import BaseProvider


class CoinGeckoProvider(BaseProvider):
    name = "CoinGecko"
    purpose = "Crypto fallback"
    key_name = "COINGECKO_API_KEY"

    def get_price_eur(self, coin_id: str):
        if not coin_id:
            return self.failure("Missing CoinGecko coin ID")
        headers = {"Accept": "application/json", "User-Agent": "wealth-manager/1.0"}
        if self.api_key:
            headers["x-cg-demo-api-key"] = self.api_key
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?" + urlencode(
                {"ids": coin_id, "vs_currencies": "eur"})
            with urlopen(Request(url, headers=headers), timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
            price = data.get(coin_id, {}).get("eur")
            return self.success({"price": float(price), "currency": "EUR"}, "Medium") if price else self.failure("CoinGecko price missing")
        except Exception as exc:
            return self.failure(str(exc) or "CoinGecko unavailable")

    def status_row(self, key_label: str = "Optional") -> dict:
        row = super().status_row(key_label)
        row["Status"] = "Optional"
        return row
