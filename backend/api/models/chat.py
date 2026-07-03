"""
Chat Models & Schemas for kGPT.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey

from backend.database.db import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    mode = Column(String(50), nullable=False, default="general")
    sources = Column(Text, nullable=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def get_sources_list(self) -> List[str]:
        if self.sources:
            try:
                return json.loads(self.sources)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def __repr__(self):
        return f"<ChatMessage(id={self.id}, user_id={self.user_id}, role='{self.role}')>"


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="New chat")
    context = Column(Text, nullable=True)           # legacy — superseded by conversation_attachments
    attachment_name = Column(String(255), nullable=True)  # legacy
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self):
        return f"<Conversation(id={self.id}, user_id={self.user_id}, title='{self.title}')>"


class ConversationAttachment(Base):
    __tablename__ = "conversation_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    context_text = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


# Pydantic Schemas
class ChatRequest(BaseModel):
    message: str = ""
    mode: str = "auto"
    conversation_id: Optional[int] = None


class ChatResponse(BaseModel):
    response: str
    sources: List[str] = []
    mode: str
