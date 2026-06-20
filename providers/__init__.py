"""Free-first market-data provider adapters."""

from providers.alpha_vantage_provider import AlphaVantageProvider
from providers.coingecko_provider import CoinGeckoProvider
from providers.ecb_provider import ECBProvider
from providers.fmp_provider import FMPProvider
from providers.openfigi_provider import OpenFIGIProvider
from providers.stooq_provider import StooqProvider
from providers.twelvedata_provider import TwelveDataProvider
from providers.web_price_provider import WebPriceProvider
from providers.yfinance_provider import YFinanceProvider

__all__ = ["AlphaVantageProvider", "YFinanceProvider", "OpenFIGIProvider", "ECBProvider", "CoinGeckoProvider",
           "StooqProvider", "FMPProvider", "TwelveDataProvider"]
__all__.append("WebPriceProvider")
