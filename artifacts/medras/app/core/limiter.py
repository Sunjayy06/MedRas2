"""Shared rate-limiter instance.

Uses the request's client IP as the rate-limit key. Per-route limits are
attached as decorators in the individual router modules.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
