"""
Database Module for kGPT.
"""

import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./database/data.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_conversations() -> None:
    """Add conversation support to an existing database without losing data.

    - Adds chat_messages.conversation_id if missing.
    - Moves each user's existing (unassigned) messages into one 'Imported chat'
      conversation so prior history is preserved.
    Safe to run repeatedly; wrapped by caller so a failure never blocks startup.
    """
    from datetime import datetime, timezone
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    tables = insp.get_table_names()
    if "chat_messages" not in tables:
        return

    cols = [c["name"] for c in insp.get_columns("chat_messages")]
    with engine.begin() as conn:
        if "conversation_id" not in cols:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN conversation_id INTEGER"))

        orphans = conn.execute(
            text("SELECT DISTINCT user_id FROM chat_messages WHERE conversation_id IS NULL")
        ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        for row in orphans:
            uid = row[0]
            res = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, title, created_at, updated_at) "
                    "VALUES (:uid, :title, :now, :now)"
                ),
                {"uid": uid, "title": "Imported chat", "now": now},
            )
            conv_id = res.lastrowid
            conn.execute(
                text(
                    "UPDATE chat_messages SET conversation_id = :cid "
                    "WHERE user_id = :uid AND conversation_id IS NULL"
                ),
                {"cid": conv_id, "uid": uid},
            )


def _migrate_users() -> None:
    """Add email_verified and verification_token columns to existing users tables.

    Existing users default to verified=True so they are not locked out.
    Safe to run repeatedly.
    """
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = [c["name"] for c in insp.get_columns("users")]
    with engine.begin() as conn:
        if "email_verified" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1"
            ))
        if "verification_token" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN verification_token VARCHAR(255)"
            ))


def init_db() -> None:
    from backend.api.models.user import User  # noqa: F401
    from backend.api.models.chat import ChatMessage, Conversation  # noqa: F401

    db_path = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    Base.metadata.create_all(bind=engine)

    try:
        _migrate_conversations()
    except Exception as exc:
        print(f"[kGPT] conversation migration skipped: {exc}")

    try:
        _migrate_users()
    except Exception as exc:
        print(f"[kGPT] user migration skipped: {exc}")