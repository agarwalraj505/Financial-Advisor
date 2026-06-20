"""Thread-safe provider and per-domain rate limits."""

from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
import time
from urllib.parse import urlparse


class SlidingWindowRateLimiter:
    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max(1, int(max_calls)); self.period = max(.01, float(period_seconds))
        self.calls = deque(); self.lock = Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now); return
                wait = self.period - (now - self.calls[0])
            time.sleep(max(.01, wait))


class DomainRateLimiter:
    def __init__(self, interval_seconds: float = 1.0):
        self.interval = max(0, float(interval_seconds)); self.last_call = defaultdict(float); self.lock = Lock()

    def acquire(self, url: str) -> None:
        domain = urlparse(str(url)).netloc.lower()
        if not domain: return
        with self.lock:
            now = time.monotonic(); wait = self.interval - (now - self.last_call[domain])
        if wait > 0: time.sleep(wait)
        with self.lock: self.last_call[domain] = time.monotonic()


OPENFIGI_LIMITER = SlidingWindowRateLimiter(20, 60)
WEB_DOMAIN_LIMITER = DomainRateLimiter(1.0)

