<p align="center">
  <h1 align="center">kGPT</h1>
  <p align="center"><strong>Your Private AI Assistant</strong></p>
  <p align="center">
    A full-stack AI chat application with intelligent web-search routing, retrieval-augmented
    document Q&amp;A, cross-conversation memory, and streaming responses — designed and implemented from scratch with FastAPI and React.
  </p>
  <p align="center">
    <a href="https://kgpt.zrik.tech">
      <img src="https://img.shields.io/badge/Live%20Demo-kgpt.zrik.tech-brightgreen?style=for-the-badge" alt="Live Demo">
    </a>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI">
    <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
    <img src="https://img.shields.io/badge/TypeScript-5-3178C6?style=flat&logo=typescript&logoColor=white" alt="TypeScript">
    <img src="https://img.shields.io/badge/PostgreSQL-async-4169E1?style=flat&logo=postgresql&logoColor=white" alt="PostgreSQL">
    <img src="https://img.shields.io/badge/Gemini-LLM-4285F4?style=flat&logo=googlegemini&logoColor=white" alt="Gemini">
    <img src="https://img.shields.io/badge/Groq-fallback-F55036?style=flat" alt="Groq">
    <img src="https://img.shields.io/badge/pgvector-RAG-336791?style=flat&logo=postgresql&logoColor=white" alt="pgvector">
    <img src="https://img.shields.io/badge/sentence--transformers-local%20embeddings-FFD21E?style=flat&logo=huggingface&logoColor=white" alt="sentence-transformers">
    <img src="https://img.shields.io/badge/Oracle%20Cloud-ARM-F80000?style=flat&logo=oracle&logoColor=white" alt="Oracle Cloud">
    <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License">
  </p>
</p>

---

<table>
  <tr>
    <td><img src="docs/screenshots/1-login.png" alt="Login page" width="100%"></td>
    <td><img src="docs/screenshots/2-chat.png" alt="Chat with RAG source citation" width="100%"></td>
  </tr>
  <tr>
    <td align="center"><em>Clean login & register</em></td>
    <td align="center"><em>Chat with a retrieval source citation badge</em></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/screenshots/3-documents.png" alt="Documents tab" width="100%"></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><em>Documents tab — scoped uploads (this chat only, or every chat)</em></td>
  </tr>
</table>

---

## Why I Built This

kGPT was built to explore production-ready AI application development end-to-end. The project focuses on intelligent LLM response streaming, automatic web-search routing, retrieval-augmented document Q&A, cross-conversation memory, and cloud deployment — rather than relying on pre-built chatbot frameworks. Every layer, from the SSE streaming protocol to the idempotent database migrations to the raw-HTTP LLM client to the chunking/embedding/retrieval pipeline, was designed and implemented from scratch (no LangChain, no chat SDKs — local `sentence-transformers` embeddings + pgvector similarity search instead).

---

## Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | **Intelligent routing** | Every message is classified by the LLM as `general` (direct answer) or `web` (live search + summarise). No mode switching needed. |
| 2 | **Streaming responses** | Token-by-token streaming over Server-Sent Events with a stop button to cancel mid-generation. |
| 3 | **Real-time web search** | Live DuckDuckGo results fetched and summarised by the LLM when needed. |
| 4 | **Unified document upload (RAG)** | One upload flow (chat paperclip or the Documents tab), with a scope choice: **this chat only** or **every conversation, forever**. PDF/DOCX/TXT/MD parsed directly; images described via Gemini/Groq vision. Every file is chunked, embedded locally (`sentence-transformers/all-MiniLM-L6-v2`, no API calls), and retrieved by pgvector cosine similarity — not dumped raw into the prompt. Answers cite which document(s) were used. |
| 5 | **Cross-conversation memory** | Past exchanges are embedded and semantically recalled from *other* conversations too, so kGPT can reference something you told it days ago in an unrelated chat. |
| 6 | **Conversation management** | Create, switch, rename, and delete chats. Session persists across page refreshes; fresh chat on login. |
| 7 | **Rich message rendering** | Markdown, syntax-highlighted code blocks with copy buttons, LaTeX math (KaTeX). |
| 8 | **Message actions** | Copy, edit & resend, regenerate last reply. |
| 9 | **Auth & security** | JWT (PyJWT) + Argon2 password hashing (via `pwdlib`). JWT secret validated at startup. |
| 10 | **Rate limiting** | 20 messages/min + 1000 messages/week per user — protects the upstream API. Uploads are separately capped at 15MB/file with bounded upload concurrency. |
| 11 | **HTTPS** | Nginx reverse proxy with a Let's Encrypt certificate (auto-renewing). |

---

## Demo

![kGPT Demo](docs/demo.gif)

Try it live at **[kgpt.zrik.tech](https://kgpt.zrik.tech)**

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, Python 3.11+ |
| **LLM (primary)** | Gemini API — `gemini-3.1-flash-lite` (chat + vision) |
| **LLM (fallback)** | Groq API — `openai/gpt-oss-120b` (chat) + `qwen/qwen3.6-27b` (vision) |
| **LLM client** | Raw `httpx` calls direct to the Groq/Gemini REST APIs — no LangChain, with multi-key rotation and automatic provider fallback |
| **Database** | PostgreSQL + async SQLAlchemy (`asyncpg`), `pgvector` extension with HNSW cosine indexes |
| **RAG / memory** | `sentence-transformers/all-MiniLM-L6-v2` (local, 384-dim, no API calls) for embeddings; custom paragraph-aware chunker; direct pgvector similarity queries — no LangChain |
| **Authentication** | JWT (PyJWT) + Argon2 (pwdlib) |
| **Web search** | DuckDuckGo via `ddgs` |
| **File extraction** | PyMuPDF (PDF), python-docx (DOCX), Gemini vision → Groq vision fallback (images) |
| **Frontend** | React 19 + TypeScript + Vite |
| **Frontend libs** | react-markdown + remark-gfm/remark-math + rehype-katex/rehype-highlight, react-router-dom |
| **Reverse proxy** | Nginx + Let's Encrypt |
| **Deployment** | Oracle Cloud (ARM Ampere, Always Free tier), systemd |
| **Containerisation** | Docker + Docker Compose available for local dev (app + Postgres) |

---

## Architecture

```
Browser (React SPA)
  │
  ├─ GET /           → FastAPI serves frontend/dist/index.html (built static SPA)
  │
  └─ POST /api/chat/stream
       │
       ├─ Auth: JWT verified
       ├─ Rate limit: 20/min + 1000/week (in-memory bucket + Postgres count)
       ├─ Retrieval: pgvector similarity search over this chat's scoped docs +
       │             every global doc, plus cross-conversation memory
       ├─ Provider: Gemini keys first, then Groq keys (candidate_providers())
       ├─ Router: LLM classifies → general or web
       │     ├─ general: LLM answers directly
       │     └─ web: DuckDuckGo → results → LLM summarises
       └─ SSE stream: meta → chunk... → done
```

**Request flow:**
1. Frontend sends `POST /api/chat/stream` with `{message, conversation_id}`
2. Rate limits checked (in-memory per-minute + Postgres weekly count)
3. Query embedded locally and matched against document chunks (this chat's scoped uploads + every global upload) and past cross-conversation memory via pgvector cosine distance; relevant matches injected as labeled context
4. LLM classifies message → `general` or `web`
5. Web mode: `run_web_search()` fetches DuckDuckGo results, prepends to prompt
6. LLM streams response token by token via SSE — raw `httpx` streaming call to whichever provider (Gemini, then Groq) is next in the fallback chain
7. User message saved before streaming; assistant reply saved in `finally` block, along with which document(s) were cited as sources

---

## Quick Start

### Prerequisites

- Python 3.11+
- Linux / macOS / Windows
- PostgreSQL (or Docker, see below)
- [Gemini API key](https://aistudio.google.com/apikey) (free tier)
- [Groq API key](https://console.groq.com/keys) (free, fallback provider)
- Node.js 18+ (to build the frontend)

### 1. Clone

```bash
git clone https://github.com/krishrakholiya32/kGPT.git
cd kGPT
```

### 2. Set up environment

```bash
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
.venv\Scripts\activate       # Windows

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `GEMINI_API_KEY` | Yes | Primary Gemini API key |
| `GEMINI_API_KEYS` | No | Comma-separated backup Gemini keys — unbounded rotation |
| `GROQ_API_KEY` | No | Groq key — fallback provider once Gemini keys are exhausted |
| `GROQ_API_KEYS` | No | Comma-separated backup Groq keys — unbounded rotation |
| `GROQ_MODEL` | No | Default: `openai/gpt-oss-120b` |
| `GROQ_VISION_MODEL` | No | Default: `qwen/qwen3.6-27b` |
| `GEMINI_MODEL` | No | Default: `gemini-3.1-flash-lite` |
| `JWT_SECRET_KEY` | Yes | Random secret — `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (`*` for local dev) |
| `RAG_TOP_K` / `RAG_MAX_DISTANCE` | No | Document retrieval tuning — defaults `5` / `0.6` |
| `MEMORY_TOP_K` / `MEMORY_MAX_DISTANCE` | No | Cross-conversation memory retrieval tuning — defaults `5` / `0.6` |

### 3. Build the frontend

```bash
cd frontend
npm install
npm run build     # outputs to frontend/dist, served by FastAPI
cd ..
```

### 4. Run

```bash
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

- App: <http://localhost:8000>
- API docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/health>

For frontend-only iteration, `cd frontend && npm run dev` runs Vite's dev server with hot reload (proxies `/api` to the backend).

---

## Docker

`docker-compose.yml` brings up both the app and a Postgres container:

```bash
docker compose up -d --build
docker compose down
```

---

## Project Structure

```
kgpt/
├── backend/
│   ├── agent/
│   │   ├── chunker.py           # Paragraph-aware text splitter for RAG (no langchain-text-splitters)
│   │   ├── embeddings.py        # Lazy-loaded local sentence-transformers embedding singleton
│   │   ├── file_extractor.py    # PDF / DOCX / image text extraction (Gemini vision → Groq vision fallback)
│   │   ├── llm.py               # Raw-httpx LLM client — Gemini/Groq, multi-key rotation, streaming
│   │   ├── retrieval.py         # pgvector document + cross-conversation memory retrieval
│   │   └── tools.py             # DuckDuckGo web search
│   ├── api/
│   │   ├── auth.py              # JWT auth, register / login (async)
│   │   ├── main.py              # FastAPI app, CORS, SPA static mount + catch-all
│   │   ├── models/
│   │   │   ├── chat.py          # Conversation, ChatMessage models
│   │   │   ├── knowledge.py     # Document, DocumentChunk, MemoryEmbedding models
│   │   │   └── user.py          # User SQLAlchemy model
│   │   └── routes/
│   │       ├── chat.py          # Chat routing, SSE streaming, conversations CRUD, rate limiting (async)
│   │       └── documents.py     # Unified upload/list/delete — chunk + embed + store, background-processed
│   └── database/
│       └── db.py                # Async engine/session, init_db, idempotent migrations (Postgres)
├── deploy/
│   ├── kgpt.service             # systemd service
│   ├── nginx.conf               # Nginx reverse proxy with SSE support
│   └── setup.sh                 # bootstrap script
├── frontend/                    # React 19 + TypeScript + Vite
│   ├── src/
│   │   ├── api/client.ts        # Typed fetch wrapper
│   │   ├── auth/AuthContext.tsx # Auth state/provider
│   │   ├── components/
│   │   │   ├── DocumentPanel.tsx # Documents tab — upload, scope toggle, per-doc scope badges
│   │   │   └── ...              # Markdown, Artifact, Toast renderers
│   │   ├── pages/
│   │   │   ├── Chat.tsx         # Sidebar, message thread, SSE streaming, scoped file upload
│   │   │   └── Login.tsx        # Login + register
│   │   └── App.tsx              # Router
│   ├── dist/                    # Built SPA — served directly by FastAPI
│   └── vite.config.ts
├── .env.example
├── docker-compose.yml           # App + Postgres containers (local dev)
├── Dockerfile
└── requirements.txt
```

---

## API Reference

All endpoints except auth require `Authorization: Bearer <token>`.

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register` | Register (verified at registration — no email step) |
| `POST` | `/api/auth/login` | Login with email + password |
| `GET`  | `/api/auth/me` | Current user |

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST`   | `/api/chat/stream` | Stream a reply via SSE (primary) |
| `POST`   | `/api/chat` | Non-streaming fallback |
| `GET`    | `/api/chat/conversations` | List conversations |
| `POST`   | `/api/chat/conversations` | Create conversation |
| `GET`    | `/api/chat/conversations/{id}/messages` | Get messages |
| `PATCH`  | `/api/chat/conversations/{id}` | Rename conversation |
| `DELETE` | `/api/chat/conversations/{id}` | Delete conversation (cascades its scoped documents) |

### Documents (RAG)

| Method   | Endpoint | Description |
|----------|----------|-------------|
| `POST`   | `/api/documents/upload` | Upload a file (PDF/DOCX/TXT/MD/JPG/PNG), optional `conversation_id` to scope it to one chat instead of every chat |
| `GET`    | `/api/documents` | List your documents, with scope + processing status |
| `DELETE` | `/api/documents/{id}` | Delete a document (cascades its chunks) |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Status, mode, active provider |

---

## Deployment

Deployed on **Oracle Cloud** (ARM Ampere, Always Free tier) with:
- **systemd** service (`deploy/kgpt.service`) — `Restart=always`
- **Nginx** reverse proxy with SSE buffering disabled and `client_max_body_size 10M`
- **Let's Encrypt** SSL via Certbot (auto-renewing)
- **PostgreSQL** running natively on the same instance (not containerized in production) with the `pgvector` extension enabled
- Frontend is built (`npm run build`) and the resulting `frontend/dist/` served directly by FastAPI — no separate web server or Node process in production

---

## Roadmap

- [ ] Multi-model support (OpenAI, local Ollama)
- [ ] Conversation sharing via public links
- [ ] Voice input / output
- [ ] Redis-backed rate limiting for multi-worker accuracy

---

## License

[MIT](LICENSE)

---

<p align="center">
  Designed and implemented from scratch with FastAPI · React · Gemini · Groq · pgvector · Deployed on Oracle Cloud
</p>
