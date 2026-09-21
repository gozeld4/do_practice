from collections.abc import Hashable
from math import ceil

from app.clock import Clock, get_clock


class TokenBucket:
    def __init__(self, clock: Clock | None = None, rate: float = 5.0, burst: int = 10) -> None:
        self._clock = clock or get_clock()
        self._rate = rate
        self._burst = burst
        self._buckets: dict[Hashable, tuple[float, float]] = {}

    def try_acquire(self, key: Hashable) -> tuple[bool, float]:
        now = self._clock.now().timestamp()
        tokens, last_refill = self._buckets.get(key, (float(self._burst), now))
        tokens = min(self._burst, tokens + (now - last_refill) * self._rate)

        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True, 0.0

        self._buckets[key] = (tokens, now)
        return False, ceil((1 - tokens) / self._rate)