# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

kGPT is a full-stack AI assistant: a FastAPI backend (LangChain-based chat with auto-routing
between general LLM answers and live web search) and a vanilla HTML/CSS/JS frontend served as
static files by FastAPI itself (same origin, no separate build step).

## Commands

```bash
# Setup
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env   # then set GROQ_API_KEY / GEMINI_API_KEY and a real JWT_SECRET_KEY

# Run (auto-reload)
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

# Docker
docker-compose up -d --build
docker-compose down
```

- App UI: `http://localhost:8000/` (redirects to `login.html`)
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/health` (reports active mode + provider)

There is no test suite and no linter configuration in this repo.

## Architecture

### Request flow (chat)

`backend/api/routes/chat.py` is the core of the app. Every chat message goes through:

1. **Conversation resolution** (`_resolve_conversation`) — finds or creates a `Conversation` row;
   memory is keyed per-conversation as `f"{user_id}:{conversation_id}"`.
2. **Provider selection with fallback** (`candidate_providers()` from `backend/agent/llm.py`) —
   tries the preferred LLM provider, and on any exception (quota/429/auth) transparently retries
   the next available provider. This happens both for non-streaming `/api/chat` and for the
   classification step in `/api/chat/stream`.
3. **Routing/classification** (`classify_query`) — if `mode == "auto"`, an LLM call classifies the
   message into `general` or `web`. General means a direct LLM answer; web means DuckDuckGo
   results are fetched first and prepended to the prompt.
4. **Mode execution** (`_run_mode` for non-streaming, `_build_stream_prompt` + `_run_mode` for
   streaming): both `general` and `web` modes stream token-by-token via `llm.stream(...)`.
5. **Persistence** — `/api/chat` saves messages inline; `/api/chat/stream` persists via
   `_persist_exchange` (its own `SessionLocal()`) after the SSE stream finishes, and also updates
   the LangChain memory object so follow-ups have context.

SSE message shape for `/api/chat/stream`: `{"type":"meta",...}` → one or more
`{"type":"chunk","text":...}` → `{"type":"done"}` (or `{"type":"error",...}`).

### LLM provider abstraction (`backend/agent/llm.py`)

- Two cloud providers: `gemini` and `groq`. Selection via `LLM_PROVIDER` env var (defaults to
  `gemini` if unset/invalid).
- `_env()` calls `load_dotenv(override=True)` on **every** invocation, so editing `.env` takes
  effect on the next request without restarting the server.
- `candidate_providers()` returns `[preferred, ...other available providers]` — used by the chat
  routes to implement automatic fallback.

### Web search tool (`backend/agent/tools.py`)

- `run_web_search(query)` calls `ddgs`/`duckduckgo_search` directly, with the LangChain
  `DuckDuckGoSearchResults` tool as a fallback. Used only for the `web` chat mode.

### Database (`backend/database/db.py`, `backend/api/models/`)

- SQLAlchemy + SQLite (`DATABASE_URL`, default `sqlite:///./database/data.db`).
- `init_db()` runs `Base.metadata.create_all` then `_migrate_conversations()`, a hand-written,
  idempotent migration that adds `chat_messages.conversation_id` to pre-existing DBs and buckets
  any orphaned messages into a synthetic "Imported chat" conversation. There is no Alembic —
  schema changes need a similar hand-written, repeat-safe migration added here.
- Models: `User` (`backend/api/models/user.py`); `ChatMessage`, `Conversation`
  (`backend/api/models/chat.py`).

### Auth (`backend/api/auth.py`)

- JWT (PyJWT, `JWT_SECRET_KEY`/`JWT_ALGORITHM`/`ACCESS_TOKEN_EXPIRE_MINUTES`) + Argon2 password
  hashing via `pwdlib`. `get_current_user` is the standard FastAPI dependency used across all
  protected routes.
- Registration enforces a username pattern (`[A-Za-z0-9_]{3,30}`) and a password policy (8-128
  chars, upper/lower/digit/special) via Pydantic `field_validator`s.

### Frontend

- `frontend/` is plain HTML/CSS/JS, no build step. `backend/api/main.py` mounts it with
  `StaticFiles(..., html=True)` at `/` — **this mount must stay registered last** so it doesn't
  shadow `/api/*` routes.
- `frontend/login.html` (auth) and `frontend/index.html` (chat UI) are separate pages.
  `frontend/js/chat.js` handles all chat logic including conversations CRUD, streaming, rendering.

## Environment variables

Config is read via `os.getenv` scattered across modules (not a single settings object) — see
`.env.example` for the full list with defaults. The most relevant for development:

- `LLM_PROVIDER` (`groq` recommended, or `gemini`) + matching API key (`GROQ_API_KEY` /
  `GEMINI_API_KEY`).
- `JWT_SECRET_KEY` — must be set to something real; generate with
  `python -c "import secrets; print(secrets.token_hex(32))"`.
- `DATABASE_URL` — defaults to `sqlite:///./database/data.db`; the `database/` directory is
  created automatically on startup.

## Dependency note

`requirements.txt` deliberately pins `langchain<1.0` / `langchain-core<1.0` because
`langchain.memory.ConversationBufferWindowMemory` (used in `backend/agent/memory.py`) was
removed in LangChain 1.0. Don't bump these without migrating to LangGraph-based memory first.
