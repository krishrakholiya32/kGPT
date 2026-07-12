"""
Semantic retrieval for kGPT's RAG document KB + cross-conversation memory.

Both retrieve_document_context() and retrieve_memory_context() follow the
same shape: embed the query, run a pgvector cosine-distance-ordered query
scoped to the user, drop results past a distance threshold (unlike the
existing file-attachment preamble in chat.py, which injects unconditionally),
and format into a labeled preamble string ready to append into the prompt
alongside the existing history/attachment parts.
"""

import asyncio
import os

from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.embeddings import embed_query
from backend.api.models.knowledge import Document, DocumentChunk, MemoryEmbedding

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.6"))
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "5"))
MEMORY_MAX_DISTANCE = float(os.getenv("MEMORY_MAX_DISTANCE", "0.6"))


async def retrieve_document_context(
    db: AsyncSession, user_id: int, query: str, conversation_id: int | None = None
) -> tuple[str, list[str]]:
    """Returns (preamble_text, source_filenames). preamble_text is '' if
    nothing relevant was found (distance threshold not met).

    Scoping: sees this conversation's own chat-scoped documents PLUS every
    global document (Document.conversation_id IS NULL) — never another
    conversation's scoped documents."""
    if not query or not query.strip():
        return "", []

    qvec = await asyncio.to_thread(embed_query, query)

    distance = DocumentChunk.embedding.cosine_distance(qvec)
    rows = (
        await db.execute(
            select(DocumentChunk.content, Document.filename, distance.label("distance"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.user_id == user_id,
                Document.status == "ready",
                (Document.conversation_id == conversation_id) | (Document.conversation_id.is_(None)),
            )
            .order_by(distance)
            .limit(RAG_TOP_K)
        )
    ).all()

    relevant = [(content, filename) for content, filename, dist in rows if dist <= RAG_MAX_DISTANCE]
    if not relevant:
        return "", []

    parts = [f"[Relevant document: {filename}]\n{content}" for content, filename in relevant]
    sources = sorted({filename for _, filename in relevant})
    return "\n\n".join(parts) + "\n\n", sources


async def retrieve_memory_context(
    db: AsyncSession, user_id: int, query: str, exclude_conversation_id: int | None = None
) -> tuple[str, list[str]]:
    """Cross-conversation semantic memory — deliberately excludes the current
    conversation (already covered by chat.py's own same-conversation recency
    window) so results are genuinely "from elsewhere", not duplicated."""
    if not query or not query.strip():
        return "", []

    qvec = await asyncio.to_thread(embed_query, query)

    distance = MemoryEmbedding.embedding.cosine_distance(qvec)
    conditions = [MemoryEmbedding.user_id == user_id]
    if exclude_conversation_id is not None:
        conditions.append(
            (MemoryEmbedding.conversation_id != exclude_conversation_id)
            | (MemoryEmbedding.conversation_id.is_(None))
        )

    rows = (
        await db.execute(
            select(MemoryEmbedding.content, distance.label("distance"))
            .where(*conditions)
            .order_by(distance)
            .limit(MEMORY_TOP_K)
        )
    ).all()

    relevant = [content for content, dist in rows if dist <= MEMORY_MAX_DISTANCE]
    if not relevant:
        return "", []

    parts = [f"[Relevant memory from a past conversation]\n{content}" for content in relevant]
    return "\n\n".join(parts) + "\n\n", ["Past conversation"]


async def record_memory(user_id: int, conversation_id: int | None, message_id: int | None, content: str) -> None:
    """Fire-and-forget: embed and store one exchange for future cross-conversation
    retrieval. Callers must wrap this in try/except — a failure here must never
    affect the user-facing chat response."""
    from backend.database.db import AsyncSessionLocal

    content = content.strip()
    if not content:
        return
    # Bound embedding compute for pathologically long exchanges.
    content_for_embedding = content[:4000]

    vector = await asyncio.to_thread(embed_query, content_for_embedding)

    async with AsyncSessionLocal() as db:
        db.add(MemoryEmbedding(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            content=content,
            embedding=vector,
        ))
        await db.commit()
