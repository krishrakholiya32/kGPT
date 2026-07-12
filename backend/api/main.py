"""
FastAPI application entry-point for kGPT.

- Registers CORS middleware (configurable via ALLOWED_ORIGINS env var).
- Runs the async DB init on startup (via lifespan).
- Serves the built React SPA (frontend/dist) as static files with a catch-all
  fallback to index.html so client-side routes (/, /login, /verify) resolve.
- Includes all API routers.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database.db import init_db
from backend.api.auth import auth_router
from backend.api.routes.chat import chat_router
from backend.api.routes.documents import documents_router

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

LLM_MODE: str = os.getenv("LLM_MODE", "online")

# CORS: comma-separated list of allowed origins.
# Use "*" for local development; set your frontend URL in production.
_raw_origins: str = os.getenv("ALLOWED_ORIGINS", "*")
ALLOW_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]


# ---------------------------------------------------------------------------
# Lifespan: initialise DB on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="kGPT API",
    description="Private AI assistant with general chat and web search.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["health"])
async def health_check():
    """Simple health check returning service status, LLM mode, and active provider."""
    from backend.agent.llm import candidate_providers

    providers = candidate_providers()
    return {"status": "healthy", "mode": LLM_MODE, "provider": providers[0] if providers else "none"}


# ---------------------------------------------------------------------------
# Frontend static files (React SPA) — must come LAST so it doesn't shadow API routes.
#
# The Vite build outputs to frontend/dist. Hashed assets live under /assets and
# are served directly; every other non-API path falls back to index.html so the
# client-side router (react-router) can resolve /, /login, etc.
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return FileResponse(str(_FRONTEND_DIST / "favicon.svg"), media_type="image/svg+xml")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Serve a real file if it exists (e.g. robots.txt), else the SPA shell.
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
