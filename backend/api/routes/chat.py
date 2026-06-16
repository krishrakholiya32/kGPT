"""
Chat router for kGPT.
Supports: general and web modes (auto-routed).
"""

import json
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from backend.agent.llm import build_llm, candidate_providers
from backend.agent.tools import run_web_search
from backend.api.auth import get_current_user
from backend.api.models.chat import ChatMessage, ChatRequest, ChatResponse, Conversation
from backend.api.models.user import User
from backend.database.db import get_db, SessionLocal

chat_router = APIRouter(prefix="/api/chat", tags=["chat"])


def classify_query(query: str, llm) -> str:
    """Classify the user message as 'general' or 'web' (needs live web search)."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
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
        )),
        ("human", "{query}")
    ])

    chain = prompt | llm | StrOutputParser()
    try:
        category = chain.invoke({"query": query}).strip().lower()
        for cat in ["web", "general"]:
            if cat in category:
                return cat
        return "general"
    except Exception:
        return "general"


def _save_message(db, user_id, role, content, mode, conversation_id=None):
    msg = ChatMessage(
        user_id=user_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        mode=mode,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(msg)
    return msg


def _resolve_conversation(db, user_id, conversation_id, first_message=""):
    """Return the Conversation to use, creating one if needed.

    - Explicit valid id -> that conversation.
    - No id (legacy / first load) -> most recent conversation, else a new one.
    """
    conv = None
    if conversation_id:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .first()
        )
    if conv is None and not conversation_id:
        conv = (
            db.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .first()
        )
    if conv is None:
        title = (first_message or "New chat").strip()[:60] or "New chat"
        conv = Conversation(user_id=user_id, title=title)
        db.add(conv)
        db.flush()

    # Give a freshly-created chat a real title from its first message.
    fm = (first_message or "").strip()
    if conv is not None and fm and conv.title == "New chat":
        conv.title = fm[:60]

    return conv


def _history_text_from_db(db, user_id, conversation_id, limit=10) -> str:
    """Load recent conversation history directly from DB — works across workers and restarts."""
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id, ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.timestamp.desc())
        .limit(limit * 2)
        .all()
    )
    msgs = list(reversed(msgs))
    lines = ""
    for msg in msgs:
        role = "User" if msg.role == "user" else "Assistant"
        lines += f"{role}: {msg.content}\n"
    return lines


def _resolve_search_query(llm, user_message, history_text):
    """If the message is a short follow-up, expand it into a self-contained search query."""
    if not history_text or len(user_message.split()) > 6:
        return user_message
    prompt = (
        f"Given this conversation history:\n{history_text}\n"
        f"The user just said: \"{user_message}\"\n"
        f"Rewrite their message as a single, self-contained web search query "
        f"(no explanation, just the query):"
    )
    result = llm.invoke(prompt)
    query = result.content if hasattr(result, "content") else str(result)
    return query.strip().strip('"')


def _run_mode(llm, mode, user_message, db, user_id, conv_id):
    """Execute a single mode with the given LLM and return the response text."""
    history_text = _history_text_from_db(db, user_id, conv_id)

    if mode == "general":
        prompt = (
            f"Previous conversation:\n{history_text}\nUser: {user_message}\nAssistant:"
            if history_text
            else f"User: {user_message}\nAssistant:"
        )
        result = llm.invoke(prompt)
        return result.content if hasattr(result, "content") else str(result)

    if mode == "web":
        search_query = _resolve_search_query(llm, user_message, history_text)
        search_results = run_web_search(search_query)
        summary_prompt = (
            f"Previous conversation:\n{history_text}\n" if history_text else ""
        ) + (
            f"Based on the following web search results, answer the user's question: '{user_message}'\n\n"
            f"Search Results:\n{search_results}\n\nAnswer:"
        )
        result = llm.invoke(summary_prompt)
        return result.content if hasattr(result, "content") else str(result)

    return f"Unknown mode '{mode}'. Supported: general, web."


def _build_stream_prompt(mode, user_message, db, user_id, conv_id):
    """Return a text prompt for the given mode (general or web), else None."""
    history_text = _history_text_from_db(db, user_id, conv_id)

    if mode == "general":
        return (
            f"Previous conversation:\n{history_text}\nUser: {user_message}\nAssistant:"
            if history_text
            else f"User: {user_message}\nAssistant:"
        )
    if mode == "web":
        return ("__web__", user_message, history_text)
    return None


def _persist_exchange(user_id, user_message, answer, mode, conversation_id=None):
    """Save a user/assistant exchange using a fresh DB session (safe during streaming)."""
    db = SessionLocal()
    try:
        _save_message(db, user_id, "user", user_message, mode, conversation_id)
        _save_message(db, user_id, "assistant", answer, mode, conversation_id)
        if conversation_id:
            conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conv:
                conv.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


@chat_router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_message = request.message
    requested_mode = request.mode or "auto"

    conv = _resolve_conversation(db, current_user.id, request.conversation_id, user_message)
    conv_id = conv.id

    providers = candidate_providers()
    response_text = None
    final_mode = requested_mode if requested_mode != "auto" else "general"
    used_provider = None
    last_error = None

    for provider in providers:
        try:
            llm = build_llm(provider)
            mode = (
                classify_query(user_message, llm)
                if requested_mode == "auto"
                else requested_mode
            )
            response_text = _run_mode(llm, mode, user_message, db, current_user.id, conv_id)
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
    _save_message(db, current_user.id, "assistant", response_text, final_mode, conv_id)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    return ChatResponse(response=response_text, mode=final_mode)


@chat_router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """Streaming variant of /api/chat. Emits Server-Sent Events:
    {"type":"meta","mode":..,"provider":..} -> {"type":"chunk","text":..} -> {"type":"done"}.
    Both general and web modes stream token-by-token.
    """
    user_message = request.message
    requested_mode = request.mode or "auto"

    # Resolve the conversation up front (create one if needed).
    _cdb = SessionLocal()
    try:
        conv = _resolve_conversation(_cdb, current_user.id, request.conversation_id, user_message)
        conv_id = conv.id
        _cdb.commit()
    finally:
        _cdb.close()

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
                classify_query(user_message, llm)
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

    def event_stream():
        collected = []
        try:
            yield sse({"type": "meta", "mode": mode, "provider": chosen, "conversation_id": conv_id})
            _db = SessionLocal()
            try:
                text_prompt = _build_stream_prompt(mode, user_message, _db, current_user.id, conv_id)
            finally:
                _db.close()

            if isinstance(text_prompt, tuple):
                _, _msg, _hist = text_prompt
                search_query = _resolve_search_query(llm, _msg, _hist)
                search_results = run_web_search(search_query)
                text_prompt = (
                    f"Previous conversation:\n{_hist}\n" if _hist else ""
                ) + (
                    f"Based on the following web search results, answer the user's question: '{_msg}'\n\n"
                    f"Search Results:\n{search_results}\n\nAnswer:"
                )

            if text_prompt is not None:
                for chunk in llm.stream(text_prompt):
                    piece = getattr(chunk, "content", "") or ""
                    if piece:
                        collected.append(piece)
                        yield sse({"type": "chunk", "text": piece})
            else:
                text = _run_mode(llm, mode, user_message, _db, current_user.id, conv_id)
                collected.append(text)
                yield sse({"type": "chunk", "text": text})
            yield sse({"type": "done"})
            answer = "".join(collected)
        except Exception as exc:
            traceback.print_exc()
            answer = "".join(collected) or f"An error occurred: {exc}"
            yield sse({"type": "error", "message": str(exc)})

        try:
            _persist_exchange(current_user.id, user_message, answer, mode, conv_id)
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
    }


@chat_router.get("/conversations")
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [_conv_dict(c) for c in convs]


@chat_router.post("/conversations")
async def create_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = Conversation(user_id=current_user.id, title="New chat")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _conv_dict(conv)


@chat_router.get("/conversations/{conv_id}/messages")
async def conversation_messages(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == current_user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conv_id)
        .order_by(ChatMessage.timestamp.asc())
        .all()
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "mode": m.mode,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        }
        for m in msgs
    ]


@chat_router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == current_user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(ChatMessage).filter(ChatMessage.conversation_id == conv_id).delete()
    db.delete(conv)
    db.commit()
    try:
        clear_memory(f"{current_user.id}:{conv_id}")
    except Exception:
        pass
    return {"status": "deleted"}


@chat_router.patch("/conversations/{conv_id}")
async def rename_conversation(
    conv_id: int,
    title: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == current_user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    new_title = (title or "").strip()[:60]
    if new_title:
        conv.title = new_title
        db.commit()
    return _conv_dict(conv)