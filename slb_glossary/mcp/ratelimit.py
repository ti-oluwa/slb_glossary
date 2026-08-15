"""
Pluggable request-rate limiting for `slb_glossary.mcp`.

`RateLimiter` is deliberately tiny (one method) so it's trivial to back with
whatever you already run - Redis, a token-bucket service, an in-memory
counter. `slb_glossary.mcp` ships one in-memory implementation,
`SlidingWindowRateLimiter`, good enough for a single-process server; swap in
your own via `slb_glossary.mcp.config.RateLimitConfig.limiter` for anything
distributed across multiple server processes.
"""

import asyncio
import collections
import time
import typing

__all__ = ["RateLimiter", "SlidingWindowRateLimiter", "RateLimitExceeded"]


class RateLimitExceeded(Exception):
    """Raised internally when a rate-limit key has no requests left in its window."""

    def __init__(self, key: str, *, retry_after: float | None = None) -> None:
        message = f"Rate limit exceeded for {key!r}"
        if retry_after is not None:
            message += f"; retry after {retry_after:.1f}s"
        super().__init__(message)
        self.key = key
        self.retry_after = retry_after


@typing.runtime_checkable
class RateLimiter(typing.Protocol):
    """Protocol for a request-rate limiter, consulted once per tool call."""

    async def acquire(self, key: str) -> bool:
        """
        Register one request against `key` and report whether it's allowed.

        :param key: The rate-limit key for this call - shaped by
            `slb_glossary.mcp.config.RateLimitScope` (e.g. `\"alice:glossary_search\"`).
        :return: `True` if the request is allowed to proceed, `False` if
            `key` has exhausted its quota for the current window.
        """
        ...


class SlidingWindowRateLimiter:
    """
    An in-memory, per-key sliding-window `RateLimiter`.

    Tracks each key's recent request timestamps in a deque; a request is
    allowed if fewer than `limit` timestamps remain within the trailing
    `window_seconds`. Process-local only - fine for a single server
    process, not for a rate limit shared across replicas.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        """
        :param limit: Maximum requests allowed per key within any trailing
            `window_seconds` interval.
        :param window_seconds: Size of the sliding window, in seconds.
        """
        if limit <= 0:
            raise ValueError("`limit` must be positive.")
        if window_seconds <= 0:
            raise ValueError("`window_seconds` must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, collections.deque[float]] = collections.defaultdict(
            collections.deque
        )
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def __repr__(self) -> str:
        return f"{type(self).__name__}(limit={self.limit}, window_seconds={self.window_seconds})"
