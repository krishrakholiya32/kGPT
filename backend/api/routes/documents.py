"""
Documents router for kGPT.

Handles file uploads, URL ingestion, and listing of uploaded documents.
All endpoints require authentication.
"""

import os
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.agent.rag import ingest_document, ingest_url
from backend.api.auth import get_current_user
from backend.api.models.user import User
from backend.database.db import get_db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./documents")

# Supported extensions → document type mapping
EXTENSION_TYPE_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".csv": "csv",
    ".txt": "txt",
    ".md": "txt",
    ".json": "txt",
    ".html": "txt",
    ".htm": "txt",
    ".xml": "txt",
    ".yaml": "txt",
    ".yml": "txt",
    ".tsv": "txt",
    ".rtf": "txt",
    ".log": "txt",
    ".ini": "txt",
    ".toml": "txt",
    ".py": "txt",
    ".js": "txt",
    ".ts": "txt",
    ".java": "txt",
    ".c": "txt",
    ".cpp": "txt",
    ".h": "txt",
    ".go": "txt",
    ".rb": "txt",
    ".css": "txt",
    ".sql": "txt",
    ".sh": "txt",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".pptx": "pptx",
}

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class UrlRequest(BaseModel):
    url: str


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    status: str


class UrlResponse(BaseModel):
    url: str
    chunks: int
    status: str


class DocumentInfo(BaseModel):
    filename: str
    size_bytes: int
    modified: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

documents_router = APIRouter(prefix="/api/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# POST /api/documents/upload — upload and ingest a file
# ---------------------------------------------------------------------------


@documents_router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a document, detect its type, ingest it into the vector store."""

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided.",
        )

    # Validate extension
    ext = Path(file.filename).suffix.lower()
    file_type = EXTENSION_TYPE_MAP.get(ext)
    if file_type is None:
        supported = ", ".join(sorted(EXTENSION_TYPE_MAP.keys()))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Supported: {supported}",
        )

    # Ensure upload directory exists
    upload_path = Path(UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)

    # Save file to disk
    file_path = upload_path / file.filename
    try:
        async with aiofiles.open(file_path, "wb") as out_file:
            content = await file.read()
            await out_file.write(content)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {exc}",
        )

    # Ingest into vector store
    try:
        chunks = ingest_document(str(file_path), file_type)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest document: {exc}",
        )

    return UploadResponse(
        filename=file.filename,
        chunks=chunks,
        status="ingested",
    )


# ---------------------------------------------------------------------------
# POST /api/documents/url — ingest from a URL
# ---------------------------------------------------------------------------


@documents_router.post("/url", response_model=UrlResponse)
async def ingest_from_url(
    request: UrlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ingest content from a URL into the vector store."""

    if not request.url or not request.url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid HTTP/HTTPS URL is required.",
        )

    try:
        chunks = ingest_url(request.url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest URL: {exc}",
        )

    return UrlResponse(
        url=request.url,
        chunks=chunks,
        status="ingested",
    )


# ---------------------------------------------------------------------------
# GET /api/documents — list uploaded files
# ---------------------------------------------------------------------------


@documents_router.get("", response_model=list[DocumentInfo])
async def list_documents(
    current_user: User = Depends(get_current_user),
):
    """List all files in the upload directory."""

    upload_path = Path(UPLOAD_DIR)
    if not upload_path.exists():
        return []

    documents: list[DocumentInfo] = []
    for entry in sorted(upload_path.iterdir()):
        if entry.is_file():
            stat = entry.stat()
            documents.append(
                DocumentInfo(
                    filename=entry.name,
                    size_bytes=stat.st_size,
                    modified=str(
                        __import__("datetime").datetime.fromtimestamp(
                            stat.st_mtime,
                            tz=__import__("datetime").timezone.utc,
                        ).isoformat()
                    ),
                )
            )

    return documents