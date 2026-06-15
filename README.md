<p align="center">
  <h1 align="center">🧠 kGPT</h1>
  <p align="center">
    <strong>A multi-tool AI agent — RAG, Web Search, SQL, Code Execution & Image Understanding</strong>
  </p>
  <p align="center">
    A full-stack AI assistant with a single smart input box. kGPT automatically routes
    each message to the right tool — your documents, the live web, your database, a Python
    runtime, an image model, or a plain chat answer — and streams the response back token by token.
  </p>
</p>

---

## ✨ Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | 🧭 **Automatic tool routing** | One endpoint classifies each message and picks the right tool: `general`, `rag`, `web`, `sql`, `code`, or `vision`. You can also force a mode. |
| 2 | 🔁 **Pluggable LLM providers** | Run on **Groq** (fast, free tier), **Google Gemini**, or a local **Ollama** model — switch with a single env var, no code changes. |
| 3 | ⚡ **Streaming responses** | Answers stream in token by token over Server-Sent Events, with a stop button to cancel mid-generation. |
| 4 | 📄 **RAG document chat** | Upload **PDF, DOCX, CSV, TXT, MD, JSON, HTML, Excel (XLSX), PowerPoint (PPTX)**, and many code/text formats — or ingest a URL — and ask questions answered from their contents. |
| 5 | 🖼️ **Image understanding** | Attach up to **5 images** in one message and ask about them, powered by a Groq vision model. |
| 6 | 🌐 **Real-time web search** | Live results via DuckDuckGo (`ddgs`), summarized by the LLM. |
| 7 | 🗄️ **SQL generation & execution** | Natural-language questions are turned into SQL and run against the app database via a LangChain SQL agent. |
| 8 | 💻 **Code execution** | Generates and runs Python in a REPL tool to compute answers, not just print code. |
| 9 | 💬 **Multiple conversations** | Create, switch, rename (double-click the title), and delete separate chat threads — each with its own context. |
| 10 | 🧠 **Conversation memory** | Per-conversation sliding-window memory for context-aware follow-ups; full history persisted in the database. |
| 11 | 🎨 **Rich rendering** | Markdown, syntax-highlighted code blocks with copy buttons, LaTeX math (KaTeX), and a live preview panel for HTML/SVG artifacts. |
| 12 | ✏️ **Message actions** | Copy any message; edit and resend your own prompts. |
| 13 | 🔐 **User authentication** | JWT-based auth with Argon2 password hashing. |
| 14 | 📊 **Usage dashboard** | Per-user stats: total messages, tool-usage breakdown, and 7-day activity. |
| 15 | 🐳 **Docker deployment** | One-command deployment with Docker Compose. |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, Python 3.11 |
| **LLM framework** | LangChain (0.3.x line) |
| **LLM (recommended)** | Groq (`llama-3.3-70b-versatile`, configurable) |
| **LLM (alternatives)** | Google Gemini (`gemini-2.0-flash`) / local Ollama |
| **Vision** | Groq `meta-llama/llama-4-scout-17b-16e-instruct` |
| **Vector database** | ChromaDB |
| **Embeddings** | Sentence Transformers (`all-MiniLM-L6-v2`, CPU) |
| **Database** | SQLite + SQLAlchemy |
| **Authentication** | JWT (PyJWT) + Argon2 (pwdlib) |
| **Web search** | DuckDuckGo via `ddgs` |
| **Document parsing** | pypdf, docx2txt, pandas, openpyxl (Excel), python-pptx (PowerPoint) |
| **Code / SQL tools** | LangChain Python REPL + SQLDatabase toolkit |
| **Frontend** | Vanilla HTML / CSS / JS (served as static files by FastAPI) |
| **Frontend libraries** | marked + DOMPurify (Markdown), highlight.js (code), KaTeX (math) |
| **Containerization** | Docker + Docker Compose |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- An LLM provider key:
  - **Groq** (recommended, free) — <https://console.groq.com/keys>
  - or **Google Gemini** — <https://aistudio.google.com/apikey>
  - or **Ollama** installed locally with a model pulled (e.g. `ollama pull llama3`)

### 1. Clone

```bash
git clone https://github.com/your-username/kgpt.git
cd kgpt
```

### 2. Create an environment

```bash
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
.venv\Scripts\activate       # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Then edit `.env`: set a strong `JWT_SECRET_KEY`, and configure your provider — for the
recommended setup, set `LLM_PROVIDER=groq` and `GROQ_API_KEY=...`. Generate a secret with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Run

```bash
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

- App UI: <http://localhost:8000/> (redirects to the login page first)
- Interactive API docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/health>

The SQLite database, vector store, and upload directories are created automatically on first run.

---

## 🐳 Docker Deployment

```bash
docker-compose up -d --build
```

This builds and starts a single `kgpt-app` service on port `8000`, with `vectorstore/`,
`documents/`, and `database/` mounted as volumes so data persists across restarts. It reads
configuration from your `.env` file.

Stop it with:

```bash
docker-compose down
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODE` | `online` | `online` = Gemini, `offline` = Ollama. Ignored if `LLM_PROVIDER` is set. |
| `LLM_PROVIDER` | _(empty)_ | Force a provider: `groq`, `gemini`, or `ollama`. |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature. |
| `GROQ_API_KEY` | — | Groq key (required for `groq` provider and for image understanding). |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq chat model. |
| `GROQ_VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq vision model for images. |
| `GEMINI_API_KEY` | — | Google Gemini key (for `gemini` provider). |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name. |
| `OLLAMA_MODEL` | `llama3` | Ollama model (offline mode). |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL. |
| `JWT_SECRET_KEY` | `change-me-in-production` | Secret used to sign JWTs — **set this**. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token lifetime in minutes. |
| `CHROMA_PERSIST_DIR` | `./vectorstore` | Where ChromaDB persists embeddings. |
| `UPLOAD_DIR` | `./documents` | Where uploaded files are stored. |
| `DATABASE_URL` | `sqlite:///./database/data.db` | SQLAlchemy database URL. |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated); restrict in production. |

---

## 📁 Project Structure

```
kgpt/
├── backend/
│   ├── agent/
│   │   ├── llm.py            # LLM factory: Groq / Gemini / Ollama + vision builder
│   │   ├── memory.py         # Per-conversation sliding-window memory
│   │   ├── rag.py            # Chroma RAG: ingest, embed, retrieve (incl. Excel/PPTX loaders)
│   │   └── tools.py          # Web search (ddgs), SQL agent, Python REPL
│   ├── api/
│   │   ├── main.py           # FastAPI app, CORS, startup, static frontend mount
│   │   ├── auth.py           # JWT auth + register / login / me
│   │   ├── models/
│   │   │   ├── user.py       # User & UsageStat models + schemas
│   │   │   └── chat.py       # Conversation & ChatMessage models + request/response schemas
│   │   └── routes/
│   │       ├── chat.py       # Chat (auto-routing), streaming, conversations, history
│   │       ├── documents.py  # Upload / URL ingest / list
│   │       └── dashboard.py  # Usage stats
│   └── database/
│       └── db.py             # SQLAlchemy engine, session, init_db, migrations
├── frontend/
│   ├── index.html            # Main app — Chat + Dashboard
│   ├── login.html            # Login / register
│   ├── css/style.css
│   └── js/
│       ├── chat.js
│       └── dashboard.js
├── vectorstore/              # ChromaDB persistence (gitignored)
├── documents/                # Uploaded documents (gitignored)
├── database/                 # SQLite database (gitignored)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## 📡 API Endpoints

All endpoints except register/login require an `Authorization: Bearer <token>` header.

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register` | Register a new user; returns a JWT. |
| `POST` | `/api/auth/login` | OAuth2 password login; returns a JWT. |
| `GET`  | `/api/auth/me` | Get the current user. |

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST`   | `/api/chat` | Send a message (non-streaming). |
| `POST`   | `/api/chat/stream` | Send a message; streams the reply via SSE. Body supports `message`, `mode`, `images` (list), and `conversation_id`. |
| `GET`    | `/api/chat/history` | Recent messages for the user. |
| `DELETE` | `/api/chat/history` | Clear history and in-memory context. |
| `GET`    | `/api/chat/conversations` | List the user's conversations. |
| `POST`   | `/api/chat/conversations` | Create a new conversation. |
| `GET`    | `/api/chat/conversations/{id}/messages` | Messages in a conversation. |
| `PATCH`  | `/api/chat/conversations/{id}` | Rename a conversation. |
| `DELETE` | `/api/chat/conversations/{id}` | Delete a conversation. |

### Documents (RAG)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/documents/upload` | Upload and ingest a file. |
| `POST` | `/api/documents/url` | Ingest a web URL. |
| `GET`  | `/api/documents` | List ingested files. |

### Dashboard & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/dashboard/stats` | Usage statistics for the current user. |
| `GET` | `/api/health` | Service status, mode, and active provider. |

---

## 🔒 Security Notes

- **Never commit your real `.env`.** It's gitignored; keep it that way, and rotate any key that has been shared.
- Set a strong, unique `JWT_SECRET_KEY` before deploying.
- CORS defaults to `*` for local development — restrict `ALLOWED_ORIGINS` for production.

---

## 📝 License

Released under the **MIT License**.

```
MIT License

Copyright (c) 2026 kGPT

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

<p align="center">
  Built with FastAPI, LangChain, and Groq.
</p>