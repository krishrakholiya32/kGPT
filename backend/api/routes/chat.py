"""
Chat router for kGPT.
Supports: general and web modes (auto-routed).

Converted to async SQLAlchemy (AsyncSession / select / await) and the async,
httpx-based LLM client. The SSE event shape is unchanged:
{"type":"meta",...} -> {"type":"chunk","text":...} -> {"type":"done"} / {"type":"error",...}.
"""

import asyncio
import json
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from fastapi import APIRouter, Depends, HTTPException, Body, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent import retrieval
from backend.agent.llm import build_llm, candidate_providers
from backend.agent.tools import run_web_search
from backend.api.auth import get_current_user
from backend.api.models.chat import ChatMessage, ChatRequest, ChatResponse, Conversation, ConversationAttachment
from backend.api.models.user import User
from backend.database.db import get_db, AsyncSessionLocal

chat_router = APIRouter(prefix="/api/chat", tags=["chat"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS = 10
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".pdf", ".docx"}

_RPM_LIMIT = 20        # max user messages per minute
_WEEKLY_LIMIT = 1000   # max user messages per 7 days
_rpm_buckets: dict[int, list[float]] = defaultdict(list)
_rpm_lock = threading.Lock()

_CLASSIFY_SYSTEM = (
    "You are a routing classification agent for an AI assistant.\n"
    "Analyze the user's message and decide whether it needs a live web search.\n\n"
    "- 'web': Select this if the user is asking for real-time information, recent news, "
    "current weather, stock prices today, sports scores, live info, or anything that "
    "requires searching the web. Example queries: 'What is the latest AI news?', "
    "'search the web for x', 'weather today in New York'.\n"
    "- 'general': Select this for everything else - greetings, conversational banter, "
    "general facts, coding help, real-world counting/estimate questions, or anything "
    "that doesn't need live search. Example queries: 'hi', 'how are you?', "
    "'tell me a joke', 'what is the capital of France?', 'how many scientists are there'.\n\n"
    "Constraint: reply with exactly one word: 'web' or 'general'. No explanations, "
    "markdown, code blocks, punctuation, or extra words."
)


async def _check_rate_limits(user_id: int, db: AsyncSession) -> None:
    now = time.monotonic()
    with _rpm_lock:
        bucket = [t for t in _rpm_buckets[user_id] if now - t < 60]
        if len(bucket) >= _RPM_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many messages — please wait a moment before sending again.",
            )
        bucket.append(now)
        _rpm_buckets[user_id] = bucket

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    weekly = (
        await db.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.timestamp >= week_ago,
            )
        )
    ).scalar() or 0
    if weekly >= _WEEKLY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Weekly limit of {_WEEKLY_LIMIT} messages reached. Resets after 7 days.",
        )


async def classify_query(query: str, llm) -> str:
    """Classify the user message as 'general' or 'web' (needs live web search)."""
    try:
        category = (await llm.ainvoke(query, system=_CLASSIFY_SYSTEM)).strip().lower()
        for cat in ["web", "general"]:
            if cat in category:
                return cat
        return "general"
    except Exception:
        return "general"


def _save_message(db, user_id, role, content, mode, conversation_id=None, sources=None):
    msg = ChatMessage(
        user_id=user_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        mode=mode,
        sources=json.dumps(sources) if sources else None,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(msg)
    return msg


async def _resolve_conversation(db, user_id, conversation_id, first_message=""):
    """Return the Conversation to use, creating one if needed.

    - Explicit valid id -> that conversation.
    - No id (legacy / first load) -> most recent conversation, else a new one.
    """
    conv = None
    if conversation_id:
        conv = (
            await db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
    if conv is None and not conversation_id:
        conv = (
            await db.execute(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
            )
        ).scalars().first()
    if conv is None:
        title = (first_message or "New chat").strip()[:60] or "New chat"
        conv = Conversation(user_id=user_id, title=title)
        db.add(conv)
        await db.flush()

    # Give a freshly-created chat a real title from its first message.
    fm = (first_message or "").strip()
    if conv is not None and fm and conv.title == "New chat":
        conv.title = fm[:60]

    return conv


async def _history_text_from_db(db, user_id, conversation_id, limit=10) -> str:
    """Load recent conversation history directly from DB — works across workers and restarts."""
    msgs = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id, ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.timestamp.desc())
            .limit(limit * 2)
        )
    ).scalars().all()
    msgs = list(reversed(msgs))
    lines = ""
    for msg in msgs:
        role = "User" if msg.role == "user" else "Assistant"
        lines += f"{role}: {msg.content}\n"
    return lines


async def _file_context_preamble(db, conv_id: int) -> str:
    """Return a formatted preamble with all attached file contexts for this conversation, or ''."""
    atts = (
        await db.execute(
            select(ConversationAttachment)
            .where(ConversationAttachment.conversation_id == conv_id)
            .order_by(ConversationAttachment.uploaded_at.asc())
        )
    ).scalars().all()
    if atts:
        parts = [f"[Attached file: {a.filename}]\n{a.context_text}" for a in atts]
        return "\n\n".join(parts) + "\n\n"
    # Legacy fallback for old single-attachment rows
    conv = (
        await db.execute(select(Conversation).where(Conversation.id == conv_id))
    ).scalar_one_or_none()
    if conv and conv.context:
        name = conv.attachment_name or "attached file"
        return f"[Attached file: {name}]\n{conv.context}\n\n"
    return ""


async def _resolve_search_query(llm, user_message, history_text):
    """If the message is a short follow-up, expand it into a self-contained search query."""
    if not history_text or len(user_message.split()) > 6:
        return user_message
    prompt = (
        f"Given this conversation history:\n{history_text}\n"
        f"The user just said: \"{user_message}\"\n"
        f"Rewrite their message as a single, self-contained web search query "
        f"(no explanation, just the query):"
    )
    query = await llm.ainvoke(prompt)
    return query.strip().strip('"')


async def _run_mode(llm, mode, user_message, db, user_id, conv_id):
    """Execute a single mode with the given LLM. Returns (response_text, sources)."""
    history_text = await _history_text_from_db(db, user_id, conv_id)
    ctx = await _file_context_preamble(db, conv_id)
    doc_ctx, doc_sources = await retrieval.retrieve_document_context(db, user_id, user_message, conv_id)
    mem_ctx, mem_sources = await retrieval.retrieve_memory_context(db, user_id, user_message, conv_id)
    sources = doc_sources + mem_sources

    if mode == "general":
        parts = []
        if doc_ctx:
            parts.append(doc_ctx)
        if mem_ctx:
            parts.append(mem_ctx)
        if ctx:
            parts.append(ctx)
        if history_text:
            parts.append(f"Previous conversation:\n{history_text}")
        parts.append(f"User: {user_message}\nAssistant:")
        return await llm.ainvoke("\n".join(parts)), sources

    if mode == "web":
        search_query = await _resolve_search_query(llm, user_message, history_text)
        search_results = await asyncio.to_thread(run_web_search, search_query)
        summary_prompt = (
            (doc_ctx if doc_ctx else "") +
            (mem_ctx if mem_ctx else "") +
            (ctx if ctx else "") +
            (f"Previous conversation:\n{history_text}\n" if history_text else "") +
            f"Based on the following web search results, answer the user's question: '{user_message}'\n\n"
            f"Search Results:\n{search_results}\n\nAnswer:"
        )
        return await llm.ainvoke(summary_prompt), sources

    return f"Unknown mode '{mode}'. Supported: general, web.", []


async def _build_stream_prompt(mode, user_message, db, user_id, conv_id):
    """Return (prompt_or_tuple, sources) for the given mode (general or web).
    prompt_or_tuple is None if mode is unrecognized; for web mode it's a
    ("__web__", ...) tuple the caller finishes building after a web search."""
    history_text = await _history_text_from_db(db, user_id, conv_id)
    ctx = await _file_context_preamble(db, conv_id)
    doc_ctx, doc_sources = await retrieval.retrieve_document_context(db, user_id, user_message, conv_id)
    mem_ctx, mem_sources = await retrieval.retrieve_memory_context(db, user_id, user_message, conv_id)
    sources = doc_sources + mem_sources

    if mode == "general":
        parts = []
        if doc_ctx:
            parts.append(doc_ctx)
        if mem_ctx:
            parts.append(mem_ctx)
        if ctx:
            parts.append(ctx)
        if history_text:
            parts.append(f"Previous conversation:\n{history_text}")
        parts.append(f"User: {user_message}\nAssistant:")
        return "\n".join(parts), sources
    if mode == "web":
        return ("__web__", user_message, history_text, ctx, doc_ctx, mem_ctx), sources
    return None, []


def _record_memory_safe(user_id, conversation_id, message_id, user_message, answer):
    """Fire-and-forget: embed and store this exchange for future cross-conversation
    retrieval. Never awaited by the caller — a slow/failed embedding must not
    delay or break the user-facing chat response."""
    async def _do():
        try:
            content = f"User: {user_message}\nAssistant: {answer}" if answer else f"User: {user_message}"
            await retrieval.record_memory(user_id, conversation_id, message_id, content)
        except Exception as exc:
            print(f"[kGPT] record_memory failed (non-fatal): {exc}")

    asyncio.create_task(_do())


async def _persist_exchange(user_id, user_message, answer, mode, conversation_id=None, sources=None):
    """Save a user/assistant exchange using a fresh async DB session (safe during streaming).
    Always saves the user message; saves assistant reply only if answer is non-empty."""
    async with AsyncSessionLocal() as db:
        _save_message(db, user_id, "user", user_message, mode, conversation_id)
        assistant_msg = None
        if answer:
            assistant_msg = _save_message(
                db, user_id, "assistant", answer, mode, conversation_id, sources=sources
            )
        if conversation_id:
            conv = (
                await db.execute(select(Conversation).where(Conversation.id == conversation_id))
            ).scalar_one_or_none()
            if conv:
                conv.updated_at = datetime.now(timezone.utc)
        await db.commit()
        _record_memory_safe(
            user_id, conversation_id, assistant_msg.id if assistant_msg else None, user_message, answer
        )


@chat_router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_rate_limits(current_user.id, db)
    user_message = request.message
    requested_mode = request.mode or "auto"

    conv = await _resolve_conversation(db, current_user.id, request.conversation_id, user_message)
    conv_id = conv.id

    providers = candidate_providers()
    response_text = None
    response_sources: list[str] = []
    final_mode = requested_mode if requested_mode != "auto" else "general"
    used_provider = None
    last_error = None

    for provider in providers:
        try:
            llm = build_llm(provider)
            mode = (
                await classify_query(user_message, llm)
                if requested_mode == "auto"
                else requested_mode
            )
            response_text, response_sources = await _run_mode(
                llm, mode, user_message, db, current_user.id, conv_id
            )
            final_mode = mode
            used_provider = provider
            break
        except Exception as exc:
            last_error = exc
            traceback.print_exc()
            continue

    if response_text is None:
        tried = ", ".join(providers) if providers else "none"
        response_text = (
            f"All configured LLM providers failed (tried: {tried}). "
            f"Last error: {last_error}"
        )
    else:
        print(f"[kGPT] answered mode={final_mode} provider={used_provider}")

    _save_message(db, current_user.id, "user", user_message, final_mode, conv_id)
    assistant_msg = _save_message(
        db, current_user.id, "assistant", response_text, final_mode, conv_id, sources=response_sources
    )
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    _record_memory_safe(current_user.id, conv_id, assistant_msg.id, user_message, response_text)
    return ChatResponse(response=response_text, mode=final_mode, sources=response_sources)


@chat_router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """Streaming variant of /api/chat. Emits Server-Sent Events:
    {"type":"meta","mode":..,"provider":..} -> {"type":"chunk","text":..} -> {"type":"done"}.
    Both general and web modes stream token-by-token.
    """
    async with AsyncSessionLocal() as _rdb:
        await _check_rate_limits(current_user.id, _rdb)

    user_message = request.message
    requested_mode = request.mode or "auto"

    # Resolve the conversation up front (create one if needed).
    async with AsyncSessionLocal() as _cdb:
        conv = await _resolve_conversation(_cdb, current_user.id, request.conversation_id, user_message)
        conv_id = conv.id
        await _cdb.commit()

    def sse(obj):
        return f"data: {json.dumps(obj)}\n\n"

    sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    providers = candidate_providers()
    llm = None
    chosen = None
    mode = None
    last_error = None
    for provider in providers:
        try:
            llm = build_llm(provider)
            mode = (
                await classify_query(user_message, llm)
                if requested_mode == "auto"
                else requested_mode
            )
            chosen = provider
            break
        except Exception as exc:
            last_error = exc
            traceback.print_exc()
            continue

    if chosen is None:
        raise HTTPException(status_code=503, detail=f"No LLM provider available: {last_error}")

    async def event_stream():
        collected = []
        user_msg_saved = False
        sources: list[str] = []
        try:
            yield sse({"type": "meta", "mode": mode, "provider": chosen, "conversation_id": conv_id})
            async with AsyncSessionLocal() as _db:
                text_prompt, sources = await _build_stream_prompt(mode, user_message, _db, current_user.id, conv_id)

            if isinstance(text_prompt, tuple):
                _, _msg, _hist, _ctx, _doc_ctx, _mem_ctx = text_prompt
                search_query = await _resolve_search_query(llm, _msg, _hist)
                search_results = await asyncio.to_thread(run_web_search, search_query)
                text_prompt = (
                    (_doc_ctx if _doc_ctx else "") +
                    (_mem_ctx if _mem_ctx else "") +
                    (_ctx if _ctx else "") +
                    (f"Previous conversation:\n{_hist}\n" if _hist else "") +
                    f"Based on the following web search results, answer the user's question: '{_msg}'\n\n"
                    f"Search Results:\n{search_results}\n\nAnswer:"
                )

            # Save user message NOW — after building the prompt (so it won't appear in
            # history twice) but before streaming starts. The generator keeps running
            # even after the client aborts, so the finally block may arrive too late for
            # a quick "continue" — saving here ensures the DB is updated immediately.
            async with AsyncSessionLocal() as _udb:
                _save_message(_udb, current_user.id, "user", user_message, mode, conv_id)
                await _udb.commit()
                user_msg_saved = True

            if text_prompt is not None:
                async for piece in llm.astream(text_prompt):
                    if piece:
                        collected.append(piece)
                        yield sse({"type": "chunk", "text": piece})
            else:
                async with AsyncSessionLocal() as _db2:
                    text, sources = await _run_mode(llm, mode, user_message, _db2, current_user.id, conv_id)
                collected.append(text)
                yield sse({"type": "chunk", "text": text})
            yield sse({"type": "done", "sources": sources})
        except asyncio.CancelledError:
            pass
        except GeneratorExit:
            pass
        except Exception as exc:
            traceback.print_exc()
            collected.append(f"An error occurred: {exc}")
            yield sse({"type": "error", "message": str(exc)})
        finally:
            answer = "".join(collected)
            try:
                if user_msg_saved:
                    # User message already saved; only persist the assistant reply.
                    if answer:
                        async with AsyncSessionLocal() as _adb:
                            _assistant_msg = _save_message(
                                _adb, current_user.id, "assistant", answer, mode, conv_id, sources=sources
                            )
                            if conv_id:
                                _conv = (
                                    await _adb.execute(
                                        select(Conversation).where(Conversation.id == conv_id)
                                    )
                                ).scalar_one_or_none()
                                if _conv:
                                    _conv.updated_at = datetime.now(timezone.utc)
                            await _adb.commit()
                            _record_memory_safe(
                                current_user.id, conv_id, _assistant_msg.id, user_message, answer
                            )
                else:
                    # User message wasn't saved yet (error before that point); save both.
                    await _persist_exchange(current_user.id, user_message, answer, mode, conv_id, sources=sources)
            except Exception:
                traceback.print_exc()
            print(f"[kGPT] streamed mode={mode} provider={chosen}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=sse_headers,
    )


# ===== Conversations =====
def _conv_dict(c):
    return {
        "id": c.id,
        "title": c.title,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "attachment_name": c.attachment_name,
    }


@chat_router.post("/conversations/{conv_id}/attachment")
async def upload_attachment(
    conv_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: jpg, png, pdf, docx.")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Max 10 MB.")

    existing_count = (
        await db.execute(
            select(func.count(ConversationAttachment.id)).where(
                ConversationAttachment.conversation_id == conv_id
            )
        )
    ).scalar() or 0
    if existing_count >= MAX_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_ATTACHMENTS} files per conversation.",
        )

    try:
        from backend.agent.file_extractor import extract_text
        context = await asyncio.to_thread(extract_text, data, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not extract file content: {exc}")

    att = ConversationAttachment(
        conversation_id=conv_id,
        filename=file.filename,
        context_text=context,
    )
    db.add(att)
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"filename": file.filename, "count": existing_count + 1}


@chat_router.delete("/conversations/{conv_id}/attachment")
async def delete_attachment(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.execute(
        ConversationAttachment.__table__.delete().where(
            ConversationAttachment.conversation_id == conv_id
        )
    )
    conv.context = None
    conv.attachment_name = None
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "removed"}


@chat_router.get("/conversations")
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    convs = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.updated_at.desc())
        )
    ).scalars().all()
    conv_ids = [c.id for c in convs]
    count_map: dict[int, int] = {}
    att_map: dict[int, list] = {}
    if conv_ids:
        msg_rows = (
            await db.execute(
                select(ChatMessage.conversation_id, func.count(ChatMessage.id))
                .where(ChatMessage.conversation_id.in_(conv_ids))
                .group_by(ChatMessage.conversation_id)
            )
        ).all()
        count_map = {cid: cnt for cid, cnt in msg_rows}
        att_rows = (
            await db.execute(
                select(ConversationAttachment.conversation_id, ConversationAttachment.filename)
                .where(ConversationAttachment.conversation_id.in_(conv_ids))
                .order_by(ConversationAttachment.uploaded_at.asc())
            )
        ).all()
        for cid, fname in att_rows:
            att_map.setdefault(cid, []).append(fname)
    result = []
    for c in convs:
        names = att_map.get(c.id, [])
        if not names and c.attachment_name:
            names = [c.attachment_name]
        result.append({
            **_conv_dict(c),
            "message_count": count_map.get(c.id, 0),
            "attachment_names": names,
        })
    return result


@chat_router.post("/conversations")
async def create_conversation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(user_id=current_user.id, title="New chat")
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {**_conv_dict(conv), "message_count": 0, "attachment_names": []}


@chat_router.get("/conversations/{conv_id}/messages")
async def conversation_messages(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conv_id)
            .order_by(ChatMessage.timestamp.asc())
        )
    ).scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "mode": m.mode,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            "sources": m.get_sources_list(),
        }
        for m in msgs
    ]


@chat_router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.execute(
        ConversationAttachment.__table__.delete().where(
            ConversationAttachment.conversation_id == conv_id
        )
    )
    await db.execute(
        ChatMessage.__table__.delete().where(ChatMessage.conversation_id == conv_id)
    )
    await db.delete(conv)
    await db.commit()
    return {"status": "deleted"}


@chat_router.patch("/conversations/{conv_id}")
async def rename_conversation(
    conv_id: int,
    title: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    new_title = (title or "").strip()[:60]
    if new_title:
        conv.title = new_title
        await db.commit()
    return _conv_dict(conv)
