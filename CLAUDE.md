# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

kGPT is a full-stack AI assistant: a FastAPI backend (LangChain-based chat with auto-routing
between general LLM answers and live web search) and a vanilla HTML/CSS/JS frontend served as
static files by FastAPI itself (same origin, no separate build step).

Live at **https://k-gpt.duckdns.org** (AWS EC2, Nginx + Let's Encrypt).

## Commands

```bash
# Setup
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env   # then set GROQ_API_KEY, JWT_SECRET_KEY, RESEND_API_KEY, APP_BASE_URL

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

1. **Conversation resolution** (`_resolve_conversation`) — finds or creates a `Conversation` row.
2. **Provider selection** (`candidate_providers()` from `backend/agent/llm.py`) — Groq only;
   returns an empty list if `GROQ_API_KEY` is not set.
3. **Routing/classification** (`classify_query`) — if `mode == "auto"`, an LLM call classifies
   the message into `general` or `web`. General means a direct LLM answer; web means DuckDuckGo
   results are fetched first and prepended to the prompt.
4. **Mode execution** (`_run_mode` for non-streaming, `_build_stream_prompt` for streaming):
   both modes stream token-by-token via `llm.stream(...)`.
5. **Persistence** — `/api/chat` saves messages inline. `/api/chat/stream` saves the **user
   message immediately** after building the prompt (before any streaming begins), so "continue"
   after an aborted stream always finds the right context. The assistant reply is saved in the
   generator's `finally` block once streaming finishes (or is interrupted).

SSE message shape for `/api/chat/stream`: `{"type":"meta",...}` → one or more
`{"type":"chunk","text":...}` → `{"type":"done"}` (or `{"type":"error",...}`).

### History loading (`_history_text_from_db`)

Conversation history is loaded directly from the DB (not in-memory LangChain memory), filtered
by `user_id` and `conversation_id`, ordered by `timestamp DESC`, limited to the last 10
exchanges (20 rows). This survives server restarts and works across multiple workers.

### LLM provider abstraction (`backend/agent/llm.py`)

- Groq only (`langchain_groq.ChatGroq`). `candidate_providers()` returns `["groq"]` if
  `GROQ_API_KEY` is set, otherwise `[]`.
- `_env()` calls `load_dotenv(override=True)` on **every** invocation so editing `.env` takes
  effect on the next request without restarting.

### Web search tool (`backend/agent/tools.py`)

- `run_web_search(query)` calls `ddgs`/`duckduckgo_search` directly. Used only for the `web`
  chat mode.

### Email (`backend/agent/email.py`)

- `send_verification_email(to_email, username, token)` uses the Resend SDK.
- Silently skips if `RESEND_API_KEY` is not set (useful for local dev without email).

### Database (`backend/database/db.py`, `backend/api/models/`)

- SQLAlchemy + SQLite (`DATABASE_URL`, default `sqlite:///./database/data.db`).
- `init_db()` runs `Base.metadata.create_all` then two idempotent hand-written migrations:
  - `_migrate_conversations()` — adds `chat_messages.conversation_id`, buckets orphaned messages.
  - `_migrate_users()` — adds `email_verified` (DEFAULT 1 for existing users) and
    `verification_token` columns.
- No Alembic — schema changes need a similar hand-written, repeat-safe migration added to `init_db`.
- Models: `User` (`backend/api/models/user.py`); `ChatMessage`, `Conversation`
  (`backend/api/models/chat.py`).

### Auth (`backend/api/auth.py`)

- JWT (PyJWT) + Argon2 password hashing (pwdlib).
- **Login uses email** (not username) as the identifier — the OAuth2 `username` field carries
  the email value.
- Registration sets `email_verified=False` and sends a verification email via Resend.
  Unverified users get a 403 on login and cannot access any protected route.
- Endpoints: `register`, `login`, `verify-email`, `resend-verification`, `check` (availability),
  `me`.
- `get_current_user` blocks unverified users with HTTP 403.

### Frontend

- `frontend/` is plain HTML/CSS/JS, no build step. `backend/api/main.py` mounts it with
  `StaticFiles(..., html=True)` at `/` — **this mount must stay registered last** so it doesn't
  shadow `/api/*` routes.
- `frontend/login.html` — login (email field) + register + "check your inbox" pending screen.
- `frontend/verify.html` — reads `?token=` from URL, calls `POST /api/auth/verify-email`,
  stores JWT, redirects to `index.html`.
- `frontend/index.html` + `frontend/js/chat.js` — full chat UI with conversations sidebar,
  SSE streaming, markdown/code/math rendering, copy (HTTP-safe fallback), regenerate, PDF export.

## Environment variables

Config is read via `os.getenv` scattered across modules — see `.env.example` for the full list.
The most relevant:

- `GROQ_API_KEY` — required for the LLM to work.
- `JWT_SECRET_KEY` — must be set to something real; generate with
  `python -c "import secrets; print(secrets.token_hex(32))"`.
- `RESEND_API_KEY` + `RESEND_FROM_EMAIL` — for email verification. Leave blank to skip.
- `APP_BASE_URL` — full public URL used in verification email links (e.g.
  `https://k-gpt.duckdns.org`).
- `DATABASE_URL` — defaults to `sqlite:///./database/data.db`.

## Deployment (AWS EC2)

- Ubuntu 26.04, Python 3.13 (from deadsnakes PPA — Ubuntu 26.04 ships Python 3.14 which is
  incompatible with LangChain).
- Systemd service: `deploy/kgpt.service` (app at `/home/ubuntu/kgpt`).
- Nginx reverse proxy: `/etc/nginx/sites-enabled/kgpt` with SSE buffering disabled and HTTPS.
- Let's Encrypt cert for `k-gpt.duckdns.org` via Certbot (auto-renews).
- SSH key: `kgpt-key.pem` (stored locally in Downloads).

## Dependency note

`requirements.txt` deliberately pins `langchain<1.0` / `langchain-core<1.0` because
`langchain.memory.ConversationBufferWindowMemory` (used in `backend/agent/memory.py`) was
removed in LangChain 1.0. Don't bump these without migrating away from that class first.
