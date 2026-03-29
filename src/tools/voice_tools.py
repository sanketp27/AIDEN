"""
Voice tools using Gemini Client directly
Uses gemini-2.5-flash-preview-tts for audio understanding and generation
"""
from google import genai
from google.genai import types
import base64
import structlog
import io

log = structlog.get_logger()


async def process_audio_with_gemini(
    audio_bytes: bytes,
    prompt: str = "Describe what the user is saying in this audio",
    mime_type: str = "audio/webm"
) -> dict:
    """
    Process audio using Gemini 2.5 Flash with TTS preview

    Args:
        audio_bytes: Raw audio data
        prompt: Instruction for processing the audio
        mime_type: Audio format (audio/webm, audio/mp3, audio/wav)

    Returns:
        Dictionary with transcript and analysis
    """
    try:
        client = genai.Client()

        # Create content with audio part
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type=mime_type,
                )
            ]
        )

        log.info("gemini_audio_processed", audio_size=len(audio_bytes), mime_type=mime_type)

        return {
            "transcript": response.text,
            "mode": "GEMINI_2.5_FLASH_TTS",
            "success": True
        }

    except Exception as e:
        log.error("gemini_audio_error", error=str(e))
        return {
            "transcript": "",
            "error": str(e),
            "mode": "GEMINI_2.5_FLASH_TTS",
            "success": False
        }


async def transcribe_audio(
    audio_b64: str,
    language_code: str = "en-US",
    mime_type: str = "audio/webm"
) -> dict:
    """
    Transcribe audio to text using Gemini 2.5 Flash TTS

    Args:
        audio_b64: Base64-encoded audio
        language_code: Language hint (not strictly enforced by Gemini)
        mime_type: Audio format

    Returns:
        Dictionary with transcript
    """
    audio_bytes = base64.b64decode(audio_b64)

    prompt = f"Transcribe this audio clip. Language: {language_code}. Provide only the transcript text."

    result = await process_audio_with_gemini(audio_bytes, prompt, mime_type)

    return {
        "transcript": result.get("transcript", ""),
        "language_detected": language_code,
        "mode": "GEMINI_2.5_FLASH_TTS",
        "success": result.get("success", False),
        "error": result.get("error")
    }


async def analyze_audio_intent(
    audio_b64: str,
    mime_type: str = "audio/webm"
) -> dict:
    """
    Analyze audio for user intent and extract actionable information

    Args:
        audio_b64: Base64-encoded audio
        mime_type: Audio format

    Returns:
        Dictionary with intent analysis
    """
    audio_bytes = base64.b64decode(audio_b64)

    prompt = """Analyze this audio clip and respond in JSON format:
{
    "transcript": "exact words spoken",
    "intent": "task_creation|note_creation|calendar_event|search|general_query",
    "details": {
        "title": "extracted title if creating something",
        "due_date": "extracted date if mentioned",
        "priority": "P1|P2|P3|P4 if mentioned",
        "key_points": ["extracted key information"]
    }
}"""

    result = await process_audio_with_gemini(audio_bytes, prompt, mime_type)

    try:
        import json
        analysis = json.loads(result.get("transcript", "{}"))
        return {
            "success": True,
            "mode": "GEMINI_2.5_FLASH_TTS",
            **analysis
        }
    except:
        return {
            "success": True,
            "mode": "GEMINI_2.5_FLASH_TTS",
            "transcript": result.get("transcript", ""),
            "intent": "general_query"
        }


async def generate_speech_response(
    text: str,
    voice_style: str = "professional"
) -> dict:
    """
    Generate audio response using Gemini TTS

    Note: Gemini 2.5 Flash TTS primarily does audio understanding.
    For TTS generation, we return text that can be sent to a TTS service.

    Args:
        text: Text to speak
        voice_style: Style hint (professional, casual, friendly)

    Returns:
        Dictionary with text response (audio generation requires additional TTS service)
    """
    return {
        "text": text,
        "mode": "TEXT_ONLY",
        "message": "Audio generation requires separate TTS service. Returning text response.",
        "voice_style": voice_style
    }
