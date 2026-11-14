"""Check per-seat and service-wide SSE connection caps."""

from ovue.transports.http.limits import RateLimiter, StreamRegistry


def test_stream_registry_enforces_per_seat_and_global_limits() -> None:
    """Reject excess connections and release reservations when streams close."""
    registry = StreamRegistry(per_seat_limit=1, global_limit=2)
    with registry.open("seat_a") as first:
        assert first
        with registry.open("seat_a") as duplicate:
            assert not duplicate
        with registry.open("seat_b") as second:
            assert second
            with registry.open("seat_c") as global_excess:
                assert not global_excess
    with registry.open("seat_a") as released:
        assert released


def test_rate_limiter_returns_retry_seconds_after_the_limit() -> None:
    """Provide a positive retry delay when one request bucket is full."""
    limiter = RateLimiter()
    assert limiter.check("seat_a", maximum=1) is None
    retry = limiter.check("seat_a", maximum=1)
    assert retry is not None
    assert retry > 0


def test_rate_limiter_keeps_source_buckets_bounded() -> None:
    """Route new sources through one fallback bucket after reaching the cap."""
    limiter = RateLimiter(max_buckets=2)
    assert limiter.check("source_a", maximum=1) is None
    assert limiter.check("source_b", maximum=1) is None
    retry = limiter.check("source_c", maximum=1)

    assert retry is None
    assert len(limiter._events) == 2
    assert limiter.check("source_d", maximum=1) is not None
    assert len(limiter._events) == 2
