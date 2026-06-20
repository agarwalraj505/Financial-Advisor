"""Coverage metrics and chunked, partial-save deep enrichment."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
import time
from queue import Empty, Queue

import pandas as pd

from data_cache import is_stale
from data_gap_report import generate_data_gap_report


def _present(value) -> bool:
    if value is None or value is False: return False
    try:
        if bool(pd.isna(value)): return False
    except (TypeError, ValueError): return True
    return str(value).strip() != ""


def _number(value) -> float:
    try: return 0.0 if pd.isna(value) else float(value or 0)
    except (TypeError, ValueError): return 0.0


def _verified_cost(asset) -> bool:
    if _present(asset.get("ter_pct")) or "verified cost" in str(asset.get("notes", "")).lower():
        return True
    suggestions = asset.get("enrichment_suggestions") or {}
    suggestion = suggestions.get("ter_pct", {}) if isinstance(suggestions, dict) else {}
    return suggestion.get("value") is not None and suggestion.get("confidence") == "High"


def calculate_data_coverage(holdings: pd.DataFrame, candidates: pd.DataFrame,
                            news_items=None) -> dict:
    combined = pd.concat([holdings.assign(_candidate=False), candidates.assign(_candidate=True)], ignore_index=True, sort=False)
    total = len(combined)
    if total == 0:
        return {key: 0.0 for key in ("price_coverage", "symbol_coverage", "metadata_coverage", "ter_coverage", "fx_coverage",
                                      "factsheet_coverage", "news_coverage", "recommendation_ready", "valuation_ready")} | {"total_assets": 0}
    def pct(mask): return round(float(pd.Series(mask).fillna(False).mean() * 100), 1)
    prices = combined.apply(lambda a: any(_number(a.get(field)) > 0 for field in
                            ("live_current_price", "current_price_eur", "manual_current_price", "latest_price")), axis=1)
    symbols = combined.apply(lambda a: str(a.get("asset_type", "")).lower() == "cash" or
                             _present(a.get("resolved_price_symbol") or a.get("price_symbol")), axis=1)
    metadata = combined.apply(lambda a: _present(a.get("category")) and _present(a.get("asset_type")), axis=1)
    asset_types = combined.get("asset_type", pd.Series("", index=combined.index))
    funds = combined[asset_types.isin(["ETF", "ETC", "ETP"])]
    ter = 100.0 if funds.empty else pct(funds.apply(_verified_cost, axis=1))
    fx = combined.apply(lambda a: str(a.get("currency", "EUR") or "EUR") == "EUR" or _number(a.get("fx_rate_to_eur")) > 0, axis=1)
    factsheet_funds = funds.get("factsheet_url", pd.Series(False, index=funds.index)).apply(_present)
    factsheet = 100.0 if funds.empty else pct(factsheet_funds)
    news_count = len(news_items) if news_items is not None else 0
    return {"total_assets": total, "price_coverage": pct(prices), "symbol_coverage": pct(symbols),
            "metadata_coverage": pct(metadata),
            "ter_coverage": ter, "fx_coverage": pct(fx), "factsheet_coverage": factsheet,
            "news_coverage": 100.0 if news_count else 0.0,
            "recommendation_ready": pct(combined.get("recommendation_ready", pd.Series(False, index=combined.index))),
            "valuation_ready": pct(combined.get("valuation_ready", pd.Series(False, index=combined.index)))}


def asset_is_fresh_and_complete(asset: dict, is_candidate: bool, now=None) -> bool:
    ready = bool(asset.get("recommendation_ready" if is_candidate else "valuation_ready", False))
    price_fresh = not is_stale(asset.get("last_updated"), "price", now)
    metadata_fresh = not is_stale(asset.get("last_auto_repair_at"), "metadata", now)
    fund = str(asset.get("asset_type", "")) in {"ETF", "ETC", "ETP"}
    fund_fresh = (not fund or (asset.get("ter_pct") and
                  (bool(asset.get("confirmed_by_user")) or not is_stale(asset.get("web_scrape_last_run"), "ter", now))))
    return ready and price_fresh and metadata_fresh and bool(fund_fresh)


def repair_missing_symbols(assets: list[dict], resolver, max_workers: int = 4,
                           progress_callback=None) -> list[dict]:
    """Resolve missing symbols and entered symbols already proven bad."""
    missing = []
    for asset in assets:
        current = str(asset.get("resolved_price_symbol") or asset.get("price_symbol") or "").strip()
        cached = resolver.load_cached_symbol_resolution(str(asset.get("id") or asset.get("isin") or
                                                            asset.get("wkn") or asset.get("instrument") or "")) or {}
        bad = cached.get("bad_symbols") or {}
        recently_bad = current in bad and resolver._bad_is_fresh(bad[current])
        if not current or recently_bad:
            missing.append(asset)
    results = []
    with ThreadPoolExecutor(max_workers=min(4, max(1, max_workers))) as executor:
        futures = {executor.submit(resolver.resolve_price_symbol, asset): asset for asset in missing}
        for future in as_completed(futures):
            asset = futures[future]
            if progress_callback: progress_callback({"asset": asset.get("instrument", ""), "provider": "Symbol resolver", "status": "Running"})
            try:
                resolution = future.result(); results.append({"asset": asset, "resolution": resolution})
                if progress_callback: progress_callback({"asset": asset.get("instrument", ""), "provider": resolution.get("source", "Resolver"),
                                                         "status": "Done" if resolution.get("chosen_symbol") else "Warning"})
            except Exception as exc:
                results.append({"asset": asset, "resolution": {"chosen_symbol": "", "error": str(exc)}})
                if progress_callback: progress_callback({"asset": asset.get("instrument", ""), "provider": "Symbol resolver", "status": "Failed"})
    return results


class DeepScanEngine:
    def __init__(self, enrichment_engine, symbol_resolver=None, max_workers: int = 4,
                 max_asset_seconds: int = 45, news_fetcher=None):
        self.enrichment_engine = enrichment_engine; self.symbol_resolver = symbol_resolver
        self.max_workers = min(4, max(1, int(max_workers))); self.max_asset_seconds = max_asset_seconds
        self.news_fetcher = news_fetcher; self.events = Queue()
        if hasattr(self.enrichment_engine, "event_sink"):
            self.enrichment_engine.event_sink = self.events.put

    def _flush_events(self, progress_callback) -> None:
        if not progress_callback: return
        while True:
            try: progress_callback(self.events.get_nowait())
            except Empty: return

    def run_chunk(self, holdings: pd.DataFrame, candidates: pd.DataFrame, max_assets: int = 5,
                  completed_keys: set[str] | None = None, progress_callback=None,
                  partial_save_callback=None) -> dict:
        completed = set(completed_keys or set()); queue = []
        for frame, candidate in ((holdings, False), (candidates, True)):
            for _, row in frame.iterrows():
                asset = row.to_dict(); key = str(asset.get("isin") or asset.get("instrument"))
                if key in completed or asset_is_fresh_and_complete(asset, candidate): continue
                queue.append((key, asset, candidate))
        selected = queue[:max(1, int(max_assets))]; results, warnings = [], []
        def work(item):
            key, asset, candidate = item; started = time.monotonic(); resolution = None
            if self.symbol_resolver and not asset.get("price_symbol"):
                resolution = self.symbol_resolver.resolve_price_symbol(asset)
                if resolution.get("chosen_symbol"): asset["price_symbol"] = resolution["chosen_symbol"]
            enriched = self.enrichment_engine.enrich_asset(asset, candidate, force_web=True)
            news_items = []
            if self.news_fetcher and enriched.get("price_symbol"):
                try: news_items = self.news_fetcher(enriched) or []
                except Exception: news_items = []
            return key, candidate, enriched, time.monotonic() - started, resolution, news_items
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        futures = {executor.submit(work, item): item for item in selected}
        try:
            # A whole chunk gets the same ceiling as one asset. This keeps a slow
            # provider from holding the Streamlit request open indefinitely.
            deadline = time.monotonic() + self.max_asset_seconds
            unfinished = set(futures)
            for future, item in futures.items():
                if progress_callback:
                    progress_callback({"asset": item[1].get("instrument", item[0]),
                                       "provider": "Market Data Engine", "status": "Queued"})
            while unfinished and time.monotonic() < deadline:
                done, unfinished = wait(unfinished, timeout=min(.5, max(0, deadline - time.monotonic())),
                                        return_when=FIRST_COMPLETED)
                self._flush_events(progress_callback)
                for future in done:
                    key, original, candidate = futures[future][0], futures[future][1], futures[future][2]
                    try:
                        key, candidate, enriched, elapsed, resolution, news_items = future.result()
                        result = {"asset_key": key, "is_candidate": candidate, "asset": enriched,
                                  "elapsed_seconds": round(elapsed, 2), "symbol_resolution": resolution,
                                  "news_items": news_items}
                        results.append(result); completed.add(key)
                        if partial_save_callback: partial_save_callback(result)
                        if progress_callback: progress_callback({"asset": enriched.get("instrument", key), "provider": enriched.get("data_source", "Waterfall"), "status": "Done", "elapsed": elapsed})
                    except Exception as exc:
                        warnings.append(f"{key}: {exc}")
                        if progress_callback: progress_callback({"asset": original.get("instrument", key), "provider": "Waterfall", "status": "Failed", "error": str(exc)})
            for future in unfinished:
                key, original, _candidate = futures[future][0], futures[future][1], futures[future][2]
                future.cancel()
                warnings.append(f"{key}: exceeded {self.max_asset_seconds}s deep-scan budget")
                if progress_callback:
                    progress_callback({"asset": original.get("instrument", key), "provider": "Waterfall",
                                       "status": "Warning", "error": "Timed out; queued for retry"})
            self._flush_events(progress_callback)
        finally:
            # Running HTTP calls have their own short timeouts. Do not wait for
            # timed-out work before returning cached/partial results to the UI.
            executor.shutdown(wait=False, cancel_futures=True)
        # Timed-out or failed selected assets remain queued for a later,
        # cooldown-aware continuation rather than being reported as complete.
        remaining = max(0, len(queue) - len(results))
        holding_updates = {item["asset_key"]: item["asset"] for item in results if not item["is_candidate"]}
        candidate_updates = {item["asset_key"]: item["asset"] for item in results if item["is_candidate"]}
        def apply_updates(frame, updates):
            return pd.DataFrame([updates.get(str(row.get("isin") or row.get("instrument")), row)
                                 for row in frame.to_dict("records")])
        updated_holdings = apply_updates(holdings, holding_updates)
        updated_candidates = apply_updates(candidates, candidate_updates)
        return {"results": results, "processed": len(results), "remaining": remaining,
                "completed_keys": sorted(completed), "warnings": warnings,
                "gap_report": generate_data_gap_report(updated_holdings, updated_candidates)}
