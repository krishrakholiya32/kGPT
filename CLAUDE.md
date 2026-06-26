# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project overview

kGPT is a full-stack AI assistant: a FastAPI backend with LangChain-based chat (auto-routing between
general LLM answers and live web search), file attachment support, and a vanilla HTML/CSS/JS frontend
served as static files by FastAPI itself (same origin, no separate build step).

Live at **https://kgpt.zrik.tech** (AWS EC2, Nginx + Let's Encrypt).
Old domain **https://k-gpt.duckdns.org** also active.

## Commands

```bash
# Setup
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env   # then set GROQ_API_KEY, JWT_SECRET_KEY, GMAIL_USER, GMAIL_APP_PASSWORD, APP_BASE_URL

# Run (auto-reload)
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

# Docker
docker-compose up -d --build
docker-compose down
```

- App UI: `http://localhost:8000/` (redirects to `login.html`)
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/health`

## Architecture

### Request flow (chat)

`backend/api/routes/chat.py` is the core of the app. Every chat message goes through:

1. **Rate limiting** (`_check_rate_limits`) — 20 req/min (in-memory bucket) + 1000/week (DB count).
2. **Conversation resolution** (`_resolve_conversation`) — finds or creates a `Conversation` row.
3. **File context** (`_file_context_preamble`) — queries `conversation_attachments`, concatenates all
   extracted text into a preamble injected before the user message.
4. **Provider selection** (`candidate_providers()`) — Groq only.
5. **Routing** (`classify_query`) — if `mode == "auto"`, LLM classifies as `general` or `web`.
6. **Mode execution** — both modes stream token-by-token via `llm.stream(...)`.
7. **Persistence** — user message saved before streaming; assistant reply saved in `finally` block.

SSE shape: `{"type":"meta",...}` → `{"type":"chunk","text":...}` → `{"type":"done"}`.

### File attachments

- New uploads go to `conversation_attachments` table (id, conversation_id, filename, context_text, uploaded_at).
- Max 10 files per conversation, max 10 MB each.
- Supported: `.jpg`, `.jpeg`, `.png`, `.pdf`, `.docx`.
- Extraction: PDF via PyMuPDF, DOCX via python-docx, images via Groq vision (`llama-4-scout-17b-16e-instruct`).
- Legacy single-attachment columns (`context`, `attachment_name`) on `Conversation` still read as fallback.

### Rate limiting

- Per-minute: in-memory `defaultdict(list)` per `user_id`, pruned each request. Shared across threads via `threading.Lock`. Not shared across workers (2 workers → effective limit ~40/min, acceptable for low traffic).
- Weekly: DB query counting `role='user'` messages in last 7 days.

### History loading (`_history_text_from_db`)

Loaded from DB (not in-memory), filtered by `user_id` + `conversation_id`, last 10 exchanges (20 rows).

### Frontend session persistence

- `sessionStorage` stores the active `conversation_id`.
- On page load: if saved conv exists in the list → restore it. Otherwise create a fresh empty conv.
- On logout: `sessionStorage` cleared → next login always starts fresh.
- `pageshow` listener forces reload on bfcache restore.

### Database (`backend/database/db.py`)

- SQLite + WAL mode (via `PRAGMA journal_mode=WAL` on connect).
- `init_db()` runs `Base.metadata.create_all` then idempotent hand-written migrations:
  - `_migrate_conversations()` — adds `conversation_id` to `chat_messages`.
  - `_migrate_users()` — adds `email_verified`, `verification_token`.
  - `_migrate_attachments()` — adds legacy `context`, `attachment_name` columns to `conversations`.
  - `_migrate_attachment_table()` — creates `conversation_attachments` table; migrates any legacy rows.

### Auth (`backend/api/auth.py`)

- JWT startup guard: exits immediately if `JWT_SECRET_KEY` is the default value.
- Registration sets `email_verified=True` directly (no email gate in practice).
- Email: Gmail SMTP via `backend/agent/email.py`.

## Deployment (AWS EC2)

- Ubuntu, Python 3.13 (deadsnakes PPA).
- Venv at `/home/ubuntu/kgpt/.venv/` — pip installs go there.
- Systemd service: `deploy/kgpt.service`.
- Nginx: `deploy/nginx.conf` — SSE buffering disabled, `client_max_body_size 10M`, `proxy_read_timeout 120s`.
- Let's Encrypt for `kgpt.zrik.tech` and `k-gpt.duckdns.org` via Certbot.

## Dependency note

`requirements.txt` pins `langchain<1.0` / `langchain-core<1.0` because `langchain.memory` was removed
in LangChain 1.0. Don't bump without migrating first.
