<div align="center">

```
    ___    _________  _______   __
   /   |  /  _/ __ \/ ____/ | / /
  / /| |  / // / / / __/ /  |/ /
 / ___ |_/ // /_/ / /___/ /|  /
/_/  |_/___/_____/_____/_/ |_/
```

### **AI Daily Executive Navigator — v5.0**
*Production-grade multi-agent system — fully on the Google AI stack*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Pro_+_Flash-4285F4?style=for-the-badge&logo=google)](https://ai.google.dev)
[![Vertex AI](https://img.shields.io/badge/Vertex_AI-Enabled-4285F4?style=for-the-badge&logo=googlecloud)](https://cloud.google.com/vertex-ai)
[![MCP](https://img.shields.io/badge/MCP-4_Servers-orange?style=for-the-badge)](https://modelcontextprotocol.io)
[![MongoDB](https://img.shields.io/badge/MongoDB-7.0-47A248?style=for-the-badge&logo=mongodb)](https://mongodb.com)

</div>

---

## What is AIDEN?

AIDEN is an **orchestrated squad of AI agents** that collaborate to manage your
tasks, calendar, notes, files, images, and team knowledge — all in real time.
Every routing decision, tool call, and agent handoff streams live to the UI.

## Architecture

```
  Your Input (text / voice / image)
        │
        ▼
  ┌─────────────────────────────────────────────────┐
  │   AIDEN ORCHESTRATOR v5.0  (Gemini 2.5 Pro)     │
  │   build_orchestrator(user) — async, per-session  │
  └────────┬─────────────────────────────────────┬───┘
           │ MCP tools (direct)                  │ Sub-agents (AgentTool)
   ┌───────┴──────────────────────┐   ┌───────────┴──────────────────────────┐
   │ Workspace MCP  :8001         │   │ TaskMaster   │ NoteKeeper            │
   │ MongoDB MCP    :8002         │   │ CalendarBot  │ VisionAgent           │
   │ Notion MCP     :8003         │   │ VoiceAgent   │ DriveAgent            │
   │ GitHub MCP     :8004 [dev]   │   │ NotionAgent (MCP, team collab)       │
   └──────────────────────────────┘   └──────────────────────────────────────┘
           │                                      │
   Calendar/Gmail/Drive               MongoDB + ChromaDB
   MongoDB read queries               Notion Workspace
   Notion pages/databases             GitHub repos/issues
```

## What's New in v5.0

| Feature | Detail |
|---|---|
| **Google Workspace MCP** | Calendar, Gmail, Drive, Docs via `google-workspace-mcp` — port 8001 |
| **MongoDB MCP** | Read-only analytics queries via official MongoDB MCP — port 8002 |
| **Notion MCP + NotionAgent** | New sub-agent for team wiki + collaboration — port 8003 |
| **GitHub MCP** | Developer mode: issues, PRs, repos per user — port 8004 |
| **Developer Mode** | Toggle per-user via `PATCH /settings/developer` + encrypted GitHub token |
| **Async orchestrator** | `build_orchestrator(user)` + `build_runner(user)` for MCP-enabled sessions |
| **14 new tests** | MCPLoader, NotionAgent, developer settings |

## Tech Stack

### Google AI Stack
| Component | Technology |
|---|---|
| Orchestration | **Gemini 2.5 Pro** via **Vertex AI** |
| Sub-agents | **Gemini 2.5 Flash** via Vertex AI |
| Embeddings | **Gemini text-embedding-004** (768-dim vectors) |
| Agent Framework | **Google ADK 1.x** |
| Calendar + Gmail | **Google Workspace MCP** (Port 8001) |
| Cloud Deployment | **Google Cloud Run** |
| CI/CD | **Cloud Build** + **Artifact Registry** |

### MCP Layer (v5.0)
| Server | Port | Package |
|---|---|---|
| Google Workspace | 8001 | `google-workspace-mcp` (pip) |
| MongoDB | 8002 | `@mongodb-js/mongodb-mcp-server` (npm) |
| Notion | 8003 | `@notionhq/notion-mcp-server` (npm) |
| GitHub | 8004 | `@modelcontextprotocol/server-github` (npm) |

### Backend
| Component | Technology |
|---|---|
| REST API + WebSocket | FastAPI 0.115 + Uvicorn |
| Authentication | JWT + argon2 + Fernet token encryption |
| Background Jobs | APScheduler |
| Observability | structlog + OpenTelemetry + Prometheus |

### Data Layer
| Component | Technology |
|---|---|
| Primary Database | MongoDB 7 + motor (async) |
| Vector Search | ChromaDB + Gemini text-embedding-004 |
| Agent History | MongoDB `agent_traces` collection |

## Quick Start

```bash
# 1. Clone and setup
git clone <repo-url> && cd aiden
chmod +x setup.sh && ./setup.sh

# 2. Configure
cp .env.example .env
# Edit .env: GEMINI_API_KEY, JWT_SECRET (required)
#            NOTION_TOKEN (for Notion MCP)
nano .env

# 3. Start infrastructure + MCP servers
./start_mcp.sh              # workspace + mongo + notion MCP
./start_mcp.sh --dev        # also start GitHub MCP

# 4. Start API
./start.sh

# 5. Open UI
# Streamlit: http://localhost:8501
# API docs:  http://localhost:8000/docs
```

## Demo Mode

```bash
# Seed demo data (6 tasks + 3 notes + ChromaDB indexed)
curl -X POST http://localhost:8000/demo/seed \
  -H "Authorization: Bearer <token>"

# Then try these commands in the UI:
# "Plan my week"               → 4-agent workflow
# "Prepare for my next meeting" → 3-agent workflow
# "What did I write about Q2?"  → semantic note search
# "Read our team roadmap"       → NotionAgent (if NOTION_TOKEN set)
```

## New Demo Workflows (v5.0)

| Workflow | Agents/MCPs |
|---|---|
| "Read our Q2 roadmap and create tasks" | Notion MCP → TaskMaster → CalendarBot → NoteKeeper |
| "How many overdue tasks?" | MongoDB MCP → direct response |
| "Turn GitHub issue #42 into a task" (dev) | GitHub MCP → TaskMaster |
| "Plan my week" (upgraded) | Workspace MCP + MongoDB MCP + Notion MCP + TaskMaster |

## Developer Mode

Enable per user via the UI (Settings → Developer Mode) or API:

```bash
curl -X PATCH http://localhost:8000/settings/developer \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "github_token": "ghp_xxx"}'
```

GitHub MCP tools load automatically on the next conversation.

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | SSE streaming chat with live agent trace |
| `POST` | `/chat/sync` | Non-streaming chat |
| `GET` | `/chat/history` | Past agent executions |
| `POST/GET/PATCH/DELETE` | `/tasks` | Task CRUD |
| `POST/GET` | `/notes` | Note CRUD |
| `GET` | `/notes/search?q=` | Gemini semantic search |
| `GET` | `/briefing` | Daily structured briefing |
| `GET` | `/forecast` | ML workload forecast |
| `POST` | `/demo/seed` | Seed demo data |
| `GET/PATCH` | `/settings/developer` | **NEW** Developer mode toggle |
| `GET` | `/health` | Health + MCP server status |
| `GET` | `/docs` | OpenAPI interactive docs |

## Running Tests

```bash
# All tests (original + 14 new MCP tests)
pytest tests/ -v

# MCP tests only
pytest tests/test_mcp/ -v

# With coverage
pytest tests/ -v --cov=src --cov-report=term-missing
```

## Project Structure

```
aiden/
├── src/
│   ├── agents/
│   │   ├── orchestrator.py     ← v5.0: async build_orchestrator(user)
│   │   ├── notion_agent.py     ← NEW: NotionAgent via Notion MCP
│   │   ├── task_agent.py       ← TaskMaster (unchanged)
│   │   ├── notes_agent.py      ← NoteKeeper (unchanged)
│   │   ├── calendar_agent.py   ← CalendarBot (fallback; Workspace MCP is primary)
│   │   ├── drive_agent.py      ← DriveAgent (fallback; Workspace MCP is primary)
│   │   ├── vision_agent.py     ← VisionAgent (unchanged)
│   │   └── voice_agent.py      ← VoiceAgent (unchanged)
│   ├── core/
│   │   ├── config.py           ← v5.0: + MCP ports, NOTION_TOKEN, GITHUB_TOKEN
│   │   ├── runner.py           ← v5.0: + build_runner(user) for MCP sessions
│   │   ├── mcp_loader.py       ← NEW: centralised MCPLoader
│   │   ├── db_init.py
│   │   ├── scheduler.py
│   │   ├── session.py
│   │   ├── tracer.py
│   │   └── vertex_init.py
│   ├── models/
│   │   ├── user.py             ← v5.0: + is_developer, github_token, notion_connected
│   │   ├── task.py
│   │   ├── note.py
│   │   └── user_prefs.py
│   ├── api/
│   │   ├── main.py             ← v5.0: + dev_settings_router + MCP health status
│   │   ├── middleware.py
│   │   └── routers/
│   │       ├── developer_settings.py  ← NEW: PATCH /settings/developer
│   │       ├── chat.py
│   │       ├── auth.py
│   │       ├── tasks.py, notes.py, voice.py, vision.py
│   │       ├── gmail.py, habits.py, forecast.py, briefing.py
│   │       ├── sessions.py, preferences.py, demo.py
│   │       └── voice_ws.py
│   ├── repositories/           ← Full MongoDB implementations
│   ├── services/               ← Google Calendar, Drive, Gmail clients
│   ├── tools/                  ← FunctionTool implementations
│   ├── analytics/              ← briefing_generator, workload_forecaster
│   └── integrations/           ← telegram_bot
├── mcp_servers/
│   ├── workspace/README.md     ← Google Workspace MCP setup
│   ├── mongodb/README.md       ← MongoDB MCP setup
│   ├── notion/README.md        ← Notion MCP + integration setup
│   └── github/README.md        ← GitHub MCP + developer mode setup
├── tests/
│   ├── test_agents/            ← Original orchestrator tests
│   ├── test_api/               ← Original API tests
│   ├── test_repositories/      ← Original repo tests (task, vector)
│   ├── test_tools/             ← Original tool tests (drive, firestore, workflow)
│   └── test_mcp/               ← NEW: MCPLoader, NotionAgent, dev settings
├── ui/                         ← Streamlit UI + components
├── ui_react/                   ← React single-file UI with live trace panel
├── deploy/
│   ├── docker-compose.yml      ← MongoDB + 4 MCP sidecar services
│   ├── Dockerfile.api
│   └── setup_gcp.sh
├── start_mcp.sh                ← Start MCP servers
├── start.sh
├── MCP_INTEGRATION.md          ← Complete MCP integration guide
└── .env.example                ← Updated with all v5.0 settings
```

## Configuration

```bash
# Minimum required
GEMINI_API_KEY=your_key
JWT_SECRET=your_32_char_secret

# MCP (v5.0 additions)
NOTION_TOKEN=secret_xxx          # Notion workspace token
WORKSPACE_MCP_PORT=8001
MONGO_MCP_PORT=8002
NOTION_MCP_PORT=8003
GITHUB_MCP_PORT=8004

# Google Cloud
GOOGLE_CLOUD_PROJECT=your-project-id
```

See `.env.example` for the full reference.

---

*Built with Google ADK · Gemini 2.5 · Vertex AI · Cloud Run · text-embedding-004 · MCP*
