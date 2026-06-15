"""
FastAPI application entry-point for kGPT.

- Registers CORS middleware (configurable via ALLOWED_ORIGINS env var).
- Runs DB init and ensures required directories on startup (via lifespan).
- Mounts the frontend SPA as static files at the root.
- Includes all API routers.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database.db import init_db
from backend.api.auth import auth_router
from backend.api.routes.chat import chat_router
from backend.api.routes.documents import documents_router
from backend.api.routes.dashboard import dashboard_router

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

LLM_MODE: str = os.getenv("LLM_MODE", "online")

UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./documents")
VECTORSTORE_DIR: str = os.getenv("VECTORSTORE_DIR", "./vectorstore")
DATABASE_DIR: str = os.getenv("DATABASE_DIR", "./database")

# CORS: comma-separated list of allowed origins.
# Use "*" for local development; set your frontend URL in production.
# Example: https://your-kgpt.netlify.app
_raw_origins: str = os.getenv("ALLOWED_ORIGINS", "*")
ALLOW_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]


# ---------------------------------------------------------------------------
# Lifespan: initialise DB and ensure required directories on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database tables
    init_db()

    # Ensure upload / vectorstore / database dirs exist
    for directory in (UPLOAD_DIR, VECTORSTORE_DIR, DATABASE_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)

    yield


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="kGPT API",
    description="Private AI assistant with RAG, web search, SQL, and code execution.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
#
# The frontend is served by FastAPI itself (same origin), so CORS is only
# relevant if you host the frontend separately (e.g. Netlify).
# Set ALLOWED_ORIGINS in your .env or deployment env vars to lock it down.
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
app.include_router(dashboard_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["health"])
async def health_check():
    """Simple health check returning service status, LLM mode, and active provider."""
    from backend.agent.llm import resolve_provider

    return {"status": "healthy", "mode": LLM_MODE, "provider": resolve_provider()}


# ---------------------------------------------------------------------------
# Frontend static files (SPA) — must come LAST so it doesn't shadow API routes
# ---------------------------------------------------------------------------

frontend_path = Path(__file__).parent.parent.parent / "frontend"

if frontend_path.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(frontend_path), html=True),
        name="frontend",
    )
