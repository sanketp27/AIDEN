"""
Voice API endpoints using Gemini 2.5 Flash with TTS
Real audio transcription and intent analysis
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from src.models.user import UserClaims
from src.api.middleware import get_current_active_user
from src.tools.voice_tools import transcribe_audio as gemini_transcribe, analyze_audio_intent
from src.core.runner import run_agent
import base64
import structlog

log = structlog.get_logger()

router = APIRouter(prefix="/voice", tags=["Voice"])


# Response models
class TranscriptResponse(BaseModel):
    transcript: str
    language: str
    mode: str
    success: bool
    error: str | None = None


class IntentResponse(BaseModel):
    transcript: str
    intent: str
    details: dict
    mode: str
    success: bool


class VoiceQueryRequest(BaseModel):
    audio_b64: str
    language: str = "en-US"
    auto_execute: bool = True  # Auto-create tasks/notes from intent


class VoiceQueryResponse(BaseModel):
    transcript: str
    intent: str
    aiden_response: str | None = None
    actions_taken: list[dict] = []


@router.post("/transcribe", response_model=TranscriptResponse)
async def transcribe_audio_endpoint(
    file: UploadFile = File(...),
    language: str = "en-US",
    current_user: UserClaims = Depends(get_current_active_user)
) -> TranscriptResponse:
    """
    Transcribe audio to text using Gemini 2.5 Flash with TTS

    Uses Gemini's audio understanding capabilities for accurate transcription.
    """
    audio_bytes = await file.read()
    audio_b64 = base64.b64encode(audio_bytes).decode()

    log.info("voice_transcribe_gemini", user_id=current_user.user_id, file_size=len(audio_bytes))

    # Determine MIME type from file
    mime_type = file.content_type or "audio/webm"

    result = await gemini_transcribe(audio_b64, language_code=language, mime_type=mime_type)

    return TranscriptResponse(
        transcript=result.get("transcript", ""),
        language=result.get("language_detected", language),
        mode=result.get("mode", "GEMINI_2.5_FLASH_STT"),
        success=result.get("success", False),
        error=result.get("error")
    )


@router.post("/analyze", response_model=IntentResponse)
async def analyze_audio_endpoint(
    file: UploadFile = File(...),
    current_user: UserClaims = Depends(get_current_active_user)
) -> IntentResponse:
    """
    Analyze audio for intent and extract actionable information

    Returns structured intent data that can be used to auto-create tasks, notes, etc.
    """
    audio_bytes = await file.read()
    audio_b64 = base64.b64encode(audio_bytes).decode()

    log.info("voice_analyze_intent", user_id=current_user.user_id, file_size=len(audio_bytes))

    # Determine MIME type
    mime_type = file.content_type or "audio/webm"

    result = await analyze_audio_intent(audio_b64, mime_type=mime_type)

    return IntentResponse(
        transcript=result.get("transcript", ""),
        intent=result.get("intent", "general_query"),
        details=result.get("details", {}),
        mode=result.get("mode", "GEMINI_2.5_FLASH_STT"),
        success=result.get("success", False)
    )


@router.post("/query", response_model=VoiceQueryResponse)
async def voice_query_endpoint(
    request: VoiceQueryRequest,
    current_user: UserClaims = Depends(get_current_active_user)
) -> VoiceQueryResponse:
    """
    Complete voice query pipeline:
    1. Transcribe audio using Gemini
    2. Analyze intent
    3. Route to AIDEN agents for execution
    4. Return transcript, intent, and AIDEN's response

    This is the main endpoint for voice interactions.
    """
    # Step 1: Transcribe
    transcription = await gemini_transcribe(
        request.audio_b64,
        language_code=request.language,
        mime_type="audio/webm"
    )

    if not transcription.get("success"):
        raise HTTPException(status_code=400, detail="Failed to transcribe audio")

    transcript = transcription["transcript"]
    log.info("voice_query_transcribed", user_id=current_user.user_id, transcript=transcript[:100])

    # Step 2: Analyze intent
    intent_result = await analyze_audio_intent(request.audio_b64, mime_type="audio/webm")
    intent = intent_result.get("intent", "general_query")

    # Step 3: Route to AIDEN for execution
    aiden_response = None
    actions_taken = []

    if request.auto_execute:
        try:
            # Send transcript to AIDEN Core for processing
            result = await run_agent(
                user_id=current_user.user_id,
                message=transcript,
                session_id=None  # Start new session for voice queries
            )

            aiden_response = result.get("response", "")
            actions_taken = result.get("agents_used", [])

            log.info("voice_query_executed", user_id=current_user.user_id, agents=actions_taken)

        except Exception as e:
            log.error("voice_query_execution_failed", user_id=current_user.user_id, error=str(e))
            aiden_response = f"Error processing request: {str(e)}"

    return VoiceQueryResponse(
        transcript=transcript,
        intent=intent,
        aiden_response=aiden_response,
        actions_taken=actions_taken
    )
