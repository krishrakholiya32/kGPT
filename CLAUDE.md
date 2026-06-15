# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

kGPT is a full-stack multi-tool AI agent: a FastAPI backend (LangChain-based agent with RAG, web
search, SQL, code execution, vision) and a vanilla HTML/CSS/JS frontend served as static files by
FastAPI itself (same origin, no separate build step).

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
   message into one of `general | rag | web | sql | code` (vision is detected separately, before
   classification, based on whether images were attached). The classifier prompt is deliberately
   strict about *not* routing real-world counting questions to `sql`.
4. **Mode execution** (`_run_mode` for non-streaming, `_build_stream_prompt` + `_run_mode` for
   streaming):
   - `general` / `web` — plain LLM prompt (web prepends DuckDuckGo results); these stream
     token-by-token via `llm.stream(...)`.
   - `rag` — `get_rag_chain()` (Chroma `RetrievalQA`), computed fully then emitted as one chunk.
   - `sql` / `code` — `run_sql_agent` / `run_code_execution`, both backed by the same
     `create_agent_executor` ReAct agent (LangChain SQL toolkit / Python REPL tool), computed
     fully then emitted as one chunk.
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
- `build_vision_llm()` is always Groq (`GROQ_VISION_MODEL`, default
  `meta-llama/llama-4-scout-17b-16e-instruct`), independent of the chat `LLM_PROVIDER`. Image
  understanding therefore requires `GROQ_API_KEY` even if the chat provider is Gemini.

### RAG (`backend/agent/rag.py`)

- Singletons: `get_embeddings()` (`HuggingFaceEmbeddings`, `all-MiniLM-L6-v2`, CPU) and
  `get_vectorstore()` (Chroma, collection `kgpt_documents`, persisted at `CHROMA_PERSIST_DIR`).
  Documents from **all** users share this one collection — there is no per-user isolation.
- `_LOADER_MAP` dispatches by a normalized `file_type` string (`pdf`, `docx`, `csv`, `txt`, `xlsx`,
  `pptx`, ...). `_ExcelLoader` and `_PptxLoader` are hand-rolled (openpyxl / python-pptx) since
  LangChain has no built-in loaders for those. `backend/api/routes/documents.py` owns the much
  larger `EXTENSION_TYPE_MAP` (covers many code/text extensions → `txt`) and maps extensions to
  these `file_type` strings before calling `ingest_document`.
- All ingestion goes through one `RecursiveCharacterTextSplitter` (chunk_size=1000, overlap=200).

### Agent tools (`backend/agent/tools.py`)

- `create_agent_executor(llm)` builds a single ReAct agent (`create_react_agent` +
  `AgentExecutor`, `max_iterations=10`) wired with: DuckDuckGo search, a Python REPL
  (`langchain_experimental`), and the SQL toolkit over the app's own database
  (`SQLDatabaseToolkit` against `DATABASE_URL`). Both `run_sql_agent` and `run_code_execution`
  reuse this same executor — the difference is only the framing of the input string ("Using the
  database, answer: ..." vs "Write and run Python code to: ...").
- `run_web_search` is independent of the agent — it calls `ddgs`/`duckduckgo_search` directly
  (with the LangChain tool as a fallback) and is used for both the `web` chat mode and as a tool
  inside the ReAct agent.
- The SQL agent operates on the **app's own** SQLite database (users, chat_messages,
  conversations, usage_stats) — this is intentional per the classifier prompt, not a general data
  warehouse.

### Database (`backend/database/db.py`, `backend/api/models/`)

- SQLAlchemy + SQLite (`DATABASE_URL`, default `sqlite:///./database/data.db`).
- `init_db()` runs `Base.metadata.create_all` then `_migrate_conversations()`, a hand-written,
  idempotent migration that adds `chat_messages.conversation_id` to pre-existing DBs and buckets
  any orphaned messages into a synthetic "Imported chat" conversation. There is no Alembic —
  schema changes need a similar hand-written, repeat-safe migration added here.
- Models: `User`, `UsageStat` (`backend/api/models/user.py`); `ChatMessage`, `Conversation`
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
- `frontend/login.html` (auth) and `frontend/index.html` (chat + dashboard) are separate pages.
  `frontend/js/chat.js`, `dashboard.js`, `documents.js` correspond to the chat UI, usage dashboard,
  and document upload/list UI respectively.

## Environment variables

Config is read via `os.getenv` scattered across modules (not a single settings object) — see
`.env.example` for the full list with defaults. The most relevant for development:

- `LLM_PROVIDER` (`groq` recommended, or `gemini`) + matching API key (`GROQ_API_KEY` /
  `GEMINI_API_KEY`).
- `JWT_SECRET_KEY` — must be set to something real; generate with
  `python -c "import secrets; print(secrets.token_hex(32))"`.
- `CHROMA_PERSIST_DIR`, `UPLOAD_DIR`, `DATABASE_URL` — all default to local gitignored
  directories (`vectorstore/`, `documents/`, `database/`) created automatically on startup.

## Dependency note

`requirements.txt` deliberately pins `langchain<1.0` / `langchain-core<1.0` because this codebase
uses legacy APIs removed in LangChain 1.0 (`langchain.chains.RetrievalQA`,
`langchain.memory.ConversationBufferWindowMemory`, `langchain.agents.create_react_agent`). Don't
bump these without migrating those call sites first (to `create_retrieval_chain` +
LangGraph-based memory).
