"""In-memory study-proposal store keyed by proposal_id.

The intake screen lets a researcher upload a proposal document (PDF, DOCX,
PPTX, TXT, MD) before the dataset itself exists. We hold the bytes in
process memory, hand back a proposal_id, and the dataset that comes later
references the proposal_id via its `intake.proposal_id` field.

Pass 1 does not actually parse the proposal — that lands in Pass 2 once an
LLM key is available. For now we store the bytes safely with a TTL so the
upload is real (not faked) and Pass 2 can pick it up unchanged.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, Optional, Tuple


# Memory caps. Proposals can be a few MB each; keep a small ring.
_MAX_PROPOSALS = 16
_TTL_SECONDS = 60 * 60  # 1 hour, same as dataset_store


class _Entry:
    __slots__ = ("data", "meta", "created_at")

    def __init__(self, data: bytes, meta: Dict[str, Any]) -> None:
        self.data = data
        self.meta = meta
        self.created_at = time.time()


_store: "OrderedDict[str, _Entry]" = OrderedDict()
_lock = Lock()


def _evict_locked() -> None:
    now = time.time()
    expired = [k for k, v in _store.items() if now - v.created_at > _TTL_SECONDS]
    for k in expired:
        _store.pop(k, None)
    while len(_store) > _MAX_PROPOSALS:
        _store.popitem(last=False)


def put(data: bytes, meta: Dict[str, Any]) -> str:
    proposal_id = uuid.uuid4().hex[:16]
    with _lock:
        _store[proposal_id] = _Entry(data=data, meta=meta)
        _evict_locked()
    return proposal_id


def get(proposal_id: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
    with _lock:
        entry = _store.get(proposal_id)
        if entry is None:
            return None
        now = time.time()
        if now - entry.created_at > _TTL_SECONDS:
            _store.pop(proposal_id, None)
            return None
        entry.created_at = now
        _store.move_to_end(proposal_id)
        return entry.data, entry.meta


def stats() -> Dict[str, int]:
    with _lock:
        return {"proposals": len(_store), "max": _MAX_PROPOSALS}
