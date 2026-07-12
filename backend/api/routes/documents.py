"""
Document knowledge-base router for kGPT's RAG feature.

Upload once, chunk + embed + store, retrieved by semantic similarity across
any conversation (see backend/agent/retrieval.py for the retrieval side).
Separate from the existing one-off conversation attachments
(backend/api/routes/chat.py's /conversations/{id}/attachment) — that flow is
untouched, this is a new, persistent, cross-conversation knowledge base.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.chunker import chunk_text
from backend.agent.embeddings import embed_texts
from backend.api.auth import get_current_user
from backend.api.models.knowledge import Document, DocumentChunk, DocumentOut, DocumentListResponse
from backend.api.models.user import User
from backend.database.db import get_db, AsyncSessionLocal

documents_router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB — documents can reasonably be bigger than one-off attachments
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".pdf", ".docx", ".txt", ".md"}


async def _process_document(document_id: int, data: bytes, filename: str) -> None:
    """Background task: extract -> chunk -> embed -> store. Runs after the
    upload request has already returned status="processing" to the client."""
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return
        try:
            ext = Path(filename).suffix.lower()
            if ext in (".txt", ".md"):
                text = data.decode("utf-8", errors="replace")
            else:
                from backend.agent.file_extractor import extract_text
                text = await asyncio.to_thread(extract_text, data, filename)

            chunks = chunk_text(text)
            if not chunks:
                doc.status = "failed"
                doc.error_message = "No extractable text content."
                doc.updated_at = datetime.now(timezone.utc)
                await db.commit()
                return

            vectors = await asyncio.to_thread(embed_texts, chunks)

            db.add_all([
                DocumentChunk(
                    document_id=doc.id,
                    user_id=doc.user_id,
                    chunk_index=i,
                    content=chunk,
                    embedding=vector,
                )
                for i, (chunk, vector) in enumerate(zip(chunks, vectors))
            ])

            doc.status = "ready"
            doc.char_count = len(text)
            doc.chunk_count = len(chunks)
            doc.updated_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            doc.status = "failed"
            doc.error_message = str(exc)[:500]
            doc.updated_at = datetime.now(timezone.utc)
            await db.commit()


@documents_router.post("/upload", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: jpg, png, pdf, docx, txt, md.",
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Max 15 MB.")

    doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        status="processing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(_process_document, doc.id, data, file.filename)
    return doc


@documents_router.get("", response_model=DocumentListResponse)
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs = (
        await db.execute(
            select(Document)
            .where(Document.user_id == current_user.id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return DocumentListResponse(documents=list(docs))


@documents_router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = (
        await db.execute(
            select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    await db.delete(doc)
    await db.commit()
    return {"message": "Document deleted"}
