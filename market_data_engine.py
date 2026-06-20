"""Free/no-key market-data waterfall and precise enrichment readiness."""

from __future__ import annotations

from datetime import datetime, timezone
import time

import pandas as pd

from asset_quality import assess_asset_readiness
from enrichment_audit import audit_event
from metadata_enrichment import merge_provider_data, suggested_symbol_candidates
from providers import (CoinGeckoProvider, ECBProvider, FMPProvider, OpenFIGIProvider,
                       StooqProvider, TwelveDataProvider, WebPriceProvider, YFinanceProvider)
from symbol_resolver import SymbolResolver
from web_scraper import scrape_asset_metadata

CRYPTO_SYMBOLS = {"bitcoin": "BTC-EUR", "ethereum": "ETH-EUR", "solana": "SOL-EUR"}


class MarketDataEngine:
    def __init__(self, scraping_enabled: bool = True, rate_limit_seconds: float = .25,
                 retry_queue=None, event_sink=None):
        self.yahoo = YFinanceProvider(); self.openfigi = OpenFIGIProvider()
        self.ecb = ECBProvider(self.yahoo); self.coingecko = CoinGeckoProvider()
        self.fmp = FMPProvider(); self.twelve = TwelveDataProvider()
        self.stooq = StooqProvider(); self.web_price = WebPriceProvider()
        self.symbol_resolver = SymbolResolver(yahoo=self.yahoo, stooq=self.stooq)
        self.retry_queue = retry_queue; self.event_sink = event_sink
        self.scraping_enabled = scraping_enabled
        self.rate_limit_seconds = max(0, float(rate_limit_seconds))
        self.audit: list[dict] = []; self.warnings: list[str] = []

    def provider_status_rows(self, news_enabled: bool = True) -> list[dict]:
        rows = [self.yahoo.status_row("No"),
                self.openfigi.status_row("No, optional key for higher limits"), self.ecb.status_row("No"),
                self.stooq.status_row("No"), self.web_price.status_row("No"),
                self.coingecko.status_row("Optional"), self.fmp.status_row("Optional key"),
                self.twelve.status_row("Optional key")]
        rows += [{"Provider": "Web enrichment", "Purpose": "ETF/fund metadata", "Key required?": "No",
                  "Status": "Enabled" if self.scraping_enabled else "Disabled", "Last success": "", "Last error": ""},
                 {"Provider": "News/RSS", "Purpose": "Market news", "Key required?": "No",
                  "Status": "Enabled" if news_enabled else "Disabled", "Last success": "", "Last error": ""}]
        return rows

    def _record(self, asset, result, action):
        if self.event_sink:
            self.event_sink({"asset": asset.get("instrument") or asset.get("isin", ""),
                             "provider": result.provider, "source": action,
                             "status": "Done" if result.success else "Failed",
                             "error": result.error})
        self.audit.append(audit_event(asset, result.provider, action, result.success,
                                      result.error or str(result.data), confidence=result.confidence))
        if (not result.success and self.retry_queue
                and str(result.error or "") != "Retry cooldown active"):
            error_lower = str(result.error or "").lower()
            error_type = ("Rate limited" if result.status_code == 429 else "Provider timeout"
                          if "timeout" in error_lower or "timed out" in error_lower else "Provider failure")
            self.retry_queue.record_failure(result.provider, asset, action,
                                            error_type,
                                            result.error or "No verified result")
        if result.status_code == 429:
            warning = "OpenFIGI unauthenticated rate limit reached; remaining assets continue through yfinance/web enrichment."
            if warning not in self.warnings: self.warnings.append(warning)

    def _can_try(self, provider: str, asset: dict) -> bool:
        if not self.retry_queue:
            return True
        key = str(asset.get("isin") or asset.get("instrument") or "")
        return self.retry_queue.can_retry(provider, key)

    def _record_scrape_failure(self, asset: dict, scraped: dict) -> None:
        if self.retry_queue and scraped.get("web_scrape_status") != "Success":
            sources = ", ".join(scraped.get("web_scrape_sources") or [])
            self.retry_queue.record_failure("Web enrichment", asset, sources,
                                            "Scraping blocked or unavailable",
                                            "No verified metadata extracted from permitted public sources")

    def _symbol_candidates(self, asset: dict, figi_data: dict | None) -> list[str]:
        candidates = suggested_symbol_candidates(asset, figi_data)
        if str(asset.get("price_symbol", "") or "").strip():
            return list(dict.fromkeys(candidate for candidate in candidates if candidate))[:8]
        query = str(asset.get("isin") or asset.get("instrument") or "")
        if not self._can_try(self.yahoo.name, asset):
            return list(dict.fromkeys(candidate for candidate in candidates if candidate))[:8]
        search = self.yahoo.search(query)
        self._record(asset, search, "symbol search")
        if search.success:
            candidates.extend(match["symbol"] for match in search.data.get("matches", []) if match.get("symbol"))
        name = str(asset.get("instrument", "")).lower()
        for coin, symbol in CRYPTO_SYMBOLS.items():
            if coin in name: candidates.insert(0, symbol)
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))[:8]

    def enrich_asset(self, asset: dict, is_candidate: bool = False, force_web: bool = False) -> dict:
        output = dict(asset); figi_data = None
        if str(output.get("asset_type", "")).lower() == "cash" or str(output.get("isin", "")).upper() == "CASH":
            output.update({"price_source": "User-entered cash balance", "currency": "EUR",
                           "fx_rate_to_eur": 1.0, "valuation_ready": True,
                           "recommendation_ready": False, "valuation_review_reasons": "",
                           "recommendation_review_reasons": "Cash is not a buy/add candidate",
                           "manual_review_attempted": True,
                           "last_auto_repair_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            return output
        isin = str(output.get("isin", "") or "").strip()
        if not isin and output.get("instrument"):
            name_match = (self.openfigi.search_name(str(output["instrument"]))
                          if self._can_try(self.openfigi.name, output)
                          else self.openfigi.failure("Retry cooldown active"))
            self._record(output, name_match, "name search")
            if name_match.success:
                figi_data = name_match.data
                output = merge_provider_data(output, name_match.data, name_match.provider, name_match.confidence, self.audit)
        if not isin and self.scraping_enabled and output.get("instrument"):
            preliminary = scrape_asset_metadata(output)
            self._record_scrape_failure(output, preliminary)
            output.update({key: value for key, value in preliminary.items() if key in
                           {"metadata_conflicts", "enrichment_suggestions", "web_scrape_sources",
                            "web_scrape_confidence", "web_scrape_status", "web_scrape_last_run"}})
            isin_suggestion = (preliminary.get("enrichment_suggestions") or {}).get("isin", {})
            isin = str(isin_suggestion.get("value", "") or "")
            self.audit.append(audit_event(output, "Web enrichment", "name to ISIN search",
                                          bool(isin), "Identifier candidate found" if isin else "No identifier found",
                                          confidence=isin_suggestion.get("confidence", "Low")))
        if isin and isin != "CASH":
            figi = (self.openfigi.map_isin(isin) if self._can_try(self.openfigi.name, output)
                    else self.openfigi.failure("Retry cooldown active"))
            self._record(output, figi, "ISIN mapping")
            if figi.success:
                figi_data = figi.data
                output = merge_provider_data(output, figi.data, figi.provider, figi.confidence, self.audit)
        if not str(output.get("price_symbol", "") or "").strip():
            resolver_asset = {**output, "openfigi_ticker": (figi_data or {}).get("ticker_id", ""),
                              "exchange": (figi_data or {}).get("exchange", output.get("exchange", ""))}
            resolution = self.symbol_resolver.resolve_price_symbol(resolver_asset)
            output["symbol_resolution"] = resolution
            if resolution.get("chosen_symbol"):
                output["resolved_price_symbol"] = resolution["chosen_symbol"]
                if not output.get("price_symbol"): output["price_symbol"] = resolution["chosen_symbol"]
        candidates = self._symbol_candidates(output, figi_data)
        output["suggested_price_symbols"] = candidates
        live = None; selected_symbol = str(output.get("resolved_price_symbol") or output.get("price_symbol") or "")
        ordered_symbols = ([selected_symbol] if selected_symbol else []) + [item for item in candidates if item != selected_symbol]
        if self._can_try(self.yahoo.name, output):
            for symbol in ordered_symbols:
                if not self._can_try(self.yahoo.name, output): break
                result = self.yahoo.get_price(symbol); self._record(output, result, f"price attempt {symbol}")
                if result.success:
                    history = self.yahoo.get_history(symbol, "1mo")
                    self._record(output, history, f"history validation {symbol}")
                    if history.success:
                        live, selected_symbol = result, symbol; break
                time.sleep(self.rate_limit_seconds)
        if not live and self._can_try(self.stooq.name, output):
            for symbol in ordered_symbols[:4]:
                if not self._can_try(self.stooq.name, output): break
                result = self.stooq.get_price(symbol); self._record(output, result, f"Stooq price attempt {symbol}")
                if result.success and result.data.get("history_rows", 0) > 1:
                    live, selected_symbol = result, symbol; break
        if not live and self.scraping_enabled and self._can_try(self.web_price.name, output):
            web_price = self.web_price.get_price(output); self._record(output, web_price, "public product-page price")
            if web_price.success: live = web_price
        if (not live and str(output.get("category", "")).lower() == "crypto"
                and self._can_try(self.coingecko.name, output)):
            coin_id = next((coin for coin in CRYPTO_SYMBOLS if coin in str(output.get("instrument", "")).lower()), "")
            crypto = self.coingecko.get_price_eur(coin_id); self._record(output, crypto, "crypto fallback")
            if crypto.success: live = crypto; selected_symbol = selected_symbol or CRYPTO_SYMBOLS.get(coin_id, "")
        if live:
            if not output.get("price_symbol"): output["price_symbol"] = selected_symbol
            price = live.data["price"]; currency = live.data.get("currency") or output.get("currency") or "EUR"
            output.update({"live_current_price": price, "latest_price": price, "currency": currency,
                           "price_source": "Live market data", "data_source": live.provider,
                           "data_confidence": live.confidence, "last_updated": live.fetched_at})
            if live.data.get("source_url") and not output.get("source_url"):
                output["source_url"] = live.data["source_url"]
            metadata = (self.yahoo.get_metadata(selected_symbol) if self._can_try(self.yahoo.name, output)
                        else self.yahoo.failure("Retry cooldown active"))
            self._record(output, metadata, "quote/fund metadata")
            if metadata.success: output = merge_provider_data(output, metadata.data, metadata.provider, metadata.confidence, self.audit)
        currency = str(output.get("currency", "EUR") or "EUR")
        fx = (self.ecb.get_rate_to_eur(currency) if self._can_try(self.ecb.name, output)
              else self.ecb.failure("Retry cooldown active"))
        self._record(output, fx, "FX conversion")
        if fx.success: output["fx_rate_to_eur"] = fx.data["fx_rate_to_eur"]
        screenshot = float(output.get("current_price_eur", 0) or 0)
        screenshot_evidence = bool(output.get("screenshot_path") or output.get("screenshot_captured_at") or
                                   str(output.get("source", "")).lower().startswith("scalable") or output.get("user_confirmed"))
        manual = float(output.get("manual_current_price", 0) or 0)
        if live:
            selected_price = float(output.get("live_current_price", 0) or output.get("latest_price", 0))
        elif screenshot and screenshot_evidence:
            selected_price = screenshot; output.update({"price_source": "Scalable screenshot", "currency": "EUR", "fx_rate_to_eur": 1.0})
        elif manual:
            selected_price = manual; output["price_source"] = "Manual fallback"
        else:
            selected_price = 0.0; output["price_source"] = "Missing"
        if not is_candidate:
            quantity = float(output.get("quantity", 0) or 0); buy_in = float(output.get("buy_in_value_eur", 0) or 0)
            value = quantity * selected_price * float(output.get("fx_rate_to_eur", 0) or 0)
            output.update({"current_value_eur": round(value, 2), "pl_eur": round(value - buy_in, 2),
                           "pl_pct": round((value - buy_in) / buy_in * 100, 2) if buy_in else 0})
        fund_type = str(output.get("asset_type", "")) in {"ETF", "ETC", "ETP"}
        missing_fund_data = fund_type and (not output.get("ter_pct") or not output.get("fund_size_eur"))
        if self.scraping_enabled and (force_web or missing_fund_data or not output.get("price_symbol")):
            scraped = scrape_asset_metadata(output)
            self._record_scrape_failure(output, scraped)
            output.update({key: value for key, value in scraped.items() if key in
                           {"metadata_conflicts", "enrichment_suggestions", "web_scrape_sources",
                            "web_scrape_confidence", "web_scrape_status", "web_scrape_last_run"}})
            self.audit.append(audit_event(output, "Web enrichment", "safe search/scrape",
                                          scraped.get("web_scrape_status") == "Success",
                                          scraped.get("web_scrape_status", "Failed"),
                                          confidence=scraped.get("web_scrape_confidence", "Low")))
        output["manual_review_attempted"] = True
        output["last_auto_repair_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        output.update(assess_asset_readiness(output, is_candidate))
        output["provider_status"] = self.provider_status_rows()
        output["enrichment_audit"] = [item for item in self.audit if item.get("isin") == output.get("isin")][-20:]
        return output

    def enrich_assets(self, assets: pd.DataFrame, is_candidate: bool = False,
                      force_web: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
        rows = [self.enrich_asset(row.to_dict(), is_candidate, force_web) for _, row in assets.iterrows()]
        return pd.DataFrame(rows), pd.DataFrame(self.audit)
