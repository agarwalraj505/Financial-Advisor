"""Conservative no-key Stooq CSV fallback for recognized symbols."""

from __future__ import annotations

import csv
from datetime import date, timedelta
import io
from urllib.parse import quote
from urllib.request import Request, urlopen

from providers.base import BaseProvider


class StooqProvider(BaseProvider):
    name = "Stooq"
    purpose = "Backup prices/history"

    def get_price(self, symbol: str):
        if not symbol: return self.failure("Missing Stooq symbol")
        try:
            end = date.today(); start = end - timedelta(days=14)
            url = ("https://stooq.com/q/d/l/?s=" + quote(symbol.lower()) +
                   f"&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d")
            with urlopen(Request(url, headers={"User-Agent": "wealth-manager/1.0"}), timeout=8) as response:
                rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8", errors="ignore"))))
            closes = [float(row["Close"]) for row in rows if row.get("Close") not in (None, "", "N/D")]
            if not closes: return self.failure("No usable Stooq price")
            return self.success({"price": closes[-1], "currency": "", "history_rows": len(closes), "symbol": symbol}, "Medium")
        except Exception as exc:
            return self.failure(str(exc) or "Stooq price failed")
