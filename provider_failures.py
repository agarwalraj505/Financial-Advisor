"""Provider failure records and cooldown helpers used by enrichment workflows."""

from __future__ import annotations

from datetime import datetime, timezone

from data_cache import parse_timestamp
from retry_queue import RetryQueue


def failure_is_retryable(failure: dict, now: datetime | None = None) -> bool:
    retry_after = parse_timestamp(failure.get("retry_after"))
    return not retry_after or retry_after <= (now or datetime.now(timezone.utc))


def due_provider_failures(failures: list[dict]) -> list[dict]:
    return [dict(item) for item in failures if failure_is_retryable(item)]


__all__ = ["RetryQueue", "failure_is_retryable", "due_provider_failures"]

