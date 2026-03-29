"""
Vision API endpoints with Gemini Vision integration
Powered by Google ADK and Vision Agent
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
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


# Response models
class VisionAnalysisResponse(BaseModel):
    image_type: str
    confidence: float
    description: str
    extracted_data: dict
    tasks_created: int = 0
    notes_created: int = 0
    message: str


@router.post("/analyze", response_model=VisionAnalysisResponse)
async def analyze_image_endpoint(
    file: UploadFile = File(...),
    auto_create_tasks: bool = True,
    auto_create_note: bool = False,
    current_user: UserClaims = Depends(get_current_active_user)
) -> VisionAnalysisResponse:
    """
    Analyze image using Gemini Vision and extract structured data

    Supports: whiteboard, handwritten notes, documents, screenshots, business cards, slides, receipts

    Args:
        file: Image file (JPG, PNG, WEBP)
        auto_create_tasks: Automatically create tasks from extracted action items
        auto_create_note: Automatically create a note with extracted content
        current_user: Authenticated user

    Returns:
        Analysis results with extracted data and counts of items created
    """
    # Validate file type
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format. Use JPG, PNG, or WEBP."
        )

    image_bytes = await file.read()

    # Validate size
    max_size = 20 * 1024 * 1024  # 20MB
    if len(image_bytes) > max_size:
        raise HTTPException(status_code=413, detail="Image exceeds 20MB limit")

    log.info("vision_analyze_start",
            user_id=current_user.user_id,
            file_size=len(image_bytes),
            filename=file.filename)

    try:
        # Encode image to base64
        image_b64 = base64.b64encode(image_bytes).decode()

        # Step 1: Classify image
        classification = await classify_image(image_b64)
        image_type = classification.get('type', 'photo')
        confidence = classification.get('confidence', 0.0)
        description = classification.get('description', '')

        # Step 2: Analyze and extract structured data
        extraction = await analyze_image(image_b64, image_type)

        # Step 3: Auto-create tasks if requested
        tasks_created = 0
        if auto_create_tasks:
            task_extraction = await extract_tasks_from_image(image_b64)
            tasks = task_extraction.get('tasks', [])

            for task_data in tasks:
                task = Task(
                    user_id=current_user.user_id,
                    title=task_data['title'],
                    description=task_data.get('description'),
                    priority=Priority(task_data.get('priority', 'P2')),
                    tags=task_data.get('tags', [])
                )
                await task_repo.create_task(task)
                tasks_created += 1

        # Step 4: Auto-create note if requested
        notes_created = 0
        if auto_create_note:
            # Create comprehensive note from extraction
            content = f"Image Type: {image_type}\n\n"

            if extraction.get('text'):
                content += f"Extracted Text:\n{extraction['text']}\n\n"

            if extraction.get('action_items'):
                content += "Action Items:\n"
                for item in extraction['action_items']:
                    content += f"- {item}\n"
                content += "\n"

            note = Note(
                user_id=current_user.user_id,
                title=f"Image Analysis: {file.filename}",
                content=content.strip(),
                tags=['from-image', image_type, 'vision-analysis']
            )
            await notes_repo.create_note(note)
            notes_created = 1

        message = f"Analyzed {image_type} image. "
        if tasks_created > 0:
            message += f"Created {tasks_created} task(s). "
        if notes_created > 0:
            message += f"Created {notes_created} note(s)."

        log.info("vision_analyze_complete",
                user_id=current_user.user_id,
                image_type=image_type,
                tasks_created=tasks_created,
                notes_created=notes_created)

        return VisionAnalysisResponse(
            image_type=image_type,
            confidence=confidence,
            description=description,
            extracted_data=extraction,
            tasks_created=tasks_created,
            notes_created=notes_created,
            message=message
        )

    except Exception as e:
        log.error("vision_analyze_failed",
                 user_id=current_user.user_id,
                 error=str(e))

        raise HTTPException(
            status_code=500,
            detail=f"Image analysis failed: {str(e)}"
        )
