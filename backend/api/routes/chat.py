"""
Chat router for kGPT.
Supports: general, rag, web, sql, code, vision modes.
"""

import json
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage

from backend.agent.llm import get_llm, build_llm, candidate_providers, build_vision_llm
from backend.agent.memory import get_memory, clear_memory
from backend.agent.rag import get_rag_chain
from backend.agent.tools import run_web_search, run_sql_agent, run_code_execution
from backend.api.auth import get_current_user
from backend.api.models.chat import ChatMessage, ChatRequest, ChatResponse, Conversation
from backend.api.models.user import User, UsageStat
from backend.database.db import get_db, SessionLocal

chat_router = APIRouter(prefix="/api/chat", tags=["chat"])


def classify_query(query: str, llm) -> str:
    """Classify the user message into one of the modes: general, rag, web, sql, code."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are a routing classification agent for a multi-tool AI assistant.\n"
            "Analyze the user's message and determine the single most appropriate tool category.\n\n"
            "Categories:\n"
            "- 'rag': Select this if the user is asking about, querying, summarizing, or analyzing uploaded documents, files, manuals, PDFs, or articles. Example queries: 'Explain this document', 'what does the pdf say about x?', 'summarize my files'.\n"
            "- 'web': Select this if the user is asking for real-time information, recent news, current weather, stock prices today, sports scores, live info, or anything that requires searching the web. Example queries: 'What is the latest AI news?', 'search the web for x', 'weather today in New York'.\n"
            "- 'sql': Select this ONLY when the user explicitly asks about data stored in THIS application's own database - its registered users/accounts, stored chat messages, or app usage/activity records. The user must clearly be referring to the app's own database, not the world at large. Example queries: 'how many users are registered in the database?', 'query the users table', 'how many messages have I sent?'. Do NOT use 'sql' for general counting questions about the real world such as 'how many scientists are there' or 'how many countries exist' - those are 'general' or 'web'.\n"
            "- 'code': Select this if the user is asking to write and run code, execute scripts, solve math equations via coding, or generate and test programming solutions using a python repl. Example queries: 'Write and run this code', 'calculate the first 10 prime numbers', 'plot a bar chart'.\n"
            "- 'general': Select this for general greetings, conversational banter, questions about general facts that do not require live search, real-world counting/estimate questions, coding help that DOES NOT require execution, or anything else. Example queries: 'hi', 'how are you?', 'tell me a joke', 'what is the capital of France?', 'how many scientists are there'.\n\n"
            "Important: a 'how many' or counting question is NOT automatically 'sql'. Only route to 'sql' when the user is clearly asking about the application's own stored data.\n\n"
            "Constraint: You must reply with exactly one of these five words: 'rag', 'web', 'sql', 'code', or 'general'. Do NOT include any explanations, markdown format, code blocks, punctuation, or extra words."
        )),
        ("human", "{query}")
    ])
    
    chain = prompt | llm | StrOutputParser()
    try:
        category = chain.invoke({"query": query}).strip().lower()
        for cat in ["rag", "web", "sql", "code", "general"]:
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


def _save_usage(db, user_id, mode, tokens_used=0):
    stat = UsageStat(
        user_id=user_id,
        mode=mode,
        tokens_used=tokens_used,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(stat)


def _run_mode(llm, mode, user_message, memory):
    """Execute a single mode with the given LLM and return the response text."""
    if mode == "general":
        history = memory.load_memory_variables({}).get("chat_history", [])
        history_text = ""
        for msg in history:
            role = "User" if msg.type == "human" else "Assistant"
            history_text += f"{role}: {msg.content}\n"
        prompt = (
            f"Previous conversation:\n{history_text}\nUser: {user_message}\nAssistant:"
            if history_text
            else f"User: {user_message}\nAssistant:"
        )
        result = llm.invoke(prompt)
        return result.content if hasattr(result, "content") else str(result)

    if mode == "rag":
        rag_chain = get_rag_chain(llm)
        result = rag_chain.invoke({"query": user_message})
        return (
            result.get("result", str(result))
            if isinstance(result, dict)
            else str(result)
        )

    if mode == "web":
        search_results = run_web_search(user_message)
        summary_prompt = (
            f"Based on the following web search results, answer: '{user_message}'\n\n"
            f"Search Results:\n{search_results}\n\nAnswer:"
        )
        result = llm.invoke(summary_prompt)
        return result.content if hasattr(result, "content") else str(result)

    if mode == "sql":
        return run_sql_agent(user_message, llm)

    if mode == "code":
        return run_code_execution(user_message, llm)

    return f"Unknown mode '{mode}'. Supported: general, rag, web, sql, code."


def _build_stream_prompt(mode, user_message, memory):
    """Return a text prompt for token-streamable modes (general, web), else None."""
    if mode == "general":
        history = memory.load_memory_variables({}).get("chat_history", [])
        history_text = ""
        for msg in history:
            role = "User" if msg.type == "human" else "Assistant"
            history_text += f"{role}: {msg.content}\n"
        return (
            f"Previous conversation:\n{history_text}\nUser: {user_message}\nAssistant:"
            if history_text
            else f"User: {user_message}\nAssistant:"
        )
    if mode == "web":
        search_results = run_web_search(user_message)
        return (
            f"Based on the following web search results, answer: '{user_message}'\n\n"
            f"Search Results:\n{search_results}\n\nAnswer:"
        )
    return None


def _persist_exchange(user_id, user_message, answer, mode, memory, conversation_id=None):
    """Save a user/assistant exchange using a fresh DB session (safe during streaming)."""
    db = SessionLocal()
    try:
        _save_message(db, user_id, "user", user_message, mode, conversation_id)
        _save_message(db, user_id, "assistant", answer, mode, conversation_id)
        _save_usage(db, user_id, mode)
        if conversation_id:
            conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conv:
                conv.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    try:
        memory.save_context({"input": user_message}, {"output": answer})
    except Exception:
        pass


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
    memory = get_memory(f"{current_user.id}:{conv_id}")

    providers = candidate_providers()
    response_text = None
    final_mode = requested_mode if requested_mode != "auto" else "general"
    used_provider = None
    last_error = None

    # Try the preferred provider, then transparently fall back to any other
    # available provider if it fails (e.g. quota / 429 / auth errors).
    for provider in providers:
        try:
            llm = build_llm(provider)
            mode = (
                classify_query(user_message, llm)
                if requested_mode == "auto"
                else requested_mode
            )
            response_text = _run_mode(llm, mode, user_message, memory)
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
    _save_usage(db, current_user.id, final_mode)
    conv.updated_at = datetime.now(timezone.utc)

    try:
        memory.save_context({"input": user_message}, {"output": response_text})
    except Exception:
        pass

    db.commit()
    return ChatResponse(response=response_text, mode=final_mode)


@chat_router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """Streaming variant of /api/chat. Emits Server-Sent Events:
    {"type":"meta","mode":..,"provider":..} -> {"type":"chunk","text":..} -> {"type":"done"}.
    General/web modes stream token-by-token; rag/sql/code compute fully then emit once.
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

    memory = get_memory(f"{current_user.id}:{conv_id}")

    def sse(obj):
        return f"data: {json.dumps(obj)}\n\n"

    sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    # ----- Image understanding (vision) path -----
    images = request.images or ([request.image] if request.image else [])
    images = [im for im in images if im][:5]
    if images:
        try:
            vision_llm = build_vision_llm()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Vision model unavailable: {exc}")

        prompt_text = user_message.strip() if user_message else "Describe the image(s) in detail."

        def vision_stream():
            collected = []
            try:
                yield sse({"type": "meta", "mode": "vision", "provider": "groq", "conversation_id": conv_id})
                content = [{"type": "text", "text": prompt_text}]
                for im in images:
                    content.append({"type": "image_url", "image_url": {"url": im}})
                msg = HumanMessage(content=content)
                for chunk in vision_llm.stream([msg]):
                    piece = getattr(chunk, "content", "") or ""
                    if piece:
                        collected.append(piece)
                        yield sse({"type": "chunk", "text": piece})
                yield sse({"type": "done"})
                answer = "".join(collected)
            except Exception as exc:
                traceback.print_exc()
                answer = "".join(collected) or f"An error occurred: {exc}"
                yield sse({"type": "error", "message": str(exc)})
            try:
                label = f"{prompt_text} [{len(images)} image(s)]"
                _persist_exchange(current_user.id, label, answer, "vision", memory, conv_id)
            except Exception:
                traceback.print_exc()
            print(f"[kGPT] streamed mode=vision images={len(images)} provider=groq")

        return StreamingResponse(vision_stream(), media_type="text/event-stream", headers=sse_headers)

    # Pick a working provider and classify up front (non-streamed) so we can
    # fall back cleanly before any streaming begins.
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
        # Let the frontend fall back to the non-streaming endpoint.
        raise HTTPException(status_code=503, detail=f"No LLM provider available: {last_error}")

    def event_stream():
        collected = []
        try:
            yield sse({"type": "meta", "mode": mode, "provider": chosen, "conversation_id": conv_id})
            text_prompt = _build_stream_prompt(mode, user_message, memory)
            if text_prompt is not None:
                for chunk in llm.stream(text_prompt):
                    piece = getattr(chunk, "content", "") or ""
                    if piece:
                        collected.append(piece)
                        yield sse({"type": "chunk", "text": piece})
            else:
                # Agent modes (rag/sql/code) don't stream tokens; emit once.
                text = _run_mode(llm, mode, user_message, memory)
                collected.append(text)
                yield sse({"type": "chunk", "text": text})
            yield sse({"type": "done"})
            answer = "".join(collected)
        except Exception as exc:
            traceback.print_exc()
            answer = "".join(collected) or f"An error occurred: {exc}"
            yield sse({"type": "error", "message": str(exc)})

        try:
            _persist_exchange(current_user.id, user_message, answer, mode, memory, conv_id)
        except Exception:
            traceback.print_exc()
        print(f"[kGPT] streamed mode={mode} provider={chosen}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=sse_headers,
    )


@chat_router.get("/history")
async def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.timestamp.desc())
        .limit(50)
        .all()
    )
    messages.reverse()
    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "mode": msg.mode,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
        }
        for msg in messages
    ]


@chat_router.delete("/history")
async def clear_chat_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(ChatMessage).filter(ChatMessage.user_id == current_user.id).delete()
    db.commit()
    try:
        clear_memory(str(current_user.id))
    except Exception:
        pass
    return {"status": "cleared", "message": "Chat history and memory cleared."}


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