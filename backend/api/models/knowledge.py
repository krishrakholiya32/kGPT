"""
RAG document knowledge base + cross-conversation semantic memory models for kGPT.

Both `DocumentChunk` and `MemoryEmbedding` store a 384-dim vector (matches
sentence-transformers/all-MiniLM-L6-v2, the embedding model chosen after
benchmarking directly on the Oracle ARM box — see backend/agent/embeddings.py).
"""

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey

from backend.database.db import Base

EMBEDDING_DIM = 384


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="processing")  # processing|ready|failed
    error_message = Column(Text, nullable=True)
    char_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self):
        return f"<Document(id={self.id}, user_id={self.user_id}, filename='{self.filename}', status='{self.status}')>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    # Denormalized so retrieval queries can filter by user_id without a join.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # SET NULL, not CASCADE: memory content is a self-contained string
    # (see retrieval.record_memory), so a memory should survive its source
    # conversation/message being deleted — that's the point of cross-
    # conversation recall. Only the back-reference is cleared.
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


# Pydantic schemas
class DocumentOut(BaseModel):
    id: int
    filename: str
    status: str
    error_message: Optional[str] = None
    chunk_count: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentOut]
