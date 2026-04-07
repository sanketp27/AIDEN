from __future__ import annotations

import os
from typing import Optional

from google.adk.agents import Agent
from src.core.config import settings
from src.services.google_drive import get_drive_client

os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
os.environ.setdefault("GEMINI_API_KEY", settings.GEMINI_API_KEY)


async def search_drive_files(user_id: str, query: str, max_results: int = 8) -> dict:
    """
    Search the user's Google Drive for files matching a query.

    Args:
        user_id: Authenticated user ID (auto-injected).
        query: Full-text search string, e.g. "Q3 report".
        max_results: Max files to return (default 8, max 20).

    Returns:
        dict with 'files' list (id, name, mimeType, modifiedTime, webViewLink)
        and 'count'.
    """
    client = await get_drive_client(user_id)
    if not client:
        return {
            "error": (
                "Google Drive not connected. "
                "Go to Settings → Connect Google Drive to enable this feature."
            ),
            "files": [],
            "count": 0,
        }

    max_results = min(max_results, 20)
    files = await client.search_files(query, max_results=max_results)

    simplified = [
        {
            "id":           f.get("id"),
            "name":         f.get("name"),
            "type":         _friendly_mime(f.get("mimeType", "")),
            "modified":     f.get("modifiedTime", "")[:10],
            "link":         f.get("webViewLink", ""),
        }
        for f in files
    ]

    return {"files": simplified, "count": len(simplified), "query": query}


async def read_drive_file(user_id: str, file_id: str) -> dict:
    """
    Read and return the text content of a Google Drive file.

    Args:
        user_id: Authenticated user ID (auto-injected).
        file_id: The Drive file ID (from search_drive_files results).

    Returns:
        dict with 'content' (text), 'file_id', and optional 'error'.
    """
    client = await get_drive_client(user_id)
    if not client:
        return {
            "error": "Google Drive not connected. Go to Settings → Connect Google Drive.",
            "content": "",
            "file_id": file_id,
        }

    content = await client.get_file_content(file_id)
    return {"file_id": file_id, "content": content}


async def list_recent_drive_files(user_id: str, max_results: int = 10) -> dict:
    """
    List the user's most recently modified Google Drive files.

    Args:
        user_id: Authenticated user ID (auto-injected).
        max_results: Number of files to return (default 10, max 20).

    Returns:
        dict with 'files' list and 'count'.
    """
    client = await get_drive_client(user_id)
    if not client:
        return {
            "error": "Google Drive not connected. Go to Settings → Connect Google Drive.",
            "files": [],
            "count": 0,
        }

    max_results = min(max_results, 20)
    files = await client.list_recent_files(max_results=max_results)
    simplified = [
        {
            "id":       f.get("id"),
            "name":     f.get("name"),
            "type":     _friendly_mime(f.get("mimeType", "")),
            "modified": f.get("modifiedTime", "")[:10],
            "link":     f.get("webViewLink", ""),
        }
        for f in files
    ]
    return {"files": simplified, "count": len(simplified)}


def _friendly_mime(mime: str) -> str:
    _MAP = {
        "application/vnd.google-apps.document":     "Google Doc",
        "application/vnd.google-apps.spreadsheet":  "Google Sheet",
        "application/vnd.google-apps.presentation": "Google Slides",
        "application/vnd.google-apps.folder":       "Folder",
        "application/pdf":                          "PDF",
        "text/plain":                               "Text",
        "image/jpeg":                               "Image (JPEG)",
        "image/png":                                "Image (PNG)",
    }
    return _MAP.get(mime, mime.split("/")[-1] if "/" in mime else mime)


DRIVE_INSTRUCTION = """You are DriveAgent, AIDEN's Google Drive specialist.

CAPABILITIES:
- Search across all files in the user's Google Drive
- Read and summarize document contents (Google Docs, Sheets, Slides, PDFs)
- List recently modified files
- Combine Drive content with other agents to complete workflows

ROUTING TRIGGERS (you are called when user):
- Mentions "Drive", "document", "file", "report", "spreadsheet", "slides", "Docs"
- Asks to "find", "search", "read", "open", "summarize" a file
- References a specific document by name (e.g., "the Q3 report", "my budget spreadsheet")
- Wants to use a Drive document as context for a task or note

DRIVE NOT CONNECTED:
If the user hasn't connected Google Drive, guide them:
"To access your Drive files, go to Settings → Connect Google Drive.
It uses the same Google account as Gmail/Calendar."

WORKFLOW EXAMPLES:

1. File search:
   User: "Find my Q3 report"
   → Call search_drive_files(query="Q3 report")
   → Return list of matching files with links

2. Document summarize:
   User: "Summarize the Q3 report"
   → Call search_drive_files(query="Q3 report") to find file_id
   → Call read_drive_file(file_id=...) to get content
   → Provide concise summary

3. Cross-agent workflow (with orchestrator coordinating):
   User: "Create tasks from my project plan doc"
   → Read the document (read_drive_file)
   → Extract action items
   → (Orchestrator routes to TaskMaster for task creation)

BEHAVIOR RULES:
1. Always confirm which file you're reading before summarizing
2. For large documents, summarize key sections — don't dump raw content
3. Extract actionable insights (dates, people, tasks, decisions)
4. Offer to create notes or tasks from document content
5. Provide direct links to files so users can open them

OUTPUT FORMAT:
📁 File found: [name] ([type], modified [date])
🔗 Link: [webViewLink]

[Summary or content as appropriate]

Want me to:
- Create tasks from action items found?
- Save a summary as a note?
- Search for related files?
"""

drive_agent = Agent(
    name="drive_agent",
    model=settings.DEFAULT_MODEL,
    instruction=DRIVE_INSTRUCTION,
    tools=[search_drive_files, read_drive_file, list_recent_drive_files],
)
