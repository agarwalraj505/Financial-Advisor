"""Bounded provider-failure retry queue with cooldowns and no infinite loops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock

from data_cache import parse_timestamp


class RetryQueue:
    def __init__(self, repository=None, max_attempts: int = 3, cooldown_minutes: int = 60):
        self.repository = repository; self.max_attempts = max_attempts; self.cooldown = cooldown_minutes
        self.memory: list[dict] = []; self.lock = Lock()

    def record_failure(self, provider: str, asset: dict, attempted_value: str,
                       error_type: str, error_message: str) -> dict:
        key = str(asset.get("isin") or asset.get("instrument") or "")
        with self.lock:
            previous = [item for item in self.memory if item["provider"] == provider and item["asset_key"] == key]
            attempts = max((item.get("attempts", 0) for item in previous), default=0) + 1
            retry_after = datetime.now(timezone.utc) + timedelta(minutes=self.cooldown * min(attempts, 6))
            row = {"provider": provider, "asset_key": key, "isin": asset.get("isin", ""),
                   "attempted_value": attempted_value, "error_type": error_type,
                   "error_message": str(error_message)[:1000], "attempts": attempts,
                   "retry_after": retry_after.isoformat()}
            self.memory.append(row)
        if self.repository:
            try: self.repository.save_provider_failure(row)
            except Exception: pass  # The source waterfall must continue even if failure persistence is unavailable.
        return row

    def can_retry(self, provider: str, asset_key: str, failures: list[dict] | None = None) -> bool:
        rows = failures if failures is not None else list(self.memory)
        matches = [row for row in rows if row.get("provider") == provider and row.get("asset_key") == asset_key]
        if not matches: return True
        latest = max(matches, key=lambda row: str(row.get("created_at") or row.get("retry_after") or ""))
        if int(latest.get("attempts", 1)) >= self.max_attempts: return False
        retry_after = parse_timestamp(latest.get("retry_after"))
        return not retry_after or retry_after <= datetime.now(timezone.utc)

    def due(self, failures: list[dict] | None = None) -> list[dict]:
        rows = failures if failures is not None else self.memory
        return [row for row in rows if self.can_retry(row.get("provider", ""), row.get("asset_key", ""), rows)]
