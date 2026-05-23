"""Feedback collection endpoint — stores submissions to data/feedback.ndjson."""

from __future__ import annotations

import datetime
import json
import pathlib
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/feedback", tags=["feedback"])

_DATA_DIR = pathlib.Path(__file__).parent.parent.parent / "data"
_FB_FILE  = _DATA_DIR / "feedback.ndjson"


class FeedbackPayload(BaseModel):
    message: str
    module:  Optional[str] = None
    page:    Optional[str] = None
    email:   Optional[str] = None


@router.post("", summary="Submit user feedback")
async def submit_feedback(payload: FeedbackPayload):
    if not payload.message or not payload.message.strip():
        return {"ok": False, "detail": "Message is empty."}

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts":      datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "module":  (payload.module  or "unknown").strip(),
        "page":    (payload.page    or "").strip(),
        "email":   (payload.email   or "").strip(),
        "message": payload.message.strip(),
    }

    with open(_FB_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"ok": True}
