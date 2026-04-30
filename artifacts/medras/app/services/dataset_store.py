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
from typing import Any, Dict, Optional

import pandas as pd


# Hard cap to protect memory: oldest datasets get evicted past this many.
_MAX_DATASETS = 32
# Soft expiry so abandoned uploads do not pin memory forever (1 hour).
_TTL_SECONDS = 60 * 60


class _Entry:
    __slots__ = ("df", "meta", "created_at")

    def __init__(self, df: pd.DataFrame, meta: Dict[str, Any]) -> None:
        self.df = df
        self.meta = meta
        self.created_at = time.time()


_store: "OrderedDict[str, _Entry]" = OrderedDict()
_lock = Lock()


def _evict_locked() -> None:
    """Drop oldest / expired entries. Caller holds _lock."""
    now = time.time()
    # Expire by age first.
    expired = [k for k, v in _store.items() if now - v.created_at > _TTL_SECONDS]
    for k in expired:
        _store.pop(k, None)
    # Then trim to size cap.
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
    """Fetch the stored entry, or None if missing/expired."""
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            return None
        now = time.time()
        # Enforce TTL on read — abandoned datasets must not linger past
        # _TTL_SECONDS even when no further put() happens to trigger eviction.
        if now - entry.created_at > _TTL_SECONDS:
            _store.pop(job_id, None)
            return None
        # Sliding TTL: touching keeps the dataset alive for another window.
        entry.created_at = now
        # Move to end so LRU eviction works correctly.
        _store.move_to_end(job_id)
        return entry


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
