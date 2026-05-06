"""Aggregate API router.

Each module gets its own router file under ``app/api/`` and is mounted here.
This keeps ``main.py`` agnostic to module specifics and makes Phase-2 module
additions a one-line change.
"""

from __future__ import annotations

from fastapi import APIRouter

from .health import router as health_router
from .outline import router as outline_router
from .plagiarism import router as plagiarism_router
from .practice import router as practice_router
from .references import router as references_router
from .sample_size import router as sample_size_router
from .stats import router as stats_router

router = APIRouter()
router.include_router(health_router, tags=["system"])
router.include_router(sample_size_router)
router.include_router(stats_router)
router.include_router(practice_router)
router.include_router(plagiarism_router)
router.include_router(outline_router)
router.include_router(references_router)
