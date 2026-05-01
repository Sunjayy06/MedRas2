"""MedRAS — Medical Research Acceleration System.

FastAPI entry point. Serves both the JSON API under ``/api`` and the static
frontend (plain HTML / CSS / JavaScript) for everything else.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# `app.core.config` calls `load_dotenv()` at import time so env vars from a
# project `.env` file are available to every settings field, regardless of
# import order in this entry point.
from app.api import router as api_router
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)

PUBLIC_DIR = Path(__file__).resolve().parent / "public"

app = FastAPI(
    title="MedRAS API",
    version="0.1.0",
    description="Medical Research Acceleration System backend.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    # Credentials default off: a wildcard origin combined with credentials is
    # an unsafe pattern. To enable cookies/auth headers cross-origin, set
    # MEDRAS_CORS_CREDENTIALS=true *and* an explicit MEDRAS_CORS_ORIGINS list
    # (no wildcard).
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


# In development the Replit preview iframe aggressively caches HTML/CSS/JS,
# which makes it look like our fixes aren't landing even after a hard reload.
# When MEDRAS_RELOAD=true (i.e. uvicorn --reload mode), force every response
# to bypass the cache. This middleware is intentionally a no-op in production.
_DEV_NO_CACHE = os.environ.get("MEDRAS_RELOAD", "false").lower() == "true"
if _DEV_NO_CACHE:

    @app.middleware("http")
    async def _no_cache_in_dev(request, call_next):
        response = await call_next(request)
        # Don't touch API responses (they're already fine) — only static UI.
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    """Serve the landing page."""
    index = PUBLIC_DIR / "index.html"
    if not index.exists():
        return JSONResponse({"error": "Landing page missing"}, status_code=500)
    return FileResponse(index)


# Static assets (CSS / JS / images / additional HTML pages).
# Mounted last so explicit routes above take priority.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("MEDRAS_RELOAD", "false").lower() == "true",
    )
