"""
Dashboard router for kGPT.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.api.auth import get_current_user
from backend.api.models.chat import ChatMessage
from backend.api.models.user import User, UsageStat
from backend.database.db import get_db

UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./documents")

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@dashboard_router.get("/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id

    total_messages = (
        db.query(func.count(ChatMessage.id))
        .filter(ChatMessage.user_id == user_id)
        .scalar() or 0
    )

    mode_rows = (
        db.query(ChatMessage.mode, func.count(ChatMessage.id))
        .filter(ChatMessage.user_id == user_id)
        .group_by(ChatMessage.mode)
        .all()
    )
    messages_by_mode = {mode: count for mode, count in mode_rows}

    # NOTE: documents are stored in a shared folder (not per-user).
    # The count reflects all uploaded files visible to the RAG pipeline.
    upload_path = Path(UPLOAD_DIR)
    documents_count = (
        sum(
            1
            for f in upload_path.iterdir()
            if f.is_file() and not f.name.startswith(".") and f.name != ".gitkeep"
        )
        if upload_path.exists()
        else 0
    )

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    day_rows = (
        db.query(
            func.date(ChatMessage.timestamp).label("day"),
            func.count(ChatMessage.id),
        )
        .filter(
            ChatMessage.user_id == user_id,
            ChatMessage.timestamp >= seven_days_ago,
        )
        .group_by(func.date(ChatMessage.timestamp))
        .order_by(func.date(ChatMessage.timestamp))
        .all()
    )
    messages_per_day = [{"date": str(day), "count": count} for day, count in day_rows]

    return {
        "username": current_user.username,
        "total_messages": total_messages,
        "messages_by_mode": messages_by_mode,
        "documents_count": documents_count,
        "messages_per_day": messages_per_day,
    }