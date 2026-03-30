"""
Vision API endpoints — supports both multipart file upload (Streamlit UI)
and JSON base64 payload (React UI / programmatic access).
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from src.models.user import UserClaims
from src.api.middleware import get_current_active_user
from src.tools.vision_tools import classify_image, analyze_image, extract_tasks_from_image
from src.repositories.task_repo import TaskRepository
from src.repositories.notes_repo import NotesRepository
from src.models.task import Task, Priority
from src.models.note import Note
import base64
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/vision", tags=["Vision"])
task_repo = TaskRepository()
notes_repo = NotesRepository()


# ── Response model ──────────────────────────────────────────────────────────
class VisionAnalysisResponse(BaseModel):
    image_type: str
    confidence: float
    description: str
    extracted_data: dict
    extracted_tasks: list[dict] = []
    extracted_text: Optional[str] = None
    tasks_created: int = 0
    notes_created: int = 0
    message: str


# ── Shared analysis logic ───────────────────────────────────────────────────
async def _run_analysis(
    image_b64: str,
    filename: str,
    auto_create_tasks: bool,
    auto_create_note: bool,
    current_user: UserClaims,
) -> VisionAnalysisResponse:
    # Step 1: Classify
    classification = await classify_image(image_b64)
    image_type  = classification.get("type", "photo")
    confidence  = classification.get("confidence", 0.0)
    description = classification.get("description", "")

    # Step 2: Deep extraction
    extraction = await analyze_image(image_b64, image_type)
    extracted_text = (
        extraction.get("text")
        or extraction.get("content")
        or extraction.get("description")
    )

    # Step 3: Extract tasks list
    task_extraction = await extract_tasks_from_image(image_b64)
    raw_tasks = task_extraction.get("tasks", [])

    # Step 4: Auto-create tasks
    tasks_created = 0
    if auto_create_tasks and raw_tasks:
        for td in raw_tasks:
            task = Task(
                user_id=current_user.user_id,
                title=td.get("title", "Untitled task"),
                description=td.get("description"),
                priority=Priority(td.get("priority", "P2")),
                tags=td.get("tags", []) + ["from-image"],
            )
            await task_repo.create_task(task)
            tasks_created += 1

    # Step 5: Auto-create note
    notes_created = 0
    if auto_create_note:
        content = f"Image Type: {image_type}\nDescription: {description}\n\n"
        if extracted_text:
            content += f"Extracted Text:\n{extracted_text}\n"
        note = Note(
            user_id=current_user.user_id,
            title=f"Vision: {filename}",
            content=content.strip(),
            tags=["from-image", image_type, "vision"],
        )
        await notes_repo.create_note(note)
        notes_created = 1

    msg = f"Analysed {image_type} image."
    if tasks_created:
        msg += f" Created {tasks_created} task(s)."
    if notes_created:
        msg += f" Created {notes_created} note(s)."

    log.info("vision_analyse_complete", user_id=current_user.user_id,
             image_type=image_type, tasks_created=tasks_created)

    return VisionAnalysisResponse(
        image_type=image_type,
        confidence=confidence,
        description=description,
        extracted_data=extraction,
        extracted_tasks=raw_tasks,
        extracted_text=extracted_text,
        tasks_created=tasks_created,
        notes_created=notes_created,
        message=msg,
    )


# ── Endpoint 1: multipart upload (Streamlit) ───────────────────────────────
@router.post("/analyze/upload", response_model=VisionAnalysisResponse)
async def analyze_image_upload(
    file: UploadFile = File(...),
    auto_create_tasks: bool = True,
    auto_create_note: bool = False,
    current_user: UserClaims = Depends(get_current_active_user),
) -> VisionAnalysisResponse:
    """Analyse image via multipart file upload."""
    if file.content_type not in ["image/jpeg", "image/png", "image/webp", "image/gif"]:
        raise HTTPException(400, "Unsupported format. Use JPG, PNG, WEBP, or GIF.")

    image_bytes = await file.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "Image exceeds 20 MB limit.")

    return await _run_analysis(
        image_b64=base64.b64encode(image_bytes).decode(),
        filename=file.filename or "image",
        auto_create_tasks=auto_create_tasks,
        auto_create_note=auto_create_note,
        current_user=current_user,
    )


# ── Endpoint 2: JSON base64 (React UI) ─────────────────────────────────────
class VisionJsonRequest(BaseModel):
    image_b64: str
    filename: str = "image"
    auto_create_tasks: bool = False   # React UI: let user decide explicitly
    auto_create_note: bool = False


@router.post("/analyze", response_model=VisionAnalysisResponse)
async def analyze_image_json(
    request: VisionJsonRequest,
    current_user: UserClaims = Depends(get_current_active_user),
) -> VisionAnalysisResponse:
    """Analyse image via JSON body with base64-encoded image."""
    try:
        image_bytes = base64.b64decode(request.image_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 image data.")

    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "Image exceeds 20 MB limit.")

    return await _run_analysis(
        image_b64=request.image_b64,
        filename=request.filename,
        auto_create_tasks=request.auto_create_tasks,
        auto_create_note=request.auto_create_note,
        current_user=current_user,
    )
