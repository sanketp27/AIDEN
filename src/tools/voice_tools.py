"""
Voice tools — Real STT + TTS via Gemini (no GCP credentials needed)

STT:  gemini-2.5-flash               (native audio inline_data understanding)
TTS:  gemini-2.5-flash-preview-tts   (audio generation)
Live: gemini-3.1-flash-live-preview  (WebSocket real-time — see gemini_live.py)
"""
from google import genai
from google.genai import types
import base64
import json
import structlog

log = structlog.get_logger()

async def process_audio_with_gemini(
    audio_bytes: bytes,
    prompt: str = "Transcribe this audio clip. Provide only the spoken words, nothing else.",
    mime_type: str = "audio/webm",
) -> dict:
    """
    Route audio to Gemini 2.5 Flash for understanding / transcription.
    Gemini 2.5 Flash natively understands audio inline_data — no GCP Speech API needed.
    """
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(parts=[
                    types.Part(text=prompt),
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                ])
            ],
        )
        log.info("gemini_stt_success", audio_size=len(audio_bytes), mime_type=mime_type)
        return {
            "transcript": response.text,
            "mode": "GEMINI_2.5_FLASH_STT",
            "success": True,
            "error": None,
        }
    except Exception as e:
        log.error("gemini_stt_error", error=str(e), mime_type=mime_type)
        return {
            "transcript": "",
            "mode": "GEMINI_2.5_FLASH_STT",
            "success": False,
            "error": str(e),
        }


async def transcribe_audio(
    audio_b64: str,
    language_code: str = "en-US",
    mime_type: str = "audio/webm",
) -> dict:
    """
    Transcribe audio to text using Gemini 2.5 Flash (STT).
    No GCP credentials required — uses GEMINI_API_KEY only.
    """
    audio_bytes = base64.b64decode(audio_b64)
    prompt = (
        f"Transcribe this audio clip accurately. Language: {language_code}. "
        "Provide only the transcript text — no explanations, no preamble."
    )
    result = await process_audio_with_gemini(audio_bytes, prompt, mime_type)
    return {
        "transcript": result.get("transcript", ""),
        "language_detected": language_code,
        "mode": result.get("mode", "GEMINI_2.5_FLASH_STT"),
        "success": result.get("success", False),
        "error": result.get("error"),
    }


async def analyze_audio_intent(
    audio_b64: str,
    mime_type: str = "audio/webm",
) -> dict:
    """
    Analyse audio for user intent and extract actionable details.
    Returns structured JSON with transcript, intent, and detail fields.
    """
    audio_bytes = base64.b64decode(audio_b64)
    prompt = (
        "Analyse this audio clip and respond ONLY with valid JSON (no markdown fences):\n"
        "{\n"
        '    "transcript": "exact words spoken",\n'
        '    "intent": "task_creation|note_creation|calendar_event|search|general_query",\n'
        '    "details": {\n'
        '        "title": "extracted title if creating something",\n'
        '        "due_date": "extracted date if mentioned, else null",\n'
        '        "priority": "P1|P2|P3 if mentioned, else null",\n'
        '        "key_points": ["extracted key information"]\n'
        "    }\n"
        "}"
    )
    result = await process_audio_with_gemini(audio_bytes, prompt, mime_type)

    try:
        raw = result.get("transcript", "{}")
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        analysis = json.loads(raw)
        return {
            "success": True,
            "mode": "GEMINI_2.5_FLASH_STT",
            **analysis,
        }
    except Exception:
        return {
            "success": True,
            "mode": "GEMINI_2.5_FLASH_STT",
            "transcript": result.get("transcript", ""),
            "intent": "general_query",
            "details": {"key_points": []},
        }


async def synthesize_speech(
    text: str,
    voice_name: str = "Puck",
) -> dict:
    """
    Generate spoken audio from text using gemini-2.5-flash-preview-tts.
    Returns base64-encoded WAV bytes for direct playback in the UI.

    Available Gemini voice names: Puck, Charon, Kore, Fenrir, Aoede
    """
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=[
                types.Content(parts=[
                    types.Part(text=text),
                ])
            ],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name
                        )
                    )
                ),
            ),
        )

        audio_data = response.candidates[0].content.parts[0].inline_data.data
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        log.info("gemini_tts_success", text_length=len(text), voice=voice_name)
        return {
            "audio_b64": audio_b64,
            "mime_type": "audio/wav",
            "voice": voice_name,
            "mode": "GEMINI_2.5_FLASH_TTS",
            "success": True,
        }

    except Exception as e:
        log.error("gemini_tts_error", error=str(e), voice=voice_name)
        return {
            "text": text,
            "error": str(e),
            "mode": "GEMINI_2.5_FLASH_TTS_FAILED",
            "success": False,
        }

async def generate_speech_response(text: str, voice_style: str = "professional") -> dict:
    """Compatibility shim — delegates to synthesize_speech()."""
    style_to_voice = {
        "professional": "Puck",
        "casual": "Aoede",
        "friendly": "Kore",
        "formal": "Charon",
    }
    return await synthesize_speech(text=text, voice_name=style_to_voice.get(voice_style, "Puck"))
