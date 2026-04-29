"""Aggregate API router.

Each module gets its own router file under ``app/api/`` and is mounted here.
This keeps ``main.py`` agnostic to module specifics and makes Phase-2 module
additions a one-line change.
"""

from __future__ import annotations

from fastapi import APIRouter

from .health import router as health_router

router = APIRouter()
router.include_router(health_router, tags=["system"])
