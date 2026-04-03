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


@router.get("/search")
async def search_notes(
    q:     str,
    top_k: int = 5,
    current_user: UserClaims = Depends(get_current_active_user),
):
    """
    Semantic search across notes using Gemini text-embedding-004 + ChromaDB.
    Returns results ranked by cosine similarity with a score in [0, 1].
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query too short (min 2 chars)")

    search_results = await vector_repo.semantic_search(
        user_id = current_user.user_id,
        query   = q.strip(),
        top_k   = top_k,
    )

    # Fetch full note objects from MongoDB in parallel
    note_ids = [r["document_id"] for r in search_results]
    notes    = await notes_repo.get_notes_by_ids(current_user.user_id, note_ids)

    # Build a score lookup keyed by note_id
    score_map = {r["document_id"]: r["score"] for r in search_results}

    # Attach score + model to each note dict for the response
    result_list = []
    for note in notes:
        note_dict = note.model_dump() if hasattr(note, "model_dump") else dict(note)
        note_dict["_score"] = score_map.get(note_dict.get("note_id", ""), 0.0)
        note_dict["_model"] = "text-embedding-004"
        result_list.append(note_dict)

    # Re-sort by score descending (MongoDB order may differ)
    result_list.sort(key=lambda x: x["_score"], reverse=True)

    log.info(
        "semantic_search_response",
        user_id = current_user.user_id,
        query   = q,
        results = len(result_list),
    )
    return {
        "query":   q,
        "model":   "gemini/text-embedding-004",
        "results": result_list,
        "count":   len(result_list),
    }


@router.get("/search/verify")
async def verify_embeddings(
    current_user: UserClaims = Depends(get_current_active_user),
):
    """
    Quick smoke-test: embeds a short probe text and returns the vector dimensions.
    Confirms Gemini text-embedding-004 is live and returning 768-dim vectors.
    """
    from src.repositories.vector_repo import _embed_documents, _embed_query
    try:
        doc_vec   = await _embed_documents(["embedding verification probe"])
        query_vec = await _embed_query("verification query")
        return {
            "status":          "ok",
            "model":           "text-embedding-004",
            "document_dims":   len(doc_vec[0]),
            "query_dims":      len(query_vec),
            "expected_dims":   768,
            "dims_match":      len(doc_vec[0]) == 768 and len(query_vec) == 768,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Embedding verification failed: {exc}")


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
