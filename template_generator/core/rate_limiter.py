"""
rate_limiter.py — Token-bucket rate limiter asynchrone.
"""
import asyncio
import time


class AsyncRateLimiter:
    def __init__(self, max_rps: int) -> None:
        if max_rps <= 0:
            raise ValueError(f"max_rps doit être > 0, reçu: {max_rps}")
        self._rate = float(max_rps)
        self._tokens = float(max_rps)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0
