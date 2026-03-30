"""
Notes management tools for ADK agents.
user_id is injected from ToolContext — never passed by the LLM.
"""
from google.adk.tools import ToolContext
from src.repositories.notes_repo import NotesRepository
from src.repositories.vector_repo import VectorRepository
from src.models.note import Note, NoteUpdate, NoteFilter
from typing import Optional
import structlog

log = structlog.get_logger()

notes_repo = NotesRepository()
vector_repo = VectorRepository()


def _get_user_id(tool_context: ToolContext) -> str:
    return tool_context.user_id


async def create_note(
    title: str,
    content: str,
    tool_context: ToolContext,
    tags: list[str] = None,
    project: str = None,
) -> dict:
    """
    Create a new note and index it for semantic search.

    Args:
        title: Note title
        content: Full note content
        tags: Categorisation tags
        project: Project name for grouping
    """
    user_id = _get_user_id(tool_context)
    tags = tags or []

    note = Note(user_id=user_id, title=title, content=content, tags=tags, project=project)
    result = await notes_repo.create_note(note)

    await vector_repo.add_embedding(
        user_id=user_id,
        document_id=note.note_id,
        text=f"{title}\n{content}",
        metadata={"type": "note", "tags": tags, "project": project}
    )
    log.info("note_created_via_tool", note_id=note.note_id, user_id=user_id)
    return {
        "note_id": result["note_id"],
        "title": result["title"],
        "tags": result["tags"],
        "project": result.get("project"),
        "message": f"Note created ✓: {title}"
    }


async def search_notes_semantic(
    query: str,
    tool_context: ToolContext,
    top_k: int = 5,
) -> dict:
    """
    Semantic search across notes using AI embeddings.

    Args:
        query: Natural language search query
        top_k: Max results to return
    """
    user_id = _get_user_id(tool_context)
    results = await vector_repo.semantic_search(user_id=user_id, query=query, top_k=top_k)
    note_ids = [r["document_id"] for r in results]
    notes = await notes_repo.get_notes_by_ids(user_id, note_ids)
    formatted = [
        {
            "note_id": n.note_id,
            "title": n.title,
            "content_preview": n.content[:200] + "..." if len(n.content) > 200 else n.content,
            "tags": n.tags,
            "project": n.project,
        }
        for n in notes
    ]
    log.info("semantic_search_via_tool", user_id=user_id, query=query, results=len(formatted))
    return {"query": query, "results": formatted, "count": len(formatted),
            "message": f"Found {len(formatted)} relevant note(s)"}


async def list_notes(
    tool_context: ToolContext,
    tags: list[str] = None,
    project: str = None,
    limit: int = 20,
) -> dict:
    """List notes with optional filters."""
    user_id = _get_user_id(tool_context)
    filters = NoteFilter(tags=tags, project=project, limit=limit)
    notes = await notes_repo.list_notes(user_id, filters)
    note_list = [
        {
            "note_id": n.note_id,
            "title": n.title,
            "content_preview": n.content[:150] + "..." if len(n.content) > 150 else n.content,
            "tags": n.tags,
            "project": n.project,
            "created_at": str(n.created_at),
        }
        for n in notes
    ]
    return {"notes": note_list, "count": len(note_list), "message": f"Found {len(note_list)} note(s)"}


async def update_note(
    note_id: str,
    tool_context: ToolContext,
    title: str = None,
    content: str = None,
    tags: list[str] = None,
    project: str = None,
) -> dict:
    """Update an existing note."""
    user_id = _get_user_id(tool_context)
    updates = NoteUpdate(title=title, content=content, tags=tags, project=project)
    note = await notes_repo.update_note(user_id, note_id, updates)
    if not note:
        return {"success": False, "message": f"Note not found: {note_id}"}

    await vector_repo.update_embedding(
        user_id=user_id, document_id=note.note_id,
        text=f"{note.title}\n{note.content}",
        metadata={"type": "note", "tags": note.tags, "project": note.project}
    )
    return {"success": True, "note_id": note.note_id, "title": note.title,
            "message": f"Note updated ✓: {note.title}"}


async def delete_note(note_id: str, tool_context: ToolContext) -> dict:
    """Delete a note permanently."""
    user_id = _get_user_id(tool_context)
    success = await notes_repo.delete_note(user_id, note_id)
    if success:
        await vector_repo.delete_embedding(user_id, note_id)
        return {"success": True, "message": f"Note deleted: {note_id}"}
    return {"success": False, "message": f"Note not found: {note_id}"}


async def get_note_by_id(note_id: str, tool_context: ToolContext) -> dict:
    """Get full details of a specific note."""
    user_id = _get_user_id(tool_context)
    note = await notes_repo.get_note(user_id, note_id)
    if not note:
        return {"success": False, "message": f"Note not found: {note_id}"}
    return {
        "success": True,
        "note_id": note.note_id,
        "title": note.title,
        "content": note.content,
        "tags": note.tags,
        "project": note.project,
        "created_at": str(note.created_at),
        "updated_at": str(note.updated_at),
    }
