"""In-memory + disk-backed dataset store keyed by job_id.

The Statistical Analysis module is stateful: a researcher uploads an Excel
file once, then walks through several screens (classify → clean → assign →
run → results → export). We keep the parsed DataFrame in process memory so
we do not re-parse the Excel on every step.

Disk persistence (``/tmp/medras_sessions/``) ensures sessions survive server
restarts — critical when uvicorn runs with ``--reload`` during development, or
after a process crash in production.  The disk layer is:

* Written atomically via a ``.tmp`` rename on every mutating call.
* Loaded transparently into the memory LRU on first ``get()`` after restart.
* Evicted from disk alongside the memory entry (TTL / LRU cap).

For multi-worker deployments swap this for Redis or a shared tmpfs; the API
surface is unchanged.
"""

from __future__ import annotations

import os
import pickle
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

# Disk persistence directory — survives server restarts, lost only on full OS
# reboot or explicit cleanup.
_PERSIST_DIR = "/tmp/medras_sessions"


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


# ---------------------------------------------------------------------------
# Disk helpers
# ---------------------------------------------------------------------------

def _ensure_dir() -> bool:
    """Create the persistence dir if absent. Returns True on success."""
    try:
        os.makedirs(_PERSIST_DIR, exist_ok=True)
        return True
    except Exception:
        return False


def _disk_path(job_id: str) -> str:
    return os.path.join(_PERSIST_DIR, f"{job_id}.pkl")


def _save_to_disk(job_id: str, entry: _Entry) -> None:
    """Atomically pickle *entry* to disk.  Silently swallows I/O errors."""
    if not _ensure_dir():
        return
    path = _disk_path(job_id)
    tmp  = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            pickle.dump(entry, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)          # atomic rename — no half-written files
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _load_from_disk(job_id: str) -> Optional[_Entry]:
    """Load a pickled entry from disk.

    Returns ``None`` when the file is absent, corrupt, or beyond the TTL.
    """
    path = _disk_path(job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            entry = pickle.load(f)
        if not isinstance(entry, _Entry):
            return None
        if time.time() - entry.created_at > _TTL_SECONDS:
            _delete_from_disk(job_id)
            return None
        return entry
    except Exception:
        return None


def _delete_from_disk(job_id: str) -> None:
    try:
        os.unlink(_disk_path(job_id))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------

def _evict_locked() -> None:
    """Drop oldest / expired entries from memory (and disk).  Caller holds _lock."""
    now = time.time()
    expired = [k for k, v in _store.items() if now - v.created_at > _TTL_SECONDS]
    for k in expired:
        _store.pop(k, None)
        _delete_from_disk(k)
    while len(_store) > _MAX_DATASETS:
        k, _ = _store.popitem(last=False)
        _delete_from_disk(k)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def put(df: pd.DataFrame, meta: Dict[str, Any]) -> str:
    """Store a DataFrame and return its job_id."""
    job_id = uuid.uuid4().hex[:12]
    entry  = _Entry(df=df, meta=meta)
    with _lock:
        _store[job_id] = entry
        _evict_locked()
    _save_to_disk(job_id, entry)       # outside lock — I/O should not block
    return job_id


def get(job_id: str) -> Optional[_Entry]:
    """Fetch the stored entry, or ``None`` if missing/expired.

    Implements a sliding TTL: every successful read resets the 15-day clock.
    Falls back to the disk cache so sessions survive server restarts.
    """
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            # --- disk fallback (server restart recovery) ---
            disk_entry = _load_from_disk(job_id)
            if disk_entry is None:
                return None
            _store[job_id] = disk_entry
            _evict_locked()
            entry = _store.get(job_id)
            if entry is None:
                return None

        now = time.time()
        if now - entry.created_at > _TTL_SECONDS:
            _store.pop(job_id, None)
            _delete_from_disk(job_id)
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
            disk_entry = _load_from_disk(job_id)
            if disk_entry is None:
                return False
            _store[job_id] = disk_entry
            entry = disk_entry
        entry.created_at = time.time()
        _store.move_to_end(job_id)
    _save_to_disk(job_id, entry)
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
    _save_to_disk(job_id, entry)
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
    _save_to_disk(job_id, entry)
    return True


def replace_df(job_id: str, df: pd.DataFrame) -> bool:
    """Swap the stored DataFrame in place (e.g. after data cleaning)."""
    with _lock:
        entry = _store.get(job_id)
        if entry is None:
            return False
        entry.df = df
    _save_to_disk(job_id, entry)
    return True


def stats() -> Dict[str, int]:
    """Diagnostics for /healthz-style checks."""
    with _lock:
        return {"datasets": len(_store), "max": _MAX_DATASETS}
