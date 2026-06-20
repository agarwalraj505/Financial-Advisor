"""Free-first market-data provider adapters."""

from providers.coingecko_provider import CoinGeckoProvider
from providers.ecb_provider import ECBProvider
from providers.fmp_provider import FMPProvider
from providers.openfigi_provider import OpenFIGIProvider
from providers.stooq_provider import StooqProvider
from providers.twelvedata_provider import TwelveDataProvider
from providers.yfinance_provider import YFinanceProvider

__all__ = ["YFinanceProvider", "OpenFIGIProvider", "ECBProvider", "CoinGeckoProvider",
           "StooqProvider", "FMPProvider", "TwelveDataProvider"]
