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
  <p align="center">
    <a href="https://k-gpt.duckdns.org"><strong>🌐 Live Demo → k-gpt.duckdns.org</strong></a>
  </p>
</p>

---

## ✨ Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | 🧭 **Automatic routing** | Classifies each message as `general` (direct LLM answer) or `web` (live DuckDuckGo search + LLM summary). |
| 2 | ⚡ **Streaming responses** | Answers stream token by token over Server-Sent Events, with a stop button to cancel mid-generation. |
| 3 | 🌐 **Real-time web search** | Live results via DuckDuckGo (`ddgs`), summarised by the LLM. |
| 4 | 💬 **Multiple conversations** | Create, switch, rename (double-click the title), and delete separate chat threads — each with its own context. |
| 5 | 🧠 **Conversation memory** | Full history persisted in the database; "continue" after an interrupted stream resumes the correct topic. |
| 6 | 🎨 **Rich rendering** | Markdown, syntax-highlighted code blocks with copy buttons, LaTeX math (KaTeX), and a live preview panel for HTML/SVG artifacts. |
| 7 | ✏️ **Message actions** | Copy any message; edit and resend your own prompts; regenerate the last reply. |
| 8 | 🔐 **Auth + email verification** | JWT-based auth with Argon2 password hashing; new accounts require email verification via Resend before they can log in. |
| 9 | 🔒 **HTTPS** | Deployed behind Nginx with a Let's Encrypt certificate (auto-renewing). |
| 10 | 🐳 **Docker deployment** | One-command deployment with Docker Compose. |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, Python 3.11+ |
| **LLM framework** | LangChain (0.3.x line) |
| **LLM** | Groq (`llama-3.3-70b-versatile`, configurable) |
| **Database** | SQLite + SQLAlchemy |
| **Authentication** | JWT (PyJWT) + Argon2 (pwdlib) |
| **Email** | Resend (transactional email for verification) |
| **Web search** | DuckDuckGo via `ddgs` |
| **Frontend** | Vanilla HTML / CSS / JS (served as static files by FastAPI) |
| **Frontend libraries** | marked + DOMPurify (Markdown), highlight.js (code), KaTeX (math) |
| **Reverse proxy** | Nginx + Let's Encrypt (HTTPS) |
| **Containerisation** | Docker + Docker Compose |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- A **Groq** API key (free) — <https://console.groq.com/keys>
- A **Resend** API key (free, 100 emails/day) — <https://resend.com> *(optional — skip for local dev without email verification)*

### 1. Clone

```bash
git clone https://github.com/krishrakholiya32/kGPT.git
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

Edit `.env` — the minimum required fields:

| Variable | What to set |
|----------|-------------|
| `GROQ_API_KEY` | Your Groq API key |
| `JWT_SECRET_KEY` | A random secret — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `RESEND_API_KEY` | Your Resend key (leave blank to skip email verification locally) |
| `APP_BASE_URL` | Base URL of your app (e.g. `http://localhost:8000`) |

### 5. Run

```bash
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

- App UI: <http://localhost:8000/> (redirects to the login page)
- Interactive API docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/health>

The SQLite database is created automatically on first run.

---

## 🐳 Docker Deployment

```bash
docker-compose up -d --build
```

Builds and starts a single `kgpt-app` service on port `8000`, with the `database/` directory mounted as a volume so data persists across restarts. Reads configuration from your `.env` file.

```bash
docker-compose down
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | — | Groq API key (**required**). |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq chat model. |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature. |
| `JWT_SECRET_KEY` | `change-me-in-production` | Secret used to sign JWTs — **set this**. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token lifetime in minutes (default 24 h). |
| `DATABASE_URL` | `sqlite:///./database/data.db` | SQLAlchemy database URL. |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated); restrict in production. |
| `RESEND_API_KEY` | — | Resend API key for verification emails. Leave blank to disable. |
| `RESEND_FROM_EMAIL` | `onboarding@resend.dev` | Sender address for verification emails. |
| `APP_BASE_URL` | `http://localhost:8000` | Public URL of your app (used in email verification links). |

---

## 📁 Project Structure

```
kgpt/
├── backend/
│   ├── agent/
│   │   ├── llm.py            # LLM factory: Groq with candidate_providers fallback
│   │   ├── email.py          # Resend integration for verification emails
│   │   └── tools.py          # Web search via DuckDuckGo (ddgs)
│   ├── api/
│   │   ├── main.py           # FastAPI app, CORS, startup, static frontend mount
│   │   ├── auth.py           # JWT auth, register/login/verify-email/resend-verification
│   │   ├── models/
│   │   │   ├── user.py       # User model (email_verified, verification_token)
│   │   │   └── chat.py       # Conversation & ChatMessage models + schemas
│   │   └── routes/
│   │       └── chat.py       # Chat (auto-routing), SSE streaming, conversations CRUD
│   └── database/
│       └── db.py             # SQLAlchemy engine, session, init_db, migrations
├── frontend/
│   ├── index.html            # Main chat UI
│   ├── login.html            # Login / register (email-based login + verify pending screen)
│   ├── verify.html           # Email verification landing page
│   ├── css/style.css
│   └── js/
│       └── chat.js
├── deploy/
│   ├── kgpt.service          # systemd service file
│   ├── nginx.conf            # Nginx reverse proxy config
│   └── setup.sh              # EC2 setup script
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

All endpoints except register/login/verify require an `Authorization: Bearer <token>` header.

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register` | Register a new user; sends verification email; returns a JWT. |
| `POST` | `/api/auth/login` | Login with email + password; returns a JWT. |
| `POST` | `/api/auth/verify-email` | Verify email with token from the verification link. |
| `POST` | `/api/auth/resend-verification` | Resend the verification email. |
| `GET`  | `/api/auth/check` | Check username/email availability (used for inline validation). |
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

- **Never commit your real `.env`.** It is gitignored; keep it that way, and rotate any key that has been shared.
- Set a strong, unique `JWT_SECRET_KEY` before deploying.
- CORS defaults to `*` for local development — restrict `ALLOWED_ORIGINS` in production.
- The app is served over HTTPS in production with a Let's Encrypt certificate that auto-renews via Certbot.

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
  Built with FastAPI, LangChain, and Groq · Deployed on AWS EC2 with Nginx + Let's Encrypt
</p>
