"""In-memory conversation session manager for Study Builder.

Sessions survive 30 minutes of inactivity. Up to 6 turns are stored;
the last 3 are injected into synthesis context so follow-up questions work.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Optional

log = logging.getLogger(__name__)

_SESSION_TTL: int = 1800        # 30 minutes inactivity → purge
_MAX_TURNS: int = 6             # turns stored per session
_HISTORY_FOR_CONTEXT: int = 3   # turns injected into synthesis prompt

_sessions: dict[str, dict] = {}
_lock = threading.Lock()


def _cleanup_loop() -> None:
    """Background daemon — purges inactive sessions every 5 minutes."""
    while True:
        time.sleep(300)
        now = time.time()
        with _lock:
            expired = [
                sid for sid, s in _sessions.items()
                if now - s["last_active"] > _SESSION_TTL
            ]
            for sid in expired:
                del _sessions[sid]
            if expired:
                log.debug("Purged %d expired session(s)", len(expired))


threading.Thread(
    target=_cleanup_loop, daemon=True, name="sb-session-cleanup"
).start()


def get_or_create(session_id: Optional[str]) -> tuple[str, list[dict]]:
    """Return *(session_id, recent_history)*.

    Creates a new session when *session_id* is ``None`` or unknown.
    *recent_history* contains the last :data:`_HISTORY_FOR_CONTEXT` turns,
    each a dict with keys ``question`` and ``answer_summary``.
    """
    now = time.time()
    with _lock:
        if session_id and session_id in _sessions:
            sess = _sessions[session_id]
            sess["last_active"] = now
            return session_id, list(sess["turns"][-_HISTORY_FOR_CONTEXT:])
        new_id = str(uuid.uuid4())
        _sessions[new_id] = {"turns": [], "last_active": now}
        log.debug("New session %s created", new_id)
        return new_id, []


def add_turn(session_id: str, question: str, answer_summary: str) -> None:
    """Append a completed turn and trim history to :data:`_MAX_TURNS`."""
    with _lock:
        if session_id not in _sessions:
            return
        sess = _sessions[session_id]
        sess["turns"].append(
            {"question": question, "answer_summary": answer_summary}
        )
        if len(sess["turns"]) > _MAX_TURNS:
            sess["turns"] = sess["turns"][-_MAX_TURNS:]
        sess["last_active"] = time.time()
