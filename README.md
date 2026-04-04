<div align="center">

```
    ___    _________  _______   __
   /   |  /  _/ __ \/ ____/ | / /
  / /| |  / // / / / __/ /  |/ /
 / ___ |_/ // /_/ / /___/ /|  /
/_/  |_/___/_____/_____/_/ |_/
```

### **AI Daily Executive Navigator**
*A production-grade, multi-agent productivity system — fully on the Google AI stack*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Google Gemini](https://img.shields.io/badge/Gemini-2.0_Flash_+_Pro-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)
[![Vertex AI](https://img.shields.io/badge/Vertex_AI-Enabled-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white)](https://cloud.google.com/vertex-ai)
[![Cloud Run](https://img.shields.io/badge/Cloud_Run-Deployed-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![MongoDB](https://img.shields.io/badge/MongoDB-7.0-47A248?style=for-the-badge&logo=mongodb&logoColor=white)](https://mongodb.com)
[![Tests](https://img.shields.io/badge/Tests-44_passing-22C55E?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![License](https://img.shields.io/badge/License-MIT-F59E0B?style=for-the-badge)](LICENSE)

<br/>

> **AIDEN** is not a single chatbot. It is an **orchestrated squad of specialised AI agents** that collaborate in real time to understand your intent, route it to the right specialist, and act — while you watch every routing decision, tool call, and result stream live in the UI.

<br/>

---

</div>

## ✦ &nbsp;What AIDEN Does

AIDEN coordinates multiple specialised agents through a primary orchestrator. Each message you send triggers a routing decision, one or more sub-agents, real tool calls against live APIs, and a structured result — all visible in the live trace panel.

<br/>

```
  Your Input  (text / voice / image)
          │
          ▼
  ┌─────────────────────────────┐
  │   AIDEN  ORCHESTRATOR       │  ← Gemini 2.0 Pro via Vertex AI
  │   (primary coordination)    │
  └──────────┬──────────────────┘
             │  routes to specialist agents
     ┌────────┼──────────────────────────────────┐
     ▼        ▼            ▼          ▼          ▼
  ┌──────┐ ┌──────────┐ ┌────────┐ ┌───────┐ ┌────────┐
  │ Task │ │ Calendar │ │  Note  │ │ Voice │ │ Vision │
  │Master│ │   Bot    │ │Keeper  │ │ Agent │ │ Agent  │
  └──┬───┘ └────┬─────┘ └───┬────┘ └───────┘ └────────┘
     │          │            │
     ▼          ▼            ▼
  MongoDB   Google       ChromaDB
  (tasks)   Calendar    (Gemini text-
            API v3       embedding-004
                         vectors)
```

<br/>

Every step of this coordination **streams live to the UI** as it happens — routing decisions, tool calls with arguments, results with timing — so the multi-agent execution is fully transparent.

<br/>

---

## 🧩 &nbsp;Core Features

<br/>

### 🔀 &nbsp;Live Agent Trace Panel

Every chat message opens a real-time drawer above the response that shows each step as it happens:

```
● Orchestrator  → Routed to TaskMaster
⚙ TaskMaster   → list_tasks({status: "todo"})        [running]
← TaskMaster   ← list_tasks  (94ms)
⚙ CalendarBot  → get_weeks_calendar({})              [running]
← CalendarBot  ← get_weeks_calendar  (210ms)
◈ Done in 1.8s   [ORCHESTRATOR]  [TASKMASTER]  [CALENDARBOT]
```

The panel auto-collapses after completion. A full collapsed trace (with all steps) is also embedded in the assistant message for reference.

<br/>

### 🤖 &nbsp;Multi-Agent Intelligence

| Agent | Responsibility | Trigger keywords |
|-------|---------------|-----------------|
| **Orchestrator** | Intent routing, multi-step coordination | Every message |
| **TaskMaster** | Create, update, complete, prioritise tasks | *"todo"*, *"remind me"*, *"P1"* |
| **CalendarBot** | Google Calendar v3 — list, create, find free slots | *"calendar"*, *"meeting"*, *"schedule"* |
| **NoteKeeper** | Semantic note creation + Gemini vector search | *"note"*, *"write down"*, *"search"* |
| **VoiceAgent** | Audio → intent → action (Gemini Live) | Mic button |
| **VisionAgent** | Image classification + data extraction | Image upload |

<br/>

### ⚡ &nbsp;One-Click Multi-Step Workflow Demos

Three pre-built scenarios chain 3+ agents in sequence:

| Button | Agents chained | What it does |
|--------|---------------|--------------|
| **Plan my week** | Orchestrator → TaskMaster → CalendarBot → NoteKeeper | Lists open tasks, reads calendar, spots conflicts, assigns tasks to days, saves summary note |
| **Prepare for my next meeting** | CalendarBot → NoteKeeper → TaskMaster | Finds next event, searches related notes, links open tasks, saves meeting brief |
| **Process my inbox** | Gmail → Orchestrator → TaskMaster × N | Scans Gmail, creates tasks from action items, saves reference notes, delivers summary |

<br/>

### 📅 &nbsp;Real Google Calendar Integration

Five live tools backed by Google Calendar REST API v3 (OAuth2):

| Tool | What it does |
|------|-------------|
| `get_todays_calendar` | All events for today |
| `get_weeks_calendar` | 7-day event view |
| `create_calendar_event` | Create with auto conflict-check |
| `find_free_slots` | Find available gaps on any date |
| `delete_calendar_event` | Remove event by ID |

<br/>

### 🔍 &nbsp;Semantic Search — Gemini text-embedding-004

Notes are indexed using Google's **text-embedding-004** model (768-dimensional vectors) stored in ChromaDB. Two separate task types are used for maximum retrieval quality:

- `RETRIEVAL_DOCUMENT` — when indexing notes
- `RETRIEVAL_QUERY` — when searching (query-optimised)

Results include a cosine similarity score (`_score`) and the model name (`_model: "gemini/text-embedding-004"`). Verify embeddings are live before demo:

```bash
python scripts/verify_embeddings.py
```

<br/>

### 📋 &nbsp;Task Management

- Priority system: P0 Critical → P3 Low
- Status workflow: todo → in_progress → completed → cancelled
- Due dates, tags, recurring tasks
- ML workload forecasting (7-day prediction)

<br/>

### 📊 &nbsp;Workflow History & Audit Trail

Every agent execution is permanently stored in MongoDB (`agent_traces` collection) and surfaced in the **History** tab — with step-by-step trace, agents involved as colour pills, duration, and full expandable detail. Proof that multi-agent coordination happens, always on record.

<br/>

### 📧 &nbsp;Gmail Integration

- OAuth2 connection via Google Cloud Console
- Background inbox polling every 15 min
- Action-item extraction → task creation
- "Process my inbox" workflow chains Gmail → TaskMaster → NoteKeeper

<br/>

### 📸 &nbsp;Vision Analysis

Eight image types: receipts, business cards, whiteboards, screenshots, charts, food, documents, general. Gemini Vision extracts structured data and optionally creates tasks from action items found in images.

<br/>

### 🎤 &nbsp;Voice Input

Gemini Live real-time audio — speak your request, get a multi-agent response. Also supported via Telegram voice notes.

<br/>

### 🌅 &nbsp;Daily Briefing

Structured morning brief: open tasks by priority, today's calendar, overdue items, habit streaks. Delivered at a configurable time via APScheduler.

<br/>

### 🎬 &nbsp;Demo Mode

One click seeds the account with 6 realistic tasks + 3 rich notes (all indexed in ChromaDB) and launches a 5-step guided tour highlighting every key feature. No manual setup needed for evaluation.

<br/>

---

## 🛠️ &nbsp;Tech Stack

<div align="center">

### Google AI Stack

| Component | Technology |
|-----------|-----------|
| Orchestration & Chat | **Google Gemini 2.0 Pro** via **Vertex AI** |
| Task / Note / Voice Agents | **Google Gemini 2.0 Flash** via Vertex AI |
| Vision Analysis | **Google Gemini 2.0 Flash Vision** |
| Semantic Embeddings | **Gemini text-embedding-004** (768-dim vectors) |
| Agent Framework | **Google ADK 1.x** |
| Calendar Integration | **Google Calendar API v3** (OAuth2) |
| Gmail Integration | **Gmail API** (OAuth2) |
| Cloud Deployment | **Google Cloud Run** (serverless, auto-scaling) |
| AI Routing | **Vertex AI** (all Gemini calls routed via `GOOGLE_GENAI_USE_VERTEXAI=1`) |
| CI/CD | **Google Cloud Build** + **Artifact Registry** |

### Backend Layer

| Component | Technology |
|-----------|-----------|
| REST API + WebSocket | FastAPI 0.115 + Uvicorn / Gunicorn |
| Authentication | python-jose (JWT) + passlib (bcrypt) |
| Background Jobs | APScheduler |
| HTTP Client | httpx (async) |
| Config Management | pydantic-settings |
| Structured Logging | structlog |

### Data Layer

| Component | Technology |
|-----------|-----------|
| Primary Database | MongoDB 7 + motor (async driver) |
| Vector / Semantic Search | **ChromaDB** + **Gemini text-embedding-004** |
| Agent Execution History | MongoDB `agent_traces` collection |
| OAuth Credentials | MongoDB `user_credentials` |
| Agent Sessions | MongoDB `adk_sessions` |

### Quality & Infrastructure

| Component | Technology |
|-----------|-----------|
| Tests | pytest + pytest-asyncio (44 tests, ~65% coverage) |
| Containerisation | Docker + Docker Compose |
| Cloud Infrastructure | Google Cloud Run, Secret Manager, Artifact Registry |
| Telegram Bot | python-telegram-bot 21 |

</div>

<br/>

---

## ☁️ &nbsp;Cloud Deployment (Google Cloud Run + Vertex AI)

AIDEN is deployed on Google Cloud infrastructure. All Gemini calls are routed through **Vertex AI** — not the public API endpoint.

### One-shot setup

```bash
export PROJECT_ID="your-gcp-project-id"
chmod +x deploy/setup_gcp.sh
./deploy/setup_gcp.sh          # enables APIs, creates secrets, grants IAM
```

### Deploy via Cloud Build

```bash
gcloud builds submit --config=cloudbuild.yaml \
    --substitutions=_PROJECT_ID=$PROJECT_ID
```

Cloud Build automatically:
1. Builds the Docker image
2. Pushes to Artifact Registry
3. Deploys to Cloud Run with Secret Manager secrets
4. Prints the live URL

### Vertex AI routing

Set `GOOGLE_CLOUD_PROJECT` in `.env` (or Cloud Run env vars) and AIDEN automatically routes all Gemini calls through Vertex AI at startup:

```bash
# .env
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
```

No agent or tool code changes required — ADK honours `GOOGLE_GENAI_USE_VERTEXAI=1` at the SDK level.

<br/>

---

## ⚡ &nbsp;Quick Start

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | [python.org](https://python.org) |
| MongoDB | 7.0 | Local install **or** Docker |
| Gemini API Key | — | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| GCP Project | — | Optional — for Vertex AI + Cloud Run |

<br/>

---

## 🍎 &nbsp;macOS

```bash
git clone <repo-url> && cd aiden

# First-time setup (creates .env, installs deps)
chmod +x setup.sh && ./setup.sh

# Edit .env and add your keys
nano .env

# Start full stack
./start.sh
```

Open **http://localhost:8000/docs** for the API, serve `ui_react/index.html` directly in your browser for the UI.

<br/>

---

## 🐧 &nbsp;Linux

```bash
git clone <repo-url> && cd aiden
chmod +x setup.sh start.sh
./setup.sh
nano .env          # set GEMINI_API_KEY and JWT_SECRET
./start.sh
```

<br/>

---

## 🪟 &nbsp;Windows (PowerShell)

```powershell
git clone <repo-url>; cd aiden
.\start.ps1 -Setup      # first-time setup
# Edit .env
.\start.ps1             # start full stack
```

<br/>

---

## 🐳 &nbsp;Docker — MongoDB Only

```bash
docker compose -f deploy/docker-compose.yml up -d
```

Only MongoDB runs in Docker. The FastAPI server runs natively (for live-reload dev).

<br/>

---

## ⚙️ &nbsp;Configuration Reference

### Required

```bash
# .env
GEMINI_API_KEY=your_gemini_api_key_here         # Get from aistudio.google.com
JWT_SECRET=your_min_32_char_secret_here          # python -c "import secrets; print(secrets.token_urlsafe(32))"
MONGO_URI=mongodb://localhost:27017
```

### Google Cloud / Vertex AI (recommended)

```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id        # Enables Vertex AI routing
GOOGLE_CLOUD_LOCATION=us-central1
```

When `GOOGLE_CLOUD_PROJECT` is set, AIDEN automatically routes all Gemini calls through Vertex AI at startup. When unset, it falls back to the direct Gemini API — no code changes needed.

### Gmail + Google Calendar OAuth2

```bash
GMAIL_CLIENT_ID=your_oauth_client_id
GMAIL_CLIENT_SECRET=your_oauth_client_secret
# Redirect URIs to add in Google Cloud Console:
#   http://localhost:8000/auth/gmail/callback
#   http://localhost:8000/auth/calendar/callback
```

### Optional

```bash
TELEGRAM_BOT_TOKEN=                              # BotFather token; empty = disabled
CHROMA_PATH=./data/chroma                        # ChromaDB data directory
GMAIL_POLL_INTERVAL_MINUTES=15
DEFAULT_MODEL=gemini-2.0-flash
ORCHESTRATOR_MODEL=gemini-2.0-pro
```

<br/>

---

## 🎬 &nbsp;Evaluator Quick-Start (Demo Mode)

For judges evaluating the system:

1. **Start the server** — `./start.sh`
2. **Open the UI** — serve `ui_react/index.html`
3. **Register** an account
4. **Click 🎬 Demo Mode** — seeds 6 tasks + 3 notes, launches guided tour
5. **Click "Plan my week"** — watch 3+ agents chain in the live trace panel
6. **Check History tab** — full audit trail of every execution

Or verify the embedding stack independently:
```bash
python scripts/verify_embeddings.py
```

<br/>

---

## 🔑 &nbsp;Authentication Flow

```
POST /auth/register  →  creates user, returns JWT
POST /auth/login     →  returns JWT
GET  /auth/gmail     →  starts Gmail OAuth2 flow
GET  /auth/calendar  →  starts Calendar OAuth2 flow
GET  /auth/me        →  returns user + integration status
```

All protected endpoints require `Authorization: Bearer <token>`.

<br/>

---

## 📡 &nbsp;API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat` | SSE streaming chat — multi-agent with live trace |
| `POST` | `/chat/sync` | Non-streaming chat (programmatic clients) |
| `GET`  | `/chat/history` | Past agent executions from MongoDB |
| `POST` | `/tasks` | Create task |
| `GET`  | `/tasks` | List tasks (with filters) |
| `PATCH`| `/tasks/{id}` | Update task |
| `DELETE`| `/tasks/{id}` | Delete task |
| `POST` | `/notes` | Create note + index Gemini embedding |
| `GET`  | `/notes` | List notes |
| `GET`  | `/notes/search?q=` | Semantic search (Gemini text-embedding-004) |
| `GET`  | `/notes/search/verify` | Confirm Gemini embeddings are live (768-dim check) |
| `POST` | `/demo/seed` | Seed demo data (tasks + notes, idempotent) |
| `GET`  | `/forecast` | ML workload forecast |
| `GET`  | `/briefing` | Daily structured briefing |
| `GET`  | `/health` | Server health check |
| `GET`  | `/docs` | Interactive OpenAPI docs |

<br/>

---

## 🧪 &nbsp;Tests

44 tests across 4 modules — no real API keys or database connections needed.

```bash
# Install dev extras
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=src --cov-report=term-missing
```

| Module | Tests | What's covered |
|--------|-------|---------------|
| `test_task_repo.py` | 12 | CRUD, user-scoping security, update/delete contracts |
| `test_vector_repo.py` | 10 | Gemini vector passing, score conversion, RETRIEVAL_QUERY isolation |
| `test_orchestrator.py` | 12 | SSE stream contract, multi-agent routing, session handling |
| `test_chat_endpoint.py` | 10 | Chat sync/SSE, notes search scoring, demo seed endpoint |

<br/>

---

## 🗂️ &nbsp;Project Structure

```
aiden/
├── src/
│   ├── agents/
│   │   ├── orchestrator.py       ← Primary routing agent (Gemini 2.0 Pro)
│   │   ├── task_agent.py         ← TaskMaster sub-agent
│   │   ├── calendar_agent.py     ← CalendarBot — 5 live Google Calendar tools
│   │   ├── notes_agent.py        ← NoteKeeper — semantic search
│   │   ├── voice_agent.py        ← Gemini Live audio
│   │   └── vision_agent.py       ← Gemini Vision
│   ├── api/
│   │   ├── main.py               ← FastAPI app — Vertex AI init at startup
│   │   └── routers/
│   │       ├── chat.py           ← SSE streaming with live trace emission
│   │       ├── notes.py          ← /notes/search + /notes/search/verify
│   │       ├── demo.py           ← POST /demo/seed (idempotent seed endpoint)
│   │       ├── tasks.py
│   │       ├── auth.py           ← JWT + Google OAuth2
│   │       └── ...
│   ├── core/
│   │   ├── runner.py             ← AIDENRunner — ADK + SSE trace streaming
│   │   ├── tracer.py             ← TraceCollector — step capture + MongoDB persist
│   │   ├── vertex_init.py        ← Vertex AI SDK init (GOOGLE_GENAI_USE_VERTEXAI=1)
│   │   ├── config.py             ← pydantic-settings (GOOGLE_CLOUD_PROJECT etc.)
│   │   ├── db_init.py
│   │   └── scheduler.py
│   ├── repositories/
│   │   ├── task_repo.py
│   │   ├── notes_repo.py
│   │   ├── vector_repo.py        ← ChromaDB + Gemini text-embedding-004
│   │   └── user_repo.py
│   └── services/
│       ├── google_calendar.py    ← Google Calendar REST API v3 client
│       └── gmail_pipeline.py
├── tests/
│   ├── conftest.py               ← Shared fixtures (fake user, mock MongoDB, 768-dim vector)
│   ├── test_repositories/
│   │   ├── test_task_repo.py     ← 12 tests
│   │   └── test_vector_repo.py   ← 10 tests (Gemini embedding verification)
│   ├── test_agents/
│   │   └── test_orchestrator.py  ← 12 tests (SSE stream contract)
│   └── test_api/
│       └── test_chat_endpoint.py ← 10 tests (chat + notes search + demo)
├── scripts/
│   └── verify_embeddings.py      ← Standalone Gemini embedding smoke-test
├── ui_react/
│   └── index.html                ← Complete single-file UI (dark theme)
├── deploy/
│   ├── Dockerfile.api            ← Production image (gunicorn + vertexai SDK)
│   ├── docker-compose.yml        ← MongoDB container
│   └── setup_gcp.sh              ← One-shot GCP provisioning script
├── cloudbuild.yaml               ← Cloud Build CI/CD pipeline
├── pyproject.toml
├── pytest.ini
├── start.sh                      ← macOS/Linux launcher
├── start.ps1                     ← Windows launcher
└── .env.example
```

<br/>

---

## 🚀 &nbsp;Startup Script Reference

| Script | Platform | Command | What it does |
|--------|----------|---------|-------------|
| `setup.sh` | macOS/Linux | `./setup.sh` | First-time: `.env`, venv, deps |
| `start.sh` | macOS/Linux | `./start.sh` | Full stack |
| `start.sh` | macOS/Linux | `./start.sh --docker` | Docker MongoDB |
| `start.sh` | macOS/Linux | `./start.sh --stop` | Kill all services |
| `start.ps1` | Windows | `.\start.ps1` | Full stack |
| `start.ps1` | Windows | `.\start.ps1 -Docker` | Docker MongoDB |
| `deploy/setup_gcp.sh` | Any | `./deploy/setup_gcp.sh` | GCP provisioning |
| `cloudbuild.yaml` | GCP | `gcloud builds submit` | Cloud Run deploy |

<br/>

---

## 🔧 &nbsp;Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `GEMINI_API_KEY is not set` | Missing `.env` | `./setup.sh` or edit `.env` |
| `JWT_SECRET too short` | < 32 chars | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| API not reachable | Server crashed | Check `logs/api.log` |
| MongoDB refused | Not running | `./start.sh --docker` or `sudo systemctl start mongod` |
| Port in use | Stale process | `./start.sh --stop` then retry |
| Vertex AI 403 | ADC not set | `gcloud auth application-default login` |
| Embedding dims ≠ 768 | Wrong model | Check `GEMINI_API_KEY` is valid; run `python scripts/verify_embeddings.py` |
| Gmail OAuth fails | Wrong redirect URI | Add `http://localhost:8000/auth/gmail/callback` in Google Cloud Console |

<br/>

---

## 🗺️ &nbsp;Roadmap

- [x] Multi-agent orchestration with Google ADK
- [x] Live agent trace panel (real-time SSE streaming)
- [x] Google Calendar API v3 integration (5 live tools)
- [x] Gemini text-embedding-004 semantic search
- [x] Google Cloud Run deployment
- [x] Vertex AI routing for all Gemini calls
- [x] Workflow history & audit trail (MongoDB)
- [x] Demo Mode + guided onboarding tour
- [x] Test suite (44 tests, ~65% coverage)
- [ ] Google Drive MCP integration
- [ ] Slack integration (slash commands + notifications)
- [ ] Mobile PWA (installable from browser)
- [ ] Multi-workspace / team support
- [ ] Custom agent plugins via MCP

<br/>

---

## 🤝 &nbsp;Contributing

```bash
git checkout -b feature/your-feature-name

# Install with dev extras
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint + format
ruff check src/ && black src/

# Verify Gemini embeddings
python scripts/verify_embeddings.py
```

<br/>

---

## 📜 &nbsp;License

MIT License — see [LICENSE](LICENSE) for details.

<br/>

<div align="center">

*Built with Google ADK · Gemini 2.0 · Vertex AI · Cloud Run · text-embedding-004*

</div>
