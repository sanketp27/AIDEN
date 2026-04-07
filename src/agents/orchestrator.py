from __future__ import annotations
import asyncio
import os
from typing import Any

import structlog

log = structlog.get_logger()

os.environ.setdefault("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
os.environ.setdefault("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

try:
    from src.core.config import settings
    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    os.environ.setdefault("GEMINI_API_KEY", settings.GEMINI_API_KEY)
except Exception:
    pass

try:
    from google.adk.agents import Agent
    from google.adk.tools import AgentTool
    _ADK_AVAILABLE = True
except ImportError:
    _ADK_AVAILABLE = False
    log.error("orchestrator.adk_unavailable")

try:
    from src.agents.task_agent import task_master_agent
    from src.agents.calendar_agent import calendar_bot_agent
    from src.agents.notes_agent import note_keeper_agent
    from src.agents.vision_agent import vision_agent
    from src.agents.voice_agent import voice_agent
    from src.agents.drive_agent import drive_agent
    from src.agents.notion_agent import build_notion_agent, _NotionAgentStub
    _AGENTS_LOADED = True
except ImportError as e:
    log.warning("orchestrator.agents_import_failed", error=str(e))
    _AGENTS_LOADED = False

try:
    from src.core.mcp_loader import MCPLoader
    _MCP_LOADER_AVAILABLE = True
except ImportError:
    _MCP_LOADER_AVAILABLE = False

try:
    from src.core.config import settings as _settings
except Exception:
    _settings = None


ORCHESTRATOR_INSTRUCTION = """You are AIDEN v3.0 (AI Intelligent Daily Executive Navigator).
You coordinate 6 specialist agents and 4 MCP tool servers to help users manage
tasks, calendar, notes, files, images, voice, and team knowledge.

═══════════════════════════════════════════════════
TOOL & AGENT ROUTING
═══════════════════════════════════════════════════

GOOGLE WORKSPACE MCP (direct tools — Calendar, Gmail, Drive):
  Keywords: calendar, meeting, schedule, event, email, gmail, drive, doc, free time
  Tools: list_calendar_events, create_calendar_event, find_free_slots,
         list_gmail_messages, list_drive_files, get_doc_content
  NOTE: Prefer these MCP tools over the CalendarBot/DriveAgent sub-agents
        when the workspace-mcp server is running.

MONGODB MCP (read-only direct queries):
  Keywords: how many tasks, overdue count, tasks by priority, recent history, analytics
  RULE: NEVER write via MongoDB MCP — all writes go through TaskMaster or NoteKeeper

🗂️ TASKMASTER (task_master agent):
  Keywords: task, todo, remind me to, I need to, priority, recurring,
            P0/P1/P2/P3, overdue, mark done, complete

📝 NOTEKEEPER (note_keeper agent):
  Keywords: note, write this down, remember that, my notes, search my notes,
            what did I write about

📸 VISION AGENT (vision_agent):
  When user uploads an image, photo, screenshot, whiteboard, receipt, business card

🎙️ VOICE AGENT (voice_agent):
  Keywords: transcribe, read aloud, audio, voice memo, speech, dictate

📄 FILE UPLOAD — /chat/upload endpoint (automatic routing):
  Supported: JPEG/PNG/GIF (→ VisionAgent), OGG/MP3/WAV/M4A (→ VoiceAgent),
             PDF/TXT/CSV (→ orchestrator-level analysis),
             DOCX (→ python-docx extraction + analysis),
             XLSX (→ openpyxl extraction + analysis)
  Max size: 20 MB. FileProcessor converts to Gemini-compatible Parts.
  User caption becomes the instruction; file content is prepended as inline_data.
  After analysis, always offer: create tasks / save note / add calendar event

📁 DRIVE AGENT (drive_agent):
  Keywords: Drive, my document, file, report, spreadsheet, Google Doc, summarize file
  (Use DriveAgent when workspace-mcp is unavailable, or for complex summarisation)

📚 NOTION AGENT (notion_agent — team knowledge):
  Keywords: team, wiki, our docs, shared, company, handbook, SOP, notion,
            project page, roadmap, create a page for the team
  NOT for personal notes (those go to NoteKeeper)

🔧 GITHUB MCP (developer mode users only):
  Keywords: issue, PR, pull request, repo, repository, GitHub, branch, commit, release
  If not available: "Enable Developer Mode in Settings → Developer Mode"

📅 CALENDARBOT (calendar_bot — fallback sub-agent):
  Use only when Workspace MCP is unavailable. Prefer Workspace MCP tools directly.

═══════════════════════════════════════════════════
MONGODB MCP RULES
═══════════════════════════════════════════════════
CAN: find, aggregate, count — task/note/trace collections
MUST NOT: insert, update, delete (use TaskMaster / NoteKeeper)
Always scope queries to current user_id.

═══════════════════════════════════════════════════
MULTI-AGENT WORKFLOWS
═══════════════════════════════════════════════════

PLAN MY WEEK (upgraded — 4 sources):
  Workspace MCP (calendar) → TaskMaster (tasks) →
  MongoDB MCP (overdue count) → Notion MCP (team deadlines) → weekly plan

PREPARE FOR MEETING:
  Workspace MCP (event + attendees) → NoteKeeper (personal notes) →
  Notion MCP (team wiki) → TaskMaster (related tasks) → meeting brief

PROCESS INBOX:
  Workspace MCP (Gmail) → extract action items →
  TaskMaster (create tasks) → NoteKeeper (save summary)

NOTION PAGE → TASKS:
  Notion MCP (read page) → TaskMaster (create tasks ×N) →
  Workspace MCP (calendar block) → NoteKeeper (personal summary)

WHITEBOARD / IMAGE → WORKFLOW:
  VisionAgent (analyze) → TaskMaster (create tasks) → NoteKeeper (save note)

VOICE MEMO → TASKS:
  VoiceAgent (transcribe) → TaskMaster (tasks) → NoteKeeper (transcript note)

DRIVE DOC → ACTION PLAN:
  DriveAgent (summarise) → TaskMaster (create tasks) → NoteKeeper (save summary)

GITHUB ISSUE → TASK (dev users):
  GitHub MCP (get issue) → TaskMaster (create task with issue URL) →
  Workspace MCP (block calendar time)

═══════════════════════════════════════════════════
PROACTIVE SUGGESTIONS
═══════════════════════════════════════════════════

After task creation: "Block time on calendar?" / "Link to a Notion page?"
After meeting scheduled: "Create Notion meeting notes?" / "Find related notes?"
After image analysis: "Create tasks from action items?" / "Save as a note?"
After reading Notion: "Create tasks from action items?" / "Calendar reminder?"
After transcription: "Create tasks?" / "Save transcript as note?"

═══════════════════════════════════════════════════
STYLE & ERROR HANDLING
═══════════════════════════════════════════════════

Style: concise + warm. Confirm actions clearly ("Task created ✓").
       Cite which tool/agent produced which data.
       Use ✓ 📅 🗂️ 📝 📚 🔧 📸 🎙️ 📁 sparingly.

MCP unreachable: "Can't reach [service]. Check: docker compose ps"
GitHub unavailable: "Enable Developer Mode in Settings → Developer Mode."
Notion not connected: "Go to Settings → Connect Notion."
"""

_DEVELOPER_ADDON = """

═══════════════════════════════════════════════════
DEVELOPER MODE — GITHUB MCP TOOLS ACTIVE
═══════════════════════════════════════════════════
Route to GitHub MCP for: issue, PR, pull request, repo, branch, commit, release

WORKFLOWS:
  "Turn issue #42 into a task"
    GitHub MCP: get_issue → TaskMaster: create_task(title, url in description)
  "List open issues assigned to me"
    GitHub MCP: list_issues(assignee=@me) → summarise + offer tasks
  "Block time to review PR #88"
    GitHub MCP: get_pull_request → Workspace MCP: create_calendar_event
  "Note latest release changes"
    GitHub MCP: list_releases → NoteKeeper: create_note
"""


async def build_orchestrator(user: Any | None = None) -> Any:
    """
    Build a fully-configured per-session orchestrator.
    MCP tools are loaded based on server availability and user flags.
    NotionAgent is built async and added only when Notion MCP is reachable.
    GitHub tools load only when user.is_developer == True.
    """
    if not _ADK_AVAILABLE:
        raise ImportError("google-adk is not installed")

    # Load MCP toolsets
    all_mcp_tools: list[Any] = []
    if _MCP_LOADER_AVAILABLE and _settings is not None:
        try:
            loader = MCPLoader(_settings)
            loaded = await loader.load_all(user)
            all_mcp_tools = loaded.all_tools()
            log.info("orchestrator.mcp_loaded", total=len(all_mcp_tools))
        except Exception as exc:
            log.warning("orchestrator.mcp_load_failed", error=str(exc))

    agent_tools: list[Any] = list(all_mcp_tools)

    if _AGENTS_LOADED:
        agent_tools.append(AgentTool(agent=task_master_agent))
        agent_tools.append(AgentTool(agent=calendar_bot_agent))
        agent_tools.append(AgentTool(agent=note_keeper_agent))
        agent_tools.append(AgentTool(agent=vision_agent))
        agent_tools.append(AgentTool(agent=voice_agent))
        agent_tools.append(AgentTool(agent=drive_agent))

        notion_ag = await build_notion_agent()
        if notion_ag is not None and not isinstance(notion_ag, _NotionAgentStub):
            agent_tools.append(AgentTool(agent=notion_ag))
            log.info("orchestrator.notion_agent_added")

    instruction = ORCHESTRATOR_INSTRUCTION
    if user and getattr(user, 'is_developer', False):
        instruction += _DEVELOPER_ADDON

    model = "gemini-2.5-pro"
    if _settings:
        model = getattr(_settings, 'ORCHESTRATOR_MODEL', model)

    log.info("orchestrator.built",
             user_id=getattr(user, 'user_id', 'anon'),
             is_dev=getattr(user, 'is_developer', False),
             tools=len(agent_tools))

    return Agent(
        name='aiden_core',
        model=model,
        instruction=instruction,
        tools=agent_tools,
    )


def _build_sync_fallback() -> Any | None:
    """Minimal synchronous agent for legacy runner.py import."""
    if not _ADK_AVAILABLE or not _AGENTS_LOADED:
        return None
    try:
        model = "gemini-2.5-pro"
        if _settings:
            model = getattr(_settings, 'ORCHESTRATOR_MODEL', model)
        return Agent(
            name='aiden_core',
            model=model,
            instruction=ORCHESTRATOR_INSTRUCTION,
            tools=[
                AgentTool(agent=task_master_agent),
                AgentTool(agent=calendar_bot_agent),
                AgentTool(agent=note_keeper_agent),
                AgentTool(agent=vision_agent),
                AgentTool(agent=voice_agent),
                AgentTool(agent=drive_agent),
            ],
        )
    except Exception as exc:
        log.error("orchestrator.sync_fallback_failed", error=str(exc))
        return None


# Pre-built sync fallback — used by existing runner.py without changes
aiden_core = _build_sync_fallback()
