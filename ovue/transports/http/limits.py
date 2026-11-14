"""Bound request rates and the number of open SSE connections."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager


class RateLimiter:
    """Track recent request timestamps for independent rate-limit buckets."""

    def __init__(self, *, max_buckets: int = 10_000) -> None:
        """Start with bounded per-source and per-seat request histories."""
        if max_buckets < 2:
            raise ValueError("At least two rate-limit buckets are required")
        self._max_buckets = max_buckets
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str, *, maximum: int, window_seconds: int = 60) -> int | None:
        """Return retry seconds when a bucket is full, otherwise record the event."""
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                self._remove_expired_buckets(now, window_seconds)
                if len(self._events) >= self._max_buckets:
                    key = "__overflow__"
                    events = self._events.get(key)
                    if events is None:
                        self._events.popitem(last=False)
                        events = deque()
                        self._events[key] = events
                else:
                    events = deque()
                    self._events[key] = events
            self._events.move_to_end(key)
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= maximum:
                return max(1, math.ceil(events[0] + window_seconds - now))
            events.append(now)
        return None

    def _remove_expired_buckets(self, now: float, window_seconds: int) -> None:
        """Drop expired histories before admitting a new source bucket."""
        cutoff = now - window_seconds
        while self._events:
            key, events = next(iter(self._events.items()))
            if events and events[-1] > cutoff:
                break
            del self._events[key]


class StreamRegistry:
    """Enforce per-seat and service-wide limits on concurrent SSE streams."""

    def __init__(self, *, per_seat_limit: int, global_limit: int) -> None:
        """Set finite limits for active stream handlers."""
        self._per_seat_limit = per_seat_limit
        self._global_limit = global_limit
        self._counts: dict[str, int] = defaultdict(int)
        self._total = 0
        self._lock = threading.Lock()

    @contextmanager
    def open(self, seat_id: str) -> Iterator[bool]:
        """Reserve a stream slot until its handler exits."""
        with self._lock:
            accepted = (
                self._total < self._global_limit
                and self._counts[seat_id] < self._per_seat_limit
            )
            if accepted:
                self._total += 1
                self._counts[seat_id] += 1
        try:
            yield accepted
        finally:
            if accepted:
                with self._lock:
                    self._total -= 1
                    self._counts[seat_id] -= 1
                    if self._counts[seat_id] == 0:
                        del self._counts[seat_id]
