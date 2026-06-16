<p align="center">
  <h1 align="center">🧠 kGPT</h1>
  <p align="center">
    <strong>A private AI assistant with general chat and real-time web search</strong>
  </p>
  <p align="center">
    A full-stack AI assistant with a single smart input box. kGPT automatically routes
    each message — answering directly from the LLM, or fetching live web results first —
    and streams the response back token by token.
  </p>
</p>

---

## ✨ Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | 🧭 **Automatic routing** | One endpoint classifies each message as `general` (direct LLM answer) or `web` (live DuckDuckGo search + LLM summary). |
| 2 | 🔁 **Pluggable LLM providers** | Run on **Groq** (fast, free tier) or **Google Gemini** — switch with a single env var, no code changes. Falls back automatically if the preferred provider fails. |
| 3 | ⚡ **Streaming responses** | Answers stream in token by token over Server-Sent Events, with a stop button to cancel mid-generation. |
| 4 | 🌐 **Real-time web search** | Live results via DuckDuckGo (`ddgs`), summarized by the LLM. |
| 5 | 💬 **Multiple conversations** | Create, switch, rename (double-click the title), and delete separate chat threads — each with its own context. |
| 6 | 🧠 **Conversation memory** | Per-conversation sliding-window memory for context-aware follow-ups; full history persisted in the database. |
| 7 | 🎨 **Rich rendering** | Markdown, syntax-highlighted code blocks with copy buttons, LaTeX math (KaTeX), and a live preview panel for HTML/SVG artifacts. |
| 8 | ✏️ **Message actions** | Copy any message; edit and resend your own prompts; regenerate the last reply. |
| 9 | 🔐 **User authentication** | JWT-based auth with Argon2 password hashing. |
| 10 | 🐳 **Docker deployment** | One-command deployment with Docker Compose. |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, Python 3.11 |
| **LLM framework** | LangChain (0.3.x line) |
| **LLM (recommended)** | Groq (`llama-3.3-70b-versatile`, configurable) |
| **LLM (alternative)** | Google Gemini (`gemini-2.0-flash`) |
| **Database** | SQLite + SQLAlchemy |
| **Authentication** | JWT (PyJWT) + Argon2 (pwdlib) |
| **Web search** | DuckDuckGo via `ddgs` |
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

The SQLite database is created automatically on first run.

---

## 🐳 Docker Deployment

```bash
docker-compose up -d --build
```

This builds and starts a single `kgpt-app` service on port `8000`, with the `database/`
directory mounted as a volume so data persists across restarts. It reads configuration
from your `.env` file.

Stop it with:

```bash
docker-compose down
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODE` | `online` | Informational label reported by `/api/health`. |
| `LLM_PROVIDER` | _(empty)_ | Force a provider: `groq` or `gemini`. |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature. |
| `GROQ_API_KEY` | — | Groq key (required for `groq` provider). |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq chat model. |
| `GEMINI_API_KEY` | — | Google Gemini key (for `gemini` provider). |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name. |
| `JWT_SECRET_KEY` | `change-me-in-production` | Secret used to sign JWTs — **set this**. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token lifetime in minutes. |
| `DATABASE_URL` | `sqlite:///./database/data.db` | SQLAlchemy database URL. |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated); restrict in production. |

---

## 📁 Project Structure

```
kgpt/
├── backend/
│   ├── agent/
│   │   ├── llm.py            # LLM factory: Groq / Gemini with automatic fallback
│   │   ├── memory.py         # Per-conversation sliding-window memory
│   │   └── tools.py          # Web search via DuckDuckGo (ddgs)
│   ├── api/
│   │   ├── main.py           # FastAPI app, CORS, startup, static frontend mount
│   │   ├── auth.py           # JWT auth + register / login / me
│   │   ├── models/
│   │   │   ├── user.py       # User model + schemas
│   │   │   └── chat.py       # Conversation & ChatMessage models + request/response schemas
│   │   └── routes/
│   │       └── chat.py       # Chat (auto-routing), streaming, conversations CRUD
│   └── database/
│       └── db.py             # SQLAlchemy engine, session, init_db, migrations
├── frontend/
│   ├── index.html            # Main app — Chat UI
│   ├── login.html            # Login / register
│   ├── css/style.css
│   └── js/
│       └── chat.js
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
| `POST`   | `/api/chat/stream` | Send a message; streams the reply via SSE. Body: `message`, `mode`, `conversation_id`. |
| `GET`    | `/api/chat/conversations` | List the user's conversations. |
| `POST`   | `/api/chat/conversations` | Create a new conversation. |
| `GET`    | `/api/chat/conversations/{id}/messages` | Messages in a conversation. |
| `PATCH`  | `/api/chat/conversations/{id}` | Rename a conversation. |
| `DELETE` | `/api/chat/conversations/{id}` | Delete a conversation. |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
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
