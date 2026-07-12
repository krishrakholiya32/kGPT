"""
Database Module for kGPT.

Async SQLAlchemy against PostgreSQL (asyncpg driver).

Migrated from the previous synchronous SQLite + WAL-mode setup. Postgres handles
concurrent writers natively, so the old ``PRAGMA journal_mode=WAL`` pragma is gone.
The hand-written idempotent migrations are kept but rewritten to run on the async
engine via ``conn.run_sync(...)``; they still run safely on every startup, whether
against a brand-new Postgres database or one that already has the columns/tables.
"""

import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

load_dotenv()

# Default to a local Postgres. asyncpg is the async driver.
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://kgpt:kgpt@localhost:5432/kgpt",
)


def _normalize_async_url(url: str) -> str:
    """Coerce common Postgres URL forms to the asyncpg driver.

    Heroku/Render style ``postgres://`` and plain ``postgresql://`` URLs are
    rewritten to ``postgresql+asyncpg://`` so the async engine can use them.
    """
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalize_async_url(DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
)

# expire_on_commit=False keeps attributes usable after commit without another
# (async) round-trip — matches ClauseGuard's async session pattern.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Backwards-compatible alias: existing call sites used ``SessionLocal()``.
SessionLocal = AsyncSessionLocal

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Idempotent hand-written migrations
#
# On a fresh Postgres database, ``Base.metadata.create_all`` (run first in
# init_db) already creates every table/column from the models, so each of these
# finds the target already present and becomes a no-op. Their real job is
# migrating a pre-existing database that is missing newer columns/tables. Each
# uses ``conn.run_sync`` because SQLAlchemy's ``inspect`` needs a sync-style
# connection, then executes plain DDL that is valid on Postgres.
# ---------------------------------------------------------------------------


async def _migrate_conversations() -> None:
    """Add conversation support to an existing database without losing data.

    - Adds chat_messages.conversation_id if missing.
    - Moves each user's existing (unassigned) messages into one 'Imported chat'
      conversation so prior history is preserved.
    Safe to run repeatedly.
    """
    from datetime import datetime, timezone
    from sqlalchemy import text, inspect

    def _do(conn) -> None:
        insp = inspect(conn)
        tables = insp.get_table_names()
        if "chat_messages" not in tables or "conversations" not in tables:
            return

        cols = [c["name"] for c in insp.get_columns("chat_messages")]
        if "conversation_id" not in cols:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN conversation_id INTEGER"))

        orphans = conn.execute(
            text("SELECT DISTINCT user_id FROM chat_messages WHERE conversation_id IS NULL")
        ).fetchall()
        now = datetime.now(timezone.utc)
        for row in orphans:
            uid = row[0]
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, title, created_at, updated_at) "
                    "VALUES (:uid, :title, :now, :now) RETURNING id"
                ),
                {"uid": uid, "title": "Imported chat", "now": now},
            ).scalar()
            conn.execute(
                text(
                    "UPDATE chat_messages SET conversation_id = :cid "
                    "WHERE user_id = :uid AND conversation_id IS NULL"
                ),
                {"cid": conv_id, "uid": uid},
            )

    async with engine.begin() as conn:
        await conn.run_sync(_do)


async def _migrate_users() -> None:
    """Add email_verified and verification_token columns to existing users tables.

    Existing users default to verified=True so they are not locked out.
    Safe to run repeatedly.
    """
    from sqlalchemy import text, inspect

    def _do(conn) -> None:
        insp = inspect(conn)
        if "users" not in insp.get_table_names():
            return
        cols = [c["name"] for c in insp.get_columns("users")]
        if "email_verified" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE"
            ))
        if "verification_token" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN verification_token VARCHAR(255)"
            ))

    async with engine.begin() as conn:
        await conn.run_sync(_do)


async def _migrate_attachments() -> None:
    """Add legacy context and attachment_name columns to conversations. Safe to run repeatedly."""
    from sqlalchemy import text, inspect

    def _do(conn) -> None:
        insp = inspect(conn)
        if "conversations" not in insp.get_table_names():
            return
        cols = [c["name"] for c in insp.get_columns("conversations")]
        if "context" not in cols:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN context TEXT"))
        if "attachment_name" not in cols:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN attachment_name VARCHAR(255)"))

    async with engine.begin() as conn:
        await conn.run_sync(_do)


async def _migrate_attachment_table() -> None:
    """Create conversation_attachments table and migrate any legacy single-attachment data.

    Safe to run repeatedly.
    """
    from datetime import datetime, timezone
    from sqlalchemy import text, inspect

    def _do(conn) -> None:
        insp = inspect(conn)
        if "conversation_attachments" not in insp.get_table_names():
            conn.execute(text("""
                CREATE TABLE conversation_attachments (
                    id SERIAL PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                    filename VARCHAR(255) NOT NULL,
                    context_text TEXT NOT NULL,
                    uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_conv_att_cid ON conversation_attachments(conversation_id)"
            ))

        # Migrate any legacy rows (conversation.context IS NOT NULL)
        if "conversations" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("conversations")]
            if "context" in cols and "attachment_name" in cols:
                now = datetime.now(timezone.utc)
                rows = conn.execute(text(
                    "SELECT id, attachment_name, context FROM conversations "
                    "WHERE context IS NOT NULL AND attachment_name IS NOT NULL"
                )).fetchall()
                for conv_id, filename, ctx in rows:
                    exists = conn.execute(text(
                        "SELECT 1 FROM conversation_attachments "
                        "WHERE conversation_id=:cid AND filename=:fn LIMIT 1"
                    ), {"cid": conv_id, "fn": filename}).fetchone()
                    if not exists:
                        conn.execute(text(
                            "INSERT INTO conversation_attachments "
                            "(conversation_id, filename, context_text, uploaded_at) "
                            "VALUES (:cid, :fn, :ctx, :now)"
                        ), {"cid": conv_id, "fn": filename, "ctx": ctx, "now": now})
                    conn.execute(text(
                        "UPDATE conversations SET context=NULL, attachment_name=NULL WHERE id=:cid"
                    ), {"cid": conv_id})

    async with engine.begin() as conn:
        await conn.run_sync(_do)


async def _ensure_vector_extension() -> None:
    """Enable the pgvector extension. Must run BEFORE Base.metadata.create_all —
    the Document/DocumentChunk/MemoryEmbedding models declare `vector(384)`
    columns, and create_all will fail on a database that doesn't have the
    `vector` type registered yet. Safe to run repeatedly."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def _migrate_vector_indexes() -> None:
    """Create the HNSW vector-similarity indexes.

    Must run outside any SQLAlchemy transaction — CREATE INDEX CONCURRENTLY
    raises ActiveSqlTransaction if wrapped in one. Uses a raw asyncpg
    connection (autocommit per-statement by default) instead of engine.begin().
    IF NOT EXISTS makes this idempotent on its own.
    """
    import asyncpg

    raw_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(raw_url)
    try:
        await conn.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_doc_chunks_hnsw "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
        )
        await conn.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mem_emb_hnsw "
            "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
        )
    finally:
        await conn.close()


async def init_db() -> None:
    from backend.api.models.user import User  # noqa: F401
    from backend.api.models.chat import ChatMessage, Conversation, ConversationAttachment  # noqa: F401
    from backend.api.models.knowledge import Document, DocumentChunk, MemoryEmbedding  # noqa: F401

    try:
        await _ensure_vector_extension()
    except Exception as exc:
        print(f"[kGPT] vector extension setup failed: {exc}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        await _migrate_conversations()
    except Exception as exc:
        print(f"[kGPT] conversation migration skipped: {exc}")

    try:
        await _migrate_users()
    except Exception as exc:
        print(f"[kGPT] user migration skipped: {exc}")

    try:
        await _migrate_attachments()
    except Exception as exc:
        print(f"[kGPT] attachment migration skipped: {exc}")

    try:
        await _migrate_attachment_table()
    except Exception as exc:
        print(f"[kGPT] attachment-table migration skipped: {exc}")

    try:
        await _migrate_vector_indexes()
    except Exception as exc:
        print(f"[kGPT] vector index migration skipped: {exc}")
