"""In-memory dataset store keyed by job_id.

The Statistical Analysis module is stateful: a researcher uploads an Excel
file once, then walks through several screens (classify → clean → assign →
run → results → export). We keep the parsed DataFrame in process memory so
we do not re-parse the Excel on every step.

For Phase 1 this is a simple LRU dict — single-process, single-worker.
When we add proper background jobs / multi-worker deployment we will swap
this for Redis or a tmpfs file cache, but the API surface stays the same.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, List, Optional

import pandas as pd


# Hard cap to protect memory: oldest datasets get evicted past this many.
_MAX_DATASETS = 32
# Sessions are kept for 15 days from the last access (sliding TTL).
_TTL_SECONDS = 15 * 24 * 60 * 60


class _Entry:
    __slots__ = (
        "df", "meta", "created_at",
        "completed_at", "session_title", "variable_count",
    )

    def __init__(self, df: pd.DataFrame, meta: Dict[str, Any]) -> None:
        self.df = df
        self.meta = meta
        self.created_at: float = time.time()
        self.completed_at: Optional[float] = None
        self.session_title: str = ""
        self.variable_count: int = 0


_store: "OrderedDict[str, _Entry]" = OrderedDict()
_lock = Lock()


def _evict_locked() -> None:
    """Drop oldest / expired entries. Caller holds _lock."""
    now = time.time()
    expired = [k for k, v in _store.items() if now - v.created_at > _TTL_SECONDS]
    for k in expired:
        _store.pop(k, None)
    while len(_store) > _MAX_DATASETS:
        _store.popitem(last=False)


def put(df: pd.DataFrame, meta: Dict[str, Any]) -> str:
    """Store a DataFrame and return its job_id."""
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _store[job_id] = _Entry(df=df, meta=meta)
        _evict_locked()
    return job_id


def get(job_id: str) -> Optional[_Entry]:
    """Fetch the stored entry, or None if missing/expired.

    Implements a sliding TTL: every successful read resets the 15-day clock.
    """
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            return None
        now = time.time()
        if now - entry.created_at > _TTL_SECONDS:
            _store.pop(job_id, None)
            return None
        # Sliding TTL: touching keeps the dataset alive for another window.
        entry.created_at = now
        _store.move_to_end(job_id)
        return entry


def touch(job_id: str) -> bool:
    """Reset the sliding TTL without returning the full entry."""
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            return False
        entry.created_at = time.time()
        _store.move_to_end(job_id)
        return True


def mark_completed(job_id: str, title: str, var_count: int) -> bool:
    """Record that an analysis finished; store summary metadata for history."""
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            return False
        entry.completed_at = time.time()
        entry.session_title = title or ""
        entry.variable_count = var_count
        return True


def list_recent(n: int = 5) -> List[Dict[str, Any]]:
    """Return the last *n* completed sessions, most recent first.

    Only returns sessions that are still within the TTL window.
    Does NOT touch/reset any TTL — this is a read-only scan.
    """
    now = time.time()
    with _lock:
        snapshot = [
            (jid, e) for jid, e in _store.items()
            if e.completed_at is not None
            and (now - e.created_at) <= _TTL_SECONDS
        ]
    snapshot.sort(key=lambda x: x[1].completed_at or 0.0, reverse=True)
    result: List[Dict[str, Any]] = []
    for jid, e in snapshot[:n]:
        expiry_secs = _TTL_SECONDS - (now - e.created_at)
        result.append({
            "job_id": jid,
            "title": e.session_title or "Untitled analysis",
            "variable_count": e.variable_count,
            "completed_at": e.completed_at,
            "expires_in_seconds": max(0.0, expiry_secs),
            "expires_in_days": max(0.0, expiry_secs / 86400),
        })
    return result


def update_meta(job_id: str, **fields: Any) -> bool:
    """Merge ``fields`` into the entry's meta dict. Returns False if missing."""
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            return False
        entry.meta.update(fields)
        return True


def replace_df(job_id: str, df: pd.DataFrame) -> bool:
    """Swap the stored DataFrame in place (e.g. after data cleaning)."""
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            return False
        entry.df = df
        return True


def stats() -> Dict[str, int]:
    """Diagnostics for /healthz-style checks."""
    with _lock:
        return {"datasets": len(_store), "max": _MAX_DATASETS}
