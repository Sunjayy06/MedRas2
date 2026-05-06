"""Sliding-window in-memory rate limiter — to be used by Step 6 (Generate).

Use as a FastAPI dependency::

    from app.services.rate_limiter import generation_rate_limit

    @router.post("/generate-proposal", dependencies=[Depends(generation_rate_limit)])
    async def generate_proposal(...): ...

The limiter keys requests by client IP. For a single-user development setup
that's sufficient; if/when MedRAS adds real auth, swap the key derivation
for the authenticated user id.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque, Dict

from fastapi import HTTPException, Request

# ---------------------------------------------------------------------------
# Defaults — Step 6 (Generate) will use these.
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_S = 60 * 60          # 1 hour
DEFAULT_MAX_REQUESTS = 3            # 3 generations / hour / user

_buckets: Dict[str, Deque[float]] = {}
_lock = Lock()


def _client_key(request: Request) -> str:
    # Behind a reverse proxy you may want to honour X-Forwarded-For; we
    # intentionally don't here because we have no allow-list of trusted
    # proxies. Direct .host is fine for the current Replit deployment.
    return (request.client.host if request.client else "anonymous") or "anonymous"


def _check(key: str, window_s: int, max_requests: int) -> None:
    now = time.time()
    cutoff = now - window_s
    with _lock:
        bucket = _buckets.setdefault(key, deque())
        # Drop old entries outside the window.
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        # Opportunistic cleanup: keep _buckets from growing without bound
        # by purging any *other* keys whose buckets have fully aged out.
        if len(_buckets) > 256:
            stale = [k for k, b in _buckets.items()
                     if k != key and (not b or b[-1] < cutoff)]
            for k in stale:
                _buckets.pop(k, None)
        if len(bucket) >= max_requests:
            oldest = bucket[0]
            wait_min = max(1, int((oldest + window_s - now) / 60))
            raise HTTPException(
                status_code=429,
                detail=(
                    f"You've reached the limit of {max_requests} generation "
                    f"requests per hour. Please try again in about "
                    f"{wait_min} minute(s)."
                ),
            )
        bucket.append(now)


def make_rate_limit(window_s: int = DEFAULT_WINDOW_S, max_requests: int = DEFAULT_MAX_REQUESTS):
    """Build a FastAPI dependency function with the given limits."""
    def _dep(request: Request) -> None:
        _check(_client_key(request), window_s, max_requests)
    return _dep


# Concrete dependencies most callers can import directly.
generation_rate_limit = make_rate_limit()
