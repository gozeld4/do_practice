from datetime import UTC, datetime

from app.clock import FakeClock
from app.ratelimit import TokenBucket


def test_fresh_bucket_allows_ten_then_denies_eleventh() -> None:
    limiter = TokenBucket(FakeClock(datetime(2026, 1, 1, tzinfo=UTC)))

    results = [limiter.try_acquire(("acme", "user-1")) for _ in range(11)]

    assert all(allowed for allowed, _ in results[:10])
    assert results[10] == (False, 1.0)


def test_refill_allows_five_after_one_second() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    limiter = TokenBucket(clock)

    for _ in range(10):
        assert limiter.try_acquire(("acme", "user-1"))[0]
    assert not limiter.try_acquire(("acme", "user-1"))[0]

    clock.advance(1)
    results = [limiter.try_acquire(("acme", "user-1"))[0] for _ in range(6)]

    assert results == [True, True, True, True, True, False]


def test_different_keys_have_independent_buckets() -> None:
    limiter = TokenBucket(FakeClock(datetime(2026, 1, 1, tzinfo=UTC)))

    for _ in range(10):
        assert limiter.try_acquire(("acme", "user-1"))[0]
    assert not limiter.try_acquire(("acme", "user-1"))[0]
    assert limiter.try_acquire(("acme", "user-2"))[0]
    assert limiter.try_acquire(("globex", "user-1"))[0]