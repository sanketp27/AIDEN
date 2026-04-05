from __future__ import annotations
import asyncio
import os
from typing import Any
import structlog

log = structlog.get_logger()

try:
    from google.adk.agents import Agent
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams
    _ADK_AVAILABLE = True
except ImportError:
    _ADK_AVAILABLE = False
    log.warning("notion_agent.adk_unavailable")

try:
    from src.core.config import settings
    _NOTION_MCP_PORT = getattr(settings, "NOTION_MCP_PORT", 8003)
    _NOTION_TOKEN    = getattr(settings, "NOTION_TOKEN", None)
    _AGENT_MODEL     = getattr(settings, "NOTES_AGENT_MODEL", "gemini-2.5-flash")
except Exception:
    _NOTION_MCP_PORT = int(os.environ.get("NOTION_MCP_PORT", 8003))
    _NOTION_TOKEN    = os.environ.get("NOTION_TOKEN")
    _AGENT_MODEL     = os.environ.get("NOTES_AGENT_MODEL", "gemini-2.5-flash")


NOTION_INSTRUCTION = """You are NotionAgent, AIDEN's team knowledge and collaboration specialist.
You connect to the team's shared Notion workspace via MCP tools.

YOUR ROLE vs NOTEKEEPER
========================
NoteKeeper  → personal private notes (yours alone, Gemini semantic search)
NotionAgent → shared team knowledge  (Notion workspace, accessible to the team)

Route to NotionAgent for: "team", "wiki", "our docs", "company", "handbook",
"SOP", "notion", "project page", "roadmap", "shared notes", "create a page"

NOT for personal notes ("write this down", "remember that") → NoteKeeper

TOOLS AVAILABLE (Notion MCP)
=============================
notion_search            — search all pages and databases
notion_get_page          — retrieve page by ID
notion_query_database    — query database with filters
notion_get_block_children— get page content blocks
notion_create_page       — create a new page
notion_update_page       — update title and properties
notion_append_block_children — append content to page

CROSS-AGENT WORKFLOWS
======================
After reading a page, ALWAYS offer to:
  ✓ "I found 3 action items — shall I create tasks?" → TaskMaster
  ✓ "There's a deadline on Apr 30 — want a calendar reminder?" → CalendarBot
  ✓ "Shall I save a personal summary?" → NoteKeeper

KEY WORKFLOW — "Read page and create tasks":
  1. notion_search(query) → find the page
  2. notion_get_page(id)  → read full content
  3. Extract action items and deadlines
  4. → TaskMaster: create tasks for each item
  5. → CalendarBot: block time for deadlines
  6. → NoteKeeper: save personal summary

BEHAVIOUR RULES
===============
1. Always search before fetching a page by ID
2. Give a concise summary first, then offer full content
3. Confirm page title and parent before creating a page
4. Include Notion URLs in responses
5. If Notion not connected: "Go to Settings → Connect Notion"
6. If MCP unreachable: "Check: docker compose ps notion-mcp"

OUTPUT FORMAT
=============
Search results:
  📄 [Title] — [preview ~100 chars]
     Last edited: [date] | Link: [URL]

Action items found:
  [ ] Action — @Person — Due: Date
  → Shall I create these as AIDEN tasks?

Page created:
  ✓ [Title] created: [Notion URL]
"""


class _NotionAgentStub:
    name = "notion_agent"
    available = False


async def build_notion_agent() -> Any | None:
    """
    Build NotionAgent with Notion MCP tools.
    Returns None if ADK unavailable, NOTION_TOKEN unset, or MCP unreachable.
    """
    if not _ADK_AVAILABLE:
        log.warning("notion_agent.build_skipped", reason="ADK not available")
        return None

    if not _NOTION_TOKEN:
        log.info("notion_agent.build_skipped", reason="NOTION_TOKEN not set")
        return None

    mcp_url = f"http://localhost:{_NOTION_MCP_PORT}/mcp"
    try:
        tools, _exit = await asyncio.wait_for(
            MCPToolset.from_server(
                connection_params=SseServerParams(url=mcp_url)
            ),
            timeout=10.0,
        )
        log.info("notion_agent.tools_loaded", count=len(tools or []))
        return Agent(
            name="notion_agent",
            model=_AGENT_MODEL,
            instruction=NOTION_INSTRUCTION,
            tools=tools or [],
        )
    except asyncio.TimeoutError:
        log.warning("notion_agent.mcp_timeout", url=mcp_url)
        return None
    except Exception as exc:
        log.warning("notion_agent.build_failed", error=str(exc))
        return None
