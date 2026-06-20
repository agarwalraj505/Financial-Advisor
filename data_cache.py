"""TTL-aware Supabase cache helpers for the on-demand Market Data Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


TTL_SECONDS = {
    "price": 15 * 60,
    "fx": 12 * 60 * 60,
    "metadata": 7 * 24 * 60 * 60,
    "ter": 30 * 24 * 60 * 60,
    "factsheet": 30 * 24 * 60 * 60,
    "news": 60 * 60,
    "bad_symbol": 7 * 24 * 60 * 60,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def is_stale(timestamp, data_kind: str, now: datetime | None = None) -> bool:
    fetched = parse_timestamp(timestamp)
    if not fetched:
        return True
    ttl = TTL_SECONDS.get(data_kind, 0)
    return (now or utc_now()) - fetched > timedelta(seconds=ttl)


class SupabaseDataCache:
    """Small repository over market_data_cache; safe to replace with Redis later."""

    def __init__(self, gateway, user_id: str):
        self.gateway, self.user_id = gateway, user_id

    def get(self, cache_key: str, data_kind: str | None = None) -> dict | None:
        rows = self.gateway.select("market_data_cache", {"user_id": self.user_id, "cache_key": cache_key})
        if not rows:
            return None
        row = rows[0]
        if data_kind and is_stale(row.get("fetched_at"), data_kind):
            return None
        expires = parse_timestamp(row.get("expires_at"))
        if expires and expires <= utc_now():
            return None
        return row.get("payload") or {}

    def set(self, cache_key: str, payload: Any, provider: str, data_kind: str) -> None:
        now = utc_now(); ttl = TTL_SECONDS[data_kind]
        self.gateway.upsert("market_data_cache", {
            "user_id": self.user_id, "cache_key": cache_key, "provider": provider,
            "data_kind": data_kind, "payload": payload, "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
        }, on_conflict="user_id,cache_key")

