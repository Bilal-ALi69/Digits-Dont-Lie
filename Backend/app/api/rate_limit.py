"""Per-client request rate limiting.

Analysis is expensive in a way most endpoints are not: a single upload can cost
several seconds of CPU across multiple Tesseract passes. Authentication alone
does not bound that — one valid key can issue requests as fast as the network
allows — so the work itself needs a ceiling.

A sliding window rather than a fixed one: fixed windows let a caller spend the
whole next window's budget the instant the clock ticks over, so a limit of 60/min
permits 120 requests across two adjacent seconds. Counting the trailing window
from *now* has no such edge.

Scope: this counts requests in one process. Behind several workers each keeps its
own tally, so the effective limit multiplies by the worker count. That is the
right trade for a single-instance deployment; a multi-instance one wants the
limit enforced at the reverse proxy, where the whole picture is visible.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """Allows `limit` requests per client within any `window_seconds` period."""

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        # Requests are served on a thread pool, so two can land on the same
        # client at once. Without the lock they can both read a count under the
        # limit and both record a hit, letting the limit be exceeded under
        # exactly the concurrency it exists to control.
        self._lock = threading.Lock()

    @property
    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._hits)

    def check(self, client: str) -> float | None:
        """Record a request. Returns None if allowed, else seconds to wait.

        A refused request is not recorded, so a client hammering a closed door
        cannot push its own retry time further away with every attempt.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            self._evict_idle(cutoff)

            hits = self._hits.setdefault(client, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= self.limit:
                # The oldest hit in the window is the one whose expiry frees a
                # slot, so that is when there is any point coming back.
                return max(0.0, hits[0] - cutoff)

            hits.append(now)
            return None

    def _evict_idle(self, cutoff: float) -> None:
        """Drop clients with nothing left in the window.

        Without this the dict is itself an attack surface: a stream of distinct
        source addresses would grow it without bound. Called under the lock on
        every check, which is cheap because entries are removed as they age
        rather than accumulating until a sweep.
        """
        stale = [c for c, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for c in stale:
            del self._hits[c]


def client_key(request) -> str:
    """Identify the caller for limiting purposes.

    Deliberately ignores X-Forwarded-For: that header is caller-supplied, so
    trusting it lets anyone mint a fresh identity per request and bypass the
    limit entirely. Behind a real proxy this makes every request appear to come
    from the proxy, which is the point at which the proxy should be doing the
    limiting instead.
    """
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"
