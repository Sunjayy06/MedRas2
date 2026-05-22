"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from .folio import router as folio_router
from .health import router as health_router
from .outline import router as outline_router
from .plagiarism import router as plagiarism_router
from .practice import router as practice_router
from .proposal import router as proposal_router
from .references import router as references_router
from .sample_size import router as sample_size_router
from .stats import router as stats_router
from .study_builder import router as study_builder_router
from .study_design import router as study_design_router
from .thesis import router as thesis_router

router = APIRouter()
router.include_router(folio_router)
router.include_router(health_router, tags=["system"])
router.include_router(sample_size_router)
router.include_router(stats_router)
router.include_router(practice_router)
router.include_router(plagiarism_router)
router.include_router(outline_router)
router.include_router(references_router)
router.include_router(proposal_router)
router.include_router(thesis_router)
router.include_router(study_builder_router)
router.include_router(study_design_router)
