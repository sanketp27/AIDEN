<div align="center">

```
    ___    _________  _______   __
   /   |  /  _/ __ \/ ____/ | / /
  / /| |  / // / / / __/ /  |/ /
 / ___ |_/ // /_/ / /___/ /|  /
/_/  |_/___/_____/_____/_/ |_/
```

### **AI Intelligent Daily Executive Navigator**
*A production-grade, multi-agent productivity system powered by Google Gemini*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Google Gemini](https://img.shields.io/badge/Gemini-2.0_Flash_+_Pro-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)
[![MongoDB](https://img.shields.io/badge/MongoDB-7.0-47A248?style=for-the-badge&logo=mongodb&logoColor=white)](https://mongodb.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-F59E0B?style=for-the-badge)](LICENSE)

<br/>

> **AIDEN** is your always-on AI chief of staff. It routes your voice, text, and images to a squad of specialized AI agents, manages your tasks with ML-powered scheduling intelligence, monitors your inbox, tracks your habits, and delivers a structured daily briefing — all from a single, elegant interface.

<br/>

---

</div>

## ✦ &nbsp;What AIDEN Does

AIDEN is not a single chatbot. It is an **orchestrated squad of specialized AI agents** that collaborate behind the scenes to understand your intent, route it to the right specialist, and act — all in one conversation.

<br/>

```
  Your Input  (text / voice / image)
          │
          ▼
  ┌─────────────────────────┐
  │   AIDEN  ORCHESTRATOR   │  ← Gemini 2.0 Pro — routes every request
  └──────────┬──────────────┘
             │
     ┌───────┼──────────────────────────────────┐
     ▼       ▼            ▼          ▼          ▼
  ┌──────┐ ┌──────────┐ ┌────────┐ ┌───────┐ ┌────────┐
  │ Task │ │ Calendar │ │  Note  │ │ Voice │ │ Vision │
  │Master│ │   Bot    │ │Keeper  │ │ Agent │ │ Agent  │
  └──────┘ └──────────┘ └────────┘ └───────┘ └────────┘
     │            │           │
     ▼            ▼           ▼
  MongoDB     MCP Server   ChromaDB
  (tasks)    (calendar)  (vector search)
```

<br/>

---

## 🧩 &nbsp;Core Features

<br/>

### 🤖 &nbsp;Multi-Agent Intelligence

| Agent | Responsibility | Example Triggers |
|-------|---------------|-----------------|
| **Orchestrator** | Intent routing, multi-step coordination | Every message |
| **TaskMaster** | Create, update, complete, prioritize tasks | *"remind me to"*, *"todo"*, *"P1"* |
| **CalendarBot** | Schedule meetings, check free slots | *"calendar"*, *"schedule"*, *"meeting"* |
| **NoteKeeper** | Semantic note creation, vector search | *"note"*, *"write down"*, *"remember"* |
| **VoiceAgent** | Audio transcription → intent → action | Mic button, Telegram voice notes |
| **VisionAgent** | Image classification + data extraction | Image upload |

<br/>

### 📋 &nbsp;Task Management

- **Priority tiers**: P0 (critical) → P1 → P2 → P3 with weighted scoring
- **Recurring tasks**: daily, weekly, monthly, weekdays, weekends with configurable intervals
- **Habit tracking**: current streak, longest streak, 30-day completion rate, full history
- **Per-user isolation**: every user's tasks live in their own namespaced MongoDB collection
- **Status lifecycle**: `todo` → `in_progress` → `completed` / `cancelled`

<br/>

### 📊 &nbsp;ML Workload Forecaster

> Zero LLM calls. Pure math and algorithms.

```
1. Feature Extraction   ── task vectors: priority × urgency decay × due-date proximity
2. EWMA Completion Rate ── personalised daily capacity, adapts to user's actual pace
3. Daily Load Scoring   ── weighted sum of all open tasks per day
4. Overload Detection   ── flags days where load > personal capacity threshold
5. DP Rescheduling      ── 0/1 Knapsack assigns overloaded tasks to nearest free slot
```

Delivers a 14-day workload heatmap, overloaded-day warnings, and a plain-English reschedule plan.

<br/>

### 📧 &nbsp;Gmail Integration

- **OAuth2 flow**: click *Connect Gmail* in Settings — browser redirect, no console commands
- **Background polling**: APScheduler checks inbox every 15 min (configurable)
- **Automatic task extraction**: action-items from emails become tasks with priority + due date
- **Idempotency**: processed email IDs logged in MongoDB to prevent duplicates
- **Scopes**: `gmail.readonly` + `gmail.modify`

<br/>

### 📸 &nbsp;Vision Analysis — 8 Image Types

| Image Type | Extracts |
|-----------|---------|
| 📋 **Whiteboard** | Action items, diagrams, meeting notes |
| ✍️ **Handwritten** | Transcribed tasks with inferred priorities |
| 📄 **Document** | Title, content, tables, deadlines |
| 🖥️ **Screenshot** | UI elements, error messages, text blocks |
| 💼 **Business Card** | Name, email, phone, company, title |
| 📊 **Slide** | Bullet points, headlines, data |
| 🧾 **Receipt** | Vendor, amount, line items, date |
| 📷 **Photo** | General description, visible text, context |

<br/>

### 🎤 &nbsp;Voice Input

- **Browser recording**: click mic, speak, release — transcribed by Gemini 2.5 Flash TTS
- **Intent detection**: voice parsed into structured commands and routed to the correct agent
- **Telegram voice notes**: send a voice message to your AIDEN bot — it transcribes and acts
- No Google Cloud credentials required — uses Gemini API only

<br/>

### 🌅 &nbsp;Daily Briefing

Generated fresh each morning — no LLM calls, pure DB queries:

```
1. Today's tasks     — due today or overdue, sorted P0 → P3
2. High-priority     — P0/P1 tasks due within 7 days
3. Workload risk     — ML forecaster warning if today is overloaded
4. Habit streaks     — active habits with current streak + last completed
5. Suggested focus   — top 3 tasks ranked by urgency score
```

<br/>

### 🤖 &nbsp;Telegram Bot

Link your AIDEN account and interact from anywhere:

```
/start <jwt>    — Link Telegram to your AIDEN account
/tasks          — List open tasks
/note <text>    — Quick note creation
🎤 Voice note   — Transcribed and routed to orchestrator
💬 Any text     — Full AIDEN orchestrator response
```

<br/>

---

## 🛠️ &nbsp;Tech Stack

<br/>

<div align="center">

### Intelligence Layer

| Component | Technology |
|-----------|-----------|
| Orchestration & Chat | Google Gemini 2.0 Pro |
| Task / Note / Voice Agents | Google Gemini 2.0 Flash |
| Vision Analysis | Google Gemini 2.0 Flash Vision |
| Voice Transcription | Google Gemini 2.5 Flash TTS Preview |
| Agent Framework | Google ADK 1.x |
| Tool Integration | MCP (Model Context Protocol) |

### Backend Layer

| Component | Technology |
|-----------|-----------|
| REST API + WebSocket | FastAPI 0.115 + Uvicorn |
| Authentication | python-jose (JWT) + passlib (bcrypt) |
| Background Jobs | APScheduler |
| HTTP Client | httpx (async) |
| Config Management | pydantic-settings |
| Structured Logging | structlog |

### Data Layer

| Component | Technology |
|-----------|-----------|
| Primary Database | MongoDB 7 + motor (async driver) |
| Vector / Semantic Search | ChromaDB (local persistent library) |
| JWT Token Store | MongoDB `jwt_tokens` with TTL index |
| OAuth Credentials | MongoDB `user_credentials` (encrypted) |
| Agent Sessions | MongoDB `adk_sessions` |

### Frontend & Infrastructure

| Component | Technology |
|-----------|-----------|
| UI | Vanilla HTML / CSS / JS (single file) |
| Typography | Syne + JetBrains Mono + Lora |
| Containerization | Docker + Docker Compose |
| Telegram Integration | python-telegram-bot 21 |
| Resilience | tenacity (retry logic) |

</div>

<br/>

---

## ⚡ &nbsp;Quick Start

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | [python.org](https://python.org) |
| MongoDB | 7.0 | Local install **or** Docker |
| Gemini API Key | — | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — free tier available |

<br/>

---

## 🍎 &nbsp;macOS

```bash
# 1 — Clone
git clone https://github.com/your-org/aiden.git && cd aiden

# 2 — First-time setup  (creates .env, installs deps, generates JWT secret)
chmod +x setup.sh start.sh
./setup.sh

# 3 — Start  (local MongoDB)
./start.sh

# 3 — Start  (Docker MongoDB)
./start.sh --docker

# 4 — Stop
./start.sh --stop
```

Browser opens automatically at **http://localhost:3000**

<br/>

---

## 🐧 &nbsp;Linux

```bash
# Install Python 3.11 if needed
sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip -y

# Clone
git clone https://github.com/your-org/aiden.git && cd aiden

# First-time setup
chmod +x setup.sh start.sh
./setup.sh

# Start with Docker MongoDB (recommended on Linux)
./start.sh --docker

# Or with a locally running MongoDB
sudo systemctl start mongod
./start.sh
```

> **WSL2**: Use `./start.sh --docker` with Docker Desktop (WSL2 backend enabled).

<br/>

---

## 🪟 &nbsp;Windows (PowerShell)

```powershell
# Step 1 — Allow scripts  (run once as Administrator)
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

# Step 2 — Clone
git clone https://github.com/your-org/aiden.git; cd aiden

# Step 3 — Start  (first run auto-creates .env and installs deps)
.\start.ps1

# With Docker MongoDB
.\start.ps1 -Docker

# Force reinstall dependencies
.\start.ps1 -Setup

# Stop all services
.\start.ps1 -Stop
```

On first run the script opens `.env` in Notepad so you can add your API key, then continues automatically.

<br/>

---

## 🐳 &nbsp;Docker — MongoDB Only

The project runs Python services locally and MongoDB in Docker. ChromaDB is a library — no container needed.

```bash
# Start MongoDB container
cd deploy && docker compose up -d mongo

# Verify health
docker exec aiden_mongo mongosh --eval "db.adminCommand('ping')"

# Then start AIDEN normally
cd .. && ./start.sh
```

<br/>

---

## ⚙️ &nbsp;Configuration Reference

<br/>

### Required — must be set before first run

```env
# Gemini API — https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_key_here

# JWT Secret — minimum 32 characters
# Generate: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET=your_minimum_32_character_secret
JWT_EXPIRE_MINUTES=1440        # 24 h — tokens auto-rotate in the DB
```

<br/>

### Database

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=aiden
CHROMA_PATH=./data/chroma      # ChromaDB stores data on disk here
```

<br/>

### Optional — Gmail Integration

```env
# 1. https://console.cloud.google.com/apis/credentials
# 2. Create → OAuth 2.0 Client ID → Web application
# 3. Authorized Redirect URI: http://localhost:8000/auth/gmail/callback
# 4. Enable the Gmail API in the API Library
GMAIL_CLIENT_ID=your_client_id.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=your_client_secret

GMAIL_POLL_INTERVAL_MINUTES=15
GMAIL_MAX_EMAILS_PER_RUN=30
GMAIL_MARK_READ_AFTER_TASK=true
```

<br/>

### Optional — Telegram Bot

```env
# Get token from @BotFather → /newbot
TELEGRAM_BOT_TOKEN=

AIDEN_API_URL=http://localhost:8000    # OAuth callbacks
AIDEN_UI_URL=http://localhost:3000     # Gmail post-auth redirect
```

<br/>

### Server & Models

```env
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=1

DEFAULT_MODEL=gemini-2.0-flash
ORCHESTRATOR_MODEL=gemini-2.0-pro
VISION_MODEL=gemini-2.0-flash

ENV=development          # development | production | test
DEBUG=true
```

<br/>

---

## 🔑 &nbsp;Authentication Flow

No token pasting. No terminal commands. Pure UI.

```
 Register  ──or──  Login
      │                │
      ▼                ▼
POST /auth/register   POST /auth/login
 { name, email, pw }   { email, pw }
           │
           ▼
   ┌───────────────────────────────┐
   │   jwt_tokens  (MongoDB)       │
   │   Valid token exists?         │
   │     YES → return it as-is     │
   │     NO  → mint new JWT        │
   │           store + TTL index   │
   │           auto-purge on expiry│
   └───────────────────────────────┘
           │
           ▼
   Saved to localStorage
   Restored on page refresh
   Logout → revoked in DB
```

<br/>

---

## 📡 &nbsp;API Reference

Full interactive docs at **http://localhost:8000/docs**

<br/>

<details>
<summary><strong>Auth Endpoints</strong></summary>
<br/>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/register` | Create account → JWT |
| `POST` | `/auth/login` | Authenticate → JWT (reuses valid token) |
| `POST` | `/auth/logout` | Revoke all active tokens |
| `GET` | `/auth/me` | Current user info + integration status |
| `GET` | `/auth/gmail` | Start Gmail OAuth flow |
| `GET` | `/auth/gmail/callback` | Gmail OAuth callback → redirects to UI |
| `DELETE` | `/auth/gmail` | Disconnect Gmail |

</details>

<details>
<summary><strong>Tasks & Habits</strong></summary>
<br/>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/tasks` | List tasks (filter by status, priority, tags) |
| `POST` | `/tasks` | Create task |
| `PATCH` | `/tasks/{id}` | Update task |
| `DELETE` | `/tasks/{id}` | Delete task |
| `POST` | `/tasks/{id}/complete` | Complete task + update streak |
| `GET` | `/tasks/recurring` | List recurring task templates |
| `POST` | `/tasks/recurring` | Create recurring task |
| `GET` | `/habits` | All habits with streak data |
| `POST` | `/habits/{id}/complete` | Mark habit done today |

</details>

<details>
<summary><strong>Notes, Voice, Vision, Forecast, Briefing</strong></summary>
<br/>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/notes` | List notes (vector search supported) |
| `POST` | `/notes` | Create note |
| `POST` | `/voice/transcribe` | Transcribe audio via Gemini |
| `POST` | `/vision/analyze` | Analyze image (base64 JSON) |
| `POST` | `/vision/analyze/upload` | Analyze image (multipart) |
| `GET` | `/forecast` | 14-day ML workload forecast |
| `GET` | `/forecast/explain` | Plain-English explanation |
| `GET` | `/briefing/today` | Today's morning briefing |
| `POST` | `/briefing/today/read` | Mark briefing as read |
| `GET` | `/health` | Server health + service status |

</details>

<br/>

---

## 🗂️ &nbsp;Project Structure

```
aiden/
├── src/
│   ├── agents/
│   │   ├── orchestrator.py       ← Gemini 2.0 Pro routing agent
│   │   ├── task_agent.py         ← TaskMaster specialist
│   │   ├── calendar_agent.py     ← CalendarBot + MCP
│   │   ├── notes_agent.py        ← NoteKeeper + semantic search
│   │   ├── voice_agent.py        ← Audio transcription pipeline
│   │   └── vision_agent.py       ← Image classification + extraction
│   ├── api/
│   │   ├── main.py               ← FastAPI app, CORS, lifespan
│   │   ├── middleware.py         ← JWT validation, RBAC
│   │   └── routers/              ← One file per domain
│   │       ├── auth.py           ← Register, login, Gmail OAuth
│   │       ├── tasks.py
│   │       ├── notes.py
│   │       ├── habits.py
│   │       ├── voice.py + voice_ws.py
│   │       ├── vision.py
│   │       ├── briefing.py
│   │       ├── forecast.py
│   │       └── preferences.py
│   ├── analytics/
│   │   ├── workload_forecaster.py  ← EWMA + DP rescheduling (no LLM)
│   │   └── briefing_generator.py  ← Daily briefing builder (no LLM)
│   ├── core/
│   │   ├── config.py             ← pydantic-settings .env loader
│   │   ├── db_init.py            ← MongoDB schema + TTL indexes
│   │   ├── scheduler.py          ← APScheduler recurring jobs
│   │   └── session.py            ← ADK session service
│   ├── integrations/
│   │   └── telegram_bot.py       ← python-telegram-bot 21
│   ├── models/
│   │   ├── user.py               ← UserClaims, User, TokenResponse
│   │   ├── task.py               ← Task, RecurringTask, HabitSummary
│   │   ├── note.py
│   │   └── user_prefs.py         ← Gmail + Telegram preferences
│   ├── repositories/
│   │   ├── user_repo.py          ← User CRUD + JWT lifecycle
│   │   ├── task_repo.py
│   │   ├── notes_repo.py
│   │   ├── vector_repo.py        ← ChromaDB semantic search
│   │   └── prefs_repo.py
│   └── services/
│       ├── gmail_direct.py       ← Gmail REST API + OAuth tokens
│       └── gmail_pipeline.py     ← Background inbox polling
├── ui_react/
│   └── index.html                ← Complete single-file UI
├── deploy/
│   ├── docker-compose.yml        ← MongoDB container
│   ├── Dockerfile.api
│   └── Dockerfile.ui
├── start.sh                      ← macOS/Linux launcher
├── start.ps1                     ← Windows PowerShell launcher
├── setup.sh                      ← First-time macOS/Linux setup
├── pyproject.toml
└── .env.example
```

<br/>

---

## 🚀 &nbsp;Startup Script Reference

| Script | Platform | Command | What it does |
|--------|----------|---------|-------------|
| `setup.sh` | macOS/Linux | `./setup.sh` | First-time: `.env`, venv, deps |
| `start.sh` | macOS/Linux | `./start.sh` | Full stack — local MongoDB |
| `start.sh` | macOS/Linux | `./start.sh --docker` | Full stack — Docker MongoDB |
| `start.sh` | macOS/Linux | `./start.sh --stop` | Kill all services |
| `start.sh` | macOS/Linux | `./start.sh --setup` | Force reinstall deps |
| `start.ps1` | Windows | `.\start.ps1` | Full stack |
| `start.ps1` | Windows | `.\start.ps1 -Docker` | Docker MongoDB |
| `start.ps1` | Windows | `.\start.ps1 -Stop` | Kill all services |
| `start.ps1` | Windows | `.\start.ps1 -Setup` | Force reinstall |

<br/>

---

## 🔧 &nbsp;Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `GEMINI_API_KEY is not set` | Missing `.env` value | `./setup.sh` or edit `.env` |
| `JWT_SECRET too short` | Less than 32 chars | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| API not reachable | Server crashed | Check `logs/api.log` |
| MongoDB connection refused | MongoDB not running | `./start.sh --docker` or `sudo systemctl start mongod` |
| Port already in use | Stale process | `./start.sh --stop` then retry |
| Gmail OAuth fails | Missing credentials | Add `GMAIL_CLIENT_ID` + `GMAIL_CLIENT_SECRET` to `.env` |
| Gmail redirect error | Wrong redirect URI | Add `http://localhost:8000/auth/gmail/callback` in Google Cloud Console |
| Dependencies broken | Corrupt `.venv` | `./start.sh --setup` |

<br/>

---

## 🗺️ &nbsp;Roadmap

- [ ] Production deployment (HTTPS, Nginx, Docker Compose full-stack)
- [ ] Google Calendar real-time sync via official API
- [ ] Slack integration (slash commands + notifications)
- [ ] API key authentication for developer access
- [ ] Mobile PWA (installable from browser)
- [ ] Multi-workspace / team support
- [ ] Custom agent plugins via MCP

<br/>

---

## 🤝 &nbsp;Contributing

```bash
# Fork → clone → branch
git checkout -b feature/your-feature-name

# Install with dev extras
pip install -e ".[dev]"

# Run tests
pytest

# Lint + format
ruff check src/ && black src/

# Open a PR against main
```

<br/>

---

## 📜 &nbsp;License

MIT License — see [LICENSE](LICENSE) for details.

<br/>

---

<div align="center">

**Built with Google Gemini · Google ADK · FastAPI · MongoDB**

*AIDEN v2.0 — 2026*

<br/>

[![GitHub stars](https://img.shields.io/github/stars/your-org/aiden?style=social)](https://github.com/your-org/aiden)

</div>
