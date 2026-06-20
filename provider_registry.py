"""Single registry describing free and optional providers, timeouts, and capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from providers.base import read_secret


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    capabilities: tuple[str, ...]
    timeout_seconds: int
    key_name: str = ""
    optional: bool = False

    @property
    def enabled(self) -> bool:
        return not self.key_name or bool(read_secret(self.key_name)) or self.optional


PROVIDERS = (
    ProviderDefinition("Alpha Vantage", ("price", "history", "search", "metadata", "fx"), 8,
                       "ALPHA_VANTAGE_API_KEY"),
    ProviderDefinition("yfinance", ("price", "history", "search", "metadata", "fx", "news"), 8),
    ProviderDefinition("OpenFIGI", ("identifier", "metadata"), 8, "OPENFIGI_API_KEY", True),
    ProviderDefinition("ECB", ("fx",), 8),
    ProviderDefinition("Stooq", ("price", "history"), 8),
    ProviderDefinition("CoinGecko", ("crypto_price",), 8, "COINGECKO_API_KEY", True),
    ProviderDefinition("GDELT", ("news",), 10),
    ProviderDefinition("RSS", ("news",), 10),
    ProviderDefinition("Web enrichment", ("search", "metadata", "factsheet"), 12),
    ProviderDefinition("Web price", ("price",), 12),
    ProviderDefinition("FMP", ("fundamentals",), 8, "FMP_API_KEY", True),
    ProviderDefinition("Twelve Data", ("price",), 8, "TWELVE_DATA_API_KEY", True),
)

PURPOSES = {"Alpha Vantage": "Quotes, symbol search, daily history, ETF profile",
            "yfinance": "Prices/history", "OpenFIGI": "ISIN mapping", "ECB": "FX rates",
            "Stooq": "Quote fallback", "CoinGecko": "Crypto fallback", "GDELT": "Market news",
            "RSS": "Market news", "Web enrichment": "ETF/fund metadata",
            "Web price": "Public product-page price fallback",
            "FMP": "Fundamentals", "Twelve Data": "Backup prices"}


def get_provider_registry() -> list[dict]:
    rows = []
    for provider in PROVIDERS:
        key_present = bool(read_secret(provider.key_name)) if provider.key_name else True
        enabled = True if not provider.key_name or provider.optional else key_present
        if provider.name in {"FMP", "Twelve Data"}: enabled = key_present
        key_label = "Yes" if provider.name == "Alpha Vantage" else "Optional" if provider.key_name else "No"
        rows.append({"Provider": provider.name, "Purpose": PURPOSES.get(provider.name, "Data enrichment"),
                     "Capabilities": ", ".join(provider.capabilities),
                     "Timeout seconds": provider.timeout_seconds, "Key required?": key_label,
                     "Status": "Enabled" if enabled else "Disabled", "Last success": "", "Last error": ""})
    return rows
