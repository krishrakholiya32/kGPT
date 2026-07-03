# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project overview

kGPT is a full-stack AI assistant: a FastAPI backend with raw-httpx LLM chat (Gemini primary, Groq
fallback; auto-routing between general LLM answers and live web search), file attachment support, and
a React 19 + TypeScript + Vite frontend, built and served as static files by FastAPI itself (same
origin, no separate web server in production).

Live at **https://kgpt.zrik.tech** (AWS EC2, Nginx + Let's Encrypt).
Old domain **https://k-gpt.duckdns.org** also active.

## Commands

```bash
# Backend setup
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env   # then set DATABASE_URL, GEMINI_API_KEY, GROQ_API_KEY, JWT_SECRET_KEY, GMAIL_USER, GMAIL_APP_PASSWORD, APP_BASE_URL

# Frontend (dev, hot reload — proxies /api to :8000)
cd frontend && npm install && npm run dev

# Frontend (production build — MUST do this before running the backend standalone)
cd frontend && npm run build   # outputs to frontend/dist, served by FastAPI

# Run backend (auto-reload)
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

# Docker (app + Postgres)
docker-compose up -d --build
docker-compose down
```

- App UI: `http://localhost:8000/` (React SPA, client-side routes `/`, `/login`, `/verify`)
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/health`

## Architecture

### Request flow (chat)

`backend/api/routes/chat.py` is the core of the app. Every chat message goes through:

1. **Rate limiting** (`_check_rate_limits`) — 20 req/min (in-memory bucket) + 1000/week (DB count).
2. **Conversation resolution** (`_resolve_conversation`) — finds or creates a `Conversation` row.
3. **File context** (`_file_context_preamble`) — queries `conversation_attachments`, concatenates all
   extracted text into a preamble injected before the user message.
4. **Provider selection** (`candidate_providers()`) — all Gemini keys first, then all Groq keys (unbounded rotation via `GEMINI_API_KEYS`/`GROQ_API_KEYS`).
5. **Routing** (`classify_query`) — if `mode == "auto"`, LLM classifies as `general` or `web`.
6. **Mode execution** — both modes stream token-by-token via `llm.stream(...)`.
7. **Persistence** — user message saved before streaming; assistant reply saved in `finally` block.

SSE shape: `{"type":"meta",...}` → `{"type":"chunk","text":...}` → `{"type":"done"}`.

### File attachments

- New uploads go to `conversation_attachments` table (id, conversation_id, filename, context_text, uploaded_at).
- Max 10 files per conversation, max 10 MB each.
- Supported: `.jpg`, `.jpeg`, `.png`, `.pdf`, `.docx`.
- Extraction: PDF via PyMuPDF, DOCX via python-docx, images via Gemini vision (`gemini-3.1-flash-lite`) with Groq vision fallback (`qwen/qwen3.6-27b`) in `backend/agent/file_extractor.py`.
- Legacy single-attachment columns (`context`, `attachment_name`) on `Conversation` still read as fallback.

### Rate limiting

- Per-minute: in-memory `defaultdict(list)` per `user_id`, pruned each request. Shared across threads via `threading.Lock`. Not shared across workers (2 workers → effective limit ~40/min, acceptable for low traffic).
- Weekly: DB query counting `role='user'` messages in last 7 days.

### History loading (`_history_text_from_db`)

Loaded from DB (not in-memory), filtered by `user_id` + `conversation_id`, last 10 exchanges (20 rows).

### Frontend session persistence

- `sessionStorage` stores the active `conversation_id` (logic preserved 1:1 from the original vanilla-JS app, now in `frontend/src/pages/Chat.tsx`).
- On page load: if saved conv exists in the list → restore it. Otherwise create a fresh empty conv.
- On logout: `sessionStorage` cleared → next login always starts fresh.
- `pageshow` listener forces reload on bfcache restore.

### Database (`backend/database/db.py`)

- Async SQLAlchemy against PostgreSQL (`asyncpg` driver). Migrated from the original synchronous SQLite + WAL-mode setup — Postgres handles concurrent writers natively, so the WAL pragma is gone.
- `init_db()` runs `Base.metadata.create_all` then idempotent hand-written migrations, rewritten to run on the async engine via `conn.run_sync(...)`:
  - `_migrate_conversations()` — adds `conversation_id` to `chat_messages`.
  - `_migrate_users()` — adds `email_verified`, `verification_token`.
  - `_migrate_attachments()` — adds legacy `context`, `attachment_name` columns to `conversations`.
  - `_migrate_attachment_table()` — creates `conversation_attachments` table; migrates any legacy rows.
- `DATABASE_URL` accepts `postgres://` (Heroku/Render style) and rewrites it to `postgresql+asyncpg://` via `_normalize_async_url()`.
- `DateTime` columns on `User`/`Conversation`/`ChatMessage` are `DateTime(timezone=True)` — asyncpg raises `DataError` on timezone-naive columns receiving timezone-aware datetimes (SQLite was lenient about this; Postgres is not).

### Auth (`backend/api/auth.py`)

- JWT (PyJWT) + Argon2 password hashing (via `pwdlib`), both inline in this file — kGPT was already on PyJWT+Argon2 before the stack-unification work, unlike ClauseGuard/Surveillance which needed a lazy-rehash migration off bcrypt.
- JWT startup guard: exits immediately if `JWT_SECRET_KEY` is the default value.
- Registration sets `email_verified=True` directly (no email gate in practice).
- Email: Gmail SMTP via `backend/agent/email.py`.
- All routes are `async def`, using `AsyncSession` + `select()`.

### LLM client (`backend/agent/llm.py`)

- No LangChain — `LLMClient` wraps a single Groq or Gemini API key with raw `httpx`:
  - `await client.ainvoke(prompt, system=None) -> str` — non-streaming.
  - `async for piece in client.astream(prompt, system=None)` — SSE-based streaming, yields text chunks.
- `candidate_providers()` returns the ordered fallback list: every configured Gemini key first (`gemini:0`, `gemini:1`, ...), then every Groq key (`groq:0`, `groq:1`, ...). Callers (`chat.py`) walk this list on rate-limit/error until one succeeds.
- Groq streaming parses SSE `data:` lines as JSON, reading `choices[0]["delta"]["content"]`. Gemini streaming hits `.../streamGenerateContent?alt=sse`, reading `candidates[0]["content"]["parts"]`.
- Config (`_env()`) is re-read from `.env` on every call (`load_dotenv(override=True)`) so key/model changes take effect without a restart.
- `groq_model` default: `openai/gpt-oss-120b`. `llama-3.3-70b-versatile` and `llama-4-scout-17b-16e-instruct` were deprecated by Groq (announced June 17 2026) — do not reintroduce them.

### Frontend (`frontend/`)

- React 19 + TypeScript + Vite, built to `frontend/dist/` and served directly by FastAPI (`backend/api/main.py` mounts `/assets` and falls back to `index.html` for client-side routes).
- `pages/Chat.tsx` — sidebar, message thread, SSE consumption via manual `fetch` + `ReadableStream.getReader()` (buffers partial chunks, splits on `\n\n`), file upload, session persistence, theme toggle.
- `components/Markdown.tsx` — react-markdown + remark-gfm + remark-math + rehype-katex + rehype-highlight. Deliberately **without** `rehype-raw`, to avoid re-introducing the raw-HTML-injection risk the original `marked` + `DOMPurify` setup guarded against.
- `auth/AuthContext.tsx` — holds the JWT and current user; `api/client.ts` is the typed fetch wrapper all pages use.

## Deployment (AWS EC2)

- Ubuntu, Python 3.13 (deadsnakes PPA).
- Venv at `/home/ubuntu/kgpt/.venv/` — pip installs go there.
- Systemd service: `deploy/kgpt.service`.
- Nginx: `deploy/nginx.conf` — SSE buffering disabled, `client_max_body_size 10M`, `proxy_read_timeout 120s`.
- Let's Encrypt for `kgpt.zrik.tech` and `k-gpt.duckdns.org` via Certbot.
- PostgreSQL runs in a Docker container on the same EC2 instance (`docker-compose.yml`'s `db` service) — no managed DB service, keeping the zero-cost hosting model.
- Deploy workflow: `cd frontend && npm run build`, commit `frontend/dist/`, then pull + restart the systemd service on the EC2 box (FastAPI serves the pre-built SPA — no Node process runs in production).

## Known Quirks

- **`frontend/dist/` must be rebuilt before the backend serves the latest UI.** `npm run build` inside `frontend/` — FastAPI has no Node build step of its own.
- **`.env` silently overrides code defaults.** `GROQ_MODEL`/`GEMINI_MODEL` etc. have sane defaults in `llm.py`, but a stale value hardcoded in `.env` wins silently. When changing a model default, check the actual resolved `.env` value too, not just the code.
- **`DateTime(timezone=True)` is required** on any new datetime column — asyncpg rejects timezone-aware datetimes against timezone-naive Postgres columns (`DataError`), unlike SQLite which was lenient.

## Dependency note

LangChain has been fully removed — `backend/agent/llm.py` calls the Groq/Gemini HTTP APIs directly via
`httpx`. `requirements.txt` pins `httpx>=0.27` for this. Do not reintroduce LangChain without discussing
the tradeoff first (it was removed deliberately for a lighter, more transparent dependency footprint).
