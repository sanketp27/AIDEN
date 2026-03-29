"""
Notes management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from src.models.note import Note, NoteCreate, NoteUpdate, NoteFilter
from src.models.user import UserClaims
from src.repositories.notes_repo import NotesRepository
from src.repositories.vector_repo import VectorRepository
from src.api.middleware import get_current_active_user
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/notes", tags=["Notes"])
notes_repo = NotesRepository()
vector_repo = VectorRepository()


@router.post("", response_model=Note, status_code=201)
async def create_note(
    note_create: NoteCreate,
    current_user: UserClaims = Depends(get_current_active_user)
) -> Note:
    """Create a new note and index for semantic search"""
    note = Note(user_id=current_user.user_id, **note_create.model_dump())

    note_dict = await notes_repo.create_note(note)

    # Index in ChromaDB for semantic search
    await vector_repo.add_embedding(
        user_id=current_user.user_id,
        document_id=note.note_id,
        text=f"{note.title}\n{note.content}",
        metadata={
            "type": "note",
            "tags": note.tags,
            "project": note.project
        }
    )

    return Note(**note_dict)


@router.get("", response_model=list[Note])
async def list_notes(
    tags: list[str] | None = None,
    project: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: UserClaims = Depends(get_current_active_user)
) -> list[Note]:
    """List notes with optional filters"""
    filters = NoteFilter(tags=tags, project=project, limit=limit, offset=offset)

    return await notes_repo.list_notes(current_user.user_id, filters)


@router.get("/search", response_model=list[Note])
async def search_notes(
    q: str,
    top_k: int = 5,
    current_user: UserClaims = Depends(get_current_active_user)
) -> list[Note]:
    """Semantic search across notes"""
    # Search in ChromaDB
    search_results = await vector_repo.semantic_search(
        user_id=current_user.user_id,
        query=q,
        top_k=top_k
    )

    # Get full notes from MongoDB
    note_ids = [result["document_id"] for result in search_results]
    notes = await notes_repo.get_notes_by_ids(current_user.user_id, note_ids)

    log.info("semantic_search", user_id=current_user.user_id, query=q, results=len(notes))

    return notes


@router.get("/{note_id}", response_model=Note)
async def get_note(
    note_id: str,
    current_user: UserClaims = Depends(get_current_active_user)
) -> Note:
    """Get a single note by ID"""
    note = await notes_repo.get_note(current_user.user_id, note_id)

    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    return note


@router.patch("/{note_id}", response_model=Note)
async def update_note(
    note_id: str,
    note_update: NoteUpdate,
    current_user: UserClaims = Depends(get_current_active_user)
) -> Note:
    """Update a note"""
    note = await notes_repo.update_note(current_user.user_id, note_id, note_update)

    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Update embedding in ChromaDB
    await vector_repo.update_embedding(
        user_id=current_user.user_id,
        document_id=note.note_id,
        text=f"{note.title}\n{note.content}",
        metadata={
            "type": "note",
            "tags": note.tags,
            "project": note.project
        }
    )

    return note


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    current_user: UserClaims = Depends(get_current_active_user)
):
    """Delete a note"""
    success = await notes_repo.delete_note(current_user.user_id, note_id)

    if not success:
        raise HTTPException(status_code=404, detail="Note not found")

    # Delete embedding from ChromaDB
    await vector_repo.delete_embedding(current_user.user_id, note_id)

    return None
