"""Shared HTTP client for SEC EDGAR.

One place that owns the User-Agent, the rate limit, and retries. Every other
module in this package goes through here, so identification and throttling
cannot drift between call sites.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

import requests

# SEC fair-access policy allows up to 10 requests/second. We stay under it.
MAX_REQUESTS_PER_SECOND = 8

USER_AGENT_ENV = "SEC_USER_AGENT"

_RETRY_STATUS = frozenset({403, 429, 500, 502, 503, 504})


class MissingUserAgent(RuntimeError):
    """Raised when SEC_USER_AGENT is not set."""


def _user_agent() -> str:
    ua = os.environ.get(USER_AGENT_ENV, "").strip()
    if not ua:
        raise MissingUserAgent(
            f"Set {USER_AGENT_ENV} before calling EDGAR. SEC requires a real "
            f"contact address, e.g.\n"
            f'  export {USER_AGENT_ENV}="Your Name your.email@example.com"'
        )
    if "@" not in ua:
        raise MissingUserAgent(
            f"{USER_AGENT_ENV} must contain a contact email address. Got: {ua!r}"
        )
    return ua


class RateLimiter:
    """Sliding-window limiter. Thread-safe."""

    def __init__(self, max_per_second: int = MAX_REQUESTS_PER_SECOND) -> None:
        self.max_per_second = max_per_second
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 1.0:
                    self._calls.popleft()
                if len(self._calls) < self.max_per_second:
                    self._calls.append(now)
                    return
                sleep_for = 1.0 - (now - self._calls[0])
            time.sleep(max(sleep_for, 0.01))


class EdgarClient:
    """Thin wrapper over requests.Session with EDGAR's requirements baked in."""

    def __init__(
        self,
        user_agent: str | None = None,
        max_per_second: int = MAX_REQUESTS_PER_SECOND,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.user_agent = user_agent or _user_agent()
        self.timeout = timeout
        self.max_retries = max_retries
        self._limiter = RateLimiter(max_per_second)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with rate limiting and backoff. Raises on final failure."""
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._limiter.acquire()
            try:
                response = self._session.get(url, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if response.status_code not in _RETRY_STATUS:
                    response.raise_for_status()
                    return response
                last_exc = requests.HTTPError(
                    f"{response.status_code} for {url}", response=response
                )

            if attempt < self.max_retries:
                time.sleep(2**attempt)

        raise last_exc  # type: ignore[misc]

    def get_json(self, url: str, **kwargs) -> dict:
        return self.get(url, **kwargs).json()

    def get_text(self, url: str, **kwargs) -> str:
        return self.get(url, **kwargs).text

    def get_bytes(self, url: str, **kwargs) -> bytes:
        return self.get(url, **kwargs).content

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
