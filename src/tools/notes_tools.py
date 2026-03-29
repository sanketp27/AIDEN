"""
Note management tools for ADK agents
Includes semantic search via ChromaDB
"""
from src.tools.tool_decorator import tool
from src.repositories.notes_repo import NotesRepository
from src.repositories.vector_repo import VectorRepository
from src.models.note import Note
from typing import Optional
import structlog

log = structlog.get_logger()

# Repository instances
notes_repo = NotesRepository()
vector_repo = VectorRepository()


@tool
async def create_note(
    user_id: str,
    title: str,
    content: str,
    tags: list[str] = None,
    project: str = None
) -> dict:
    """
    Create a new note and index it for semantic search.

    Args:
        user_id: User identifier
        title: Note title
        content: Note content (full text)
        tags: List of tags for categorization
        project: Project name for grouping

    Returns:
        Created note information with note_id
    """
    tags = tags or []

    note = Note(
        user_id=user_id,
        title=title,
        content=content,
        tags=tags,
        project=project
    )

    result = await notes_repo.create_note(note)

    # Index in ChromaDB for semantic search
    await vector_repo.add_embedding(
        user_id=user_id,
        document_id=note.note_id,
        text=f"{title}\n{content}",
        metadata={
            "type": "note",
            "tags": tags,
            "project": project
        }
    )

    log.info("note_created_via_tool", note_id=result['note_id'], user_id=user_id, title=title)

    return {
        "note_id": result['note_id'],
        "title": result['title'],
        "tags": result['tags'],
        "project": result.get('project'),
        "message": f"Note created and indexed: {title}"
    }


@tool
async def search_notes_semantic(
    user_id: str,
    query: str,
    top_k: int = 5
) -> dict:
    """
    Search notes using semantic similarity (AI-powered search).

    This searches by meaning, not just keywords. For example:
    - "implementation details" will find notes about "how we built this"
    - "Q1 planning" will find notes about "first quarter strategy"

    Args:
        user_id: User identifier
        query: Search query (natural language)
        top_k: Number of results to return (default: 5)

    Returns:
        List of relevant notes with similarity scores
    """
    # Search in ChromaDB
    search_results = await vector_repo.semantic_search(
        user_id=user_id,
        query=query,
        top_k=top_k
    )

    # Get full notes from MongoDB
    note_ids = [result["document_id"] for result in search_results]
    notes = await notes_repo.get_notes_by_ids(user_id, note_ids)

    # Format results
    results = []
    for note in notes:
        results.append({
            "note_id": note.note_id,
            "title": note.title,
            "content_preview": note.content[:200] + "..." if len(note.content) > 200 else note.content,
            "tags": note.tags,
            "project": note.project
        })

    log.info("semantic_search_via_tool", user_id=user_id, query=query, results=len(results))

    return {
        "query": query,
        "results": results,
        "count": len(results),
        "message": f"Found {len(results)} relevant note(s) for: {query}"
    }


@tool
async def list_notes(
    user_id: str,
    tags: list[str] = None,
    project: str = None,
    limit: int = 20
) -> dict:
    """
    List notes with optional filters.

    Args:
        user_id: User identifier
        tags: Filter by tags (returns notes matching any tag)
        project: Filter by project name
        limit: Maximum number of notes to return (default: 20)

    Returns:
        List of notes
    """
    from src.models.note import NoteFilter

    filters = NoteFilter(
        tags=tags,
        project=project,
        limit=limit
    )

    notes = await notes_repo.list_notes(user_id, filters)

    # Format notes
    note_list = []
    for note in notes:
        note_list.append({
            "note_id": note.note_id,
            "title": note.title,
            "content_preview": note.content[:150] + "..." if len(note.content) > 150 else note.content,
            "tags": note.tags,
            "project": note.project,
            "created_at": str(note.created_at)
        })

    log.info("notes_listed_via_tool", user_id=user_id, count=len(note_list))

    return {
        "notes": note_list,
        "count": len(note_list),
        "message": f"Found {len(note_list)} note(s)"
    }


@tool
async def update_note(
    user_id: str,
    note_id: str,
    title: str = None,
    content: str = None,
    tags: list[str] = None,
    project: str = None
) -> dict:
    """
    Update an existing note.

    Args:
        user_id: User identifier
        note_id: Note identifier
        title: New title
        content: New content
        tags: New tags list
        project: New project name

    Returns:
        Updated note information
    """
    from src.models.note import NoteUpdate

    updates = NoteUpdate(
        title=title,
        content=content,
        tags=tags,
        project=project
    )

    note = await notes_repo.update_note(user_id, note_id, updates)

    if not note:
        return {
            "success": False,
            "message": f"Note not found: {note_id}"
        }

    # Update embedding in ChromaDB
    await vector_repo.update_embedding(
        user_id=user_id,
        document_id=note.note_id,
        text=f"{note.title}\n{note.content}",
        metadata={
            "type": "note",
            "tags": note.tags,
            "project": note.project
        }
    )

    log.info("note_updated_via_tool", note_id=note_id, user_id=user_id)

    return {
        "success": True,
        "note_id": note.note_id,
        "title": note.title,
        "message": f"Note updated: {note.title}"
    }


@tool
async def delete_note(
    user_id: str,
    note_id: str
) -> dict:
    """
    Delete a note permanently.

    Args:
        user_id: User identifier
        note_id: Note identifier to delete

    Returns:
        Confirmation message
    """
    success = await notes_repo.delete_note(user_id, note_id)

    if success:
        # Delete from ChromaDB
        await vector_repo.delete_embedding(user_id, note_id)

        log.info("note_deleted_via_tool", note_id=note_id, user_id=user_id)
        return {
            "success": True,
            "message": f"Note deleted: {note_id}"
        }
    else:
        return {
            "success": False,
            "message": f"Note not found: {note_id}"
        }


@tool
async def get_note_by_id(
    user_id: str,
    note_id: str
) -> dict:
    """
    Get detailed information about a specific note.

    Args:
        user_id: User identifier
        note_id: Note identifier

    Returns:
        Full note details
    """
    note = await notes_repo.get_note(user_id, note_id)

    if not note:
        return {
            "success": False,
            "message": f"Note not found: {note_id}"
        }

    return {
        "success": True,
        "note_id": note.note_id,
        "title": note.title,
        "content": note.content,
        "tags": note.tags,
        "project": note.project,
        "created_at": str(note.created_at),
        "updated_at": str(note.updated_at)
    }
