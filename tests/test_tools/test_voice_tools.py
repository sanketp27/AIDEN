"""
Tests for voice_tools.py — Real Gemini STT + TTS implementation.

All Gemini API calls are mocked so these tests run without credentials.
"""
from __future__ import annotations

import base64
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

DUMMY_AUDIO_B64 = base64.b64encode(b"RIFF\x00\x00\x00\x00WAVEfmt ").decode()
DUMMY_AUDIO_BYTES = base64.b64decode(DUMMY_AUDIO_B64)


def _make_text_response(text: str) -> MagicMock:
    """Helper: build a mock Gemini generate_content response with .text"""
    mock = MagicMock()
    mock.text = text
    return mock


def _make_audio_response(audio_bytes: bytes = b"RIFF_WAV_DATA") -> MagicMock:
    """Helper: build a mock Gemini response with inline audio data."""
    mock = MagicMock()
    mock.candidates[0].content.parts[0].inline_data.data = audio_bytes
    return mock

@pytest.mark.asyncio
async def test_process_audio_success():
    """process_audio_with_gemini should return transcript on success."""
    from src.tools.voice_tools import process_audio_with_gemini

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value = \
            _make_text_response("Hello from the test audio")

        result = await process_audio_with_gemini(DUMMY_AUDIO_BYTES, mime_type="audio/wav")

    assert result["success"] is True
    assert result["transcript"] == "Hello from the test audio"
    assert result["mode"] == "GEMINI_2.5_FLASH_STT"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_process_audio_api_error():
    """process_audio_with_gemini should return success=False on API error."""
    from src.tools.voice_tools import process_audio_with_gemini

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.side_effect = \
            RuntimeError("API unavailable")

        result = await process_audio_with_gemini(DUMMY_AUDIO_BYTES)

    assert result["success"] is False
    assert result["transcript"] == ""
    assert "API unavailable" in result["error"]

@pytest.mark.asyncio
async def test_transcribe_audio_returns_transcript():
    """transcribe_audio should decode b64 audio and return the transcript."""
    from src.tools.voice_tools import transcribe_audio

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value = \
            _make_text_response("Schedule a team meeting tomorrow at 3pm")

        result = await transcribe_audio(
            audio_b64=DUMMY_AUDIO_B64,
            language_code="en-US",
            mime_type="audio/wav",
        )

    assert result["success"] is True
    assert "Schedule" in result["transcript"]
    assert result["mode"] == "GEMINI_2.5_FLASH_STT"
    assert result["language_detected"] == "en-US"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_transcribe_audio_hindi():
    """transcribe_audio should pass language hint through correctly."""
    from src.tools.voice_tools import transcribe_audio

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value = \
            _make_text_response("नमस्ते, मुझे कल तीन बजे मीटिंग चाहिए")

        result = await transcribe_audio(
            audio_b64=DUMMY_AUDIO_B64,
            language_code="hi-IN",
            mime_type="audio/ogg",
        )

    assert result["success"] is True
    assert result["language_detected"] == "hi-IN"


@pytest.mark.asyncio
async def test_transcribe_audio_failure_returns_error():
    """transcribe_audio should surface errors without raising."""
    from src.tools.voice_tools import transcribe_audio

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.side_effect = \
            Exception("quota exceeded")

        result = await transcribe_audio(audio_b64=DUMMY_AUDIO_B64)

    assert result["success"] is False
    assert "quota exceeded" in result["error"]

@pytest.mark.asyncio
async def test_analyze_audio_intent_task_creation():
    """analyze_audio_intent should parse JSON intent correctly."""
    from src.tools.voice_tools import analyze_audio_intent

    intent_json = json.dumps({
        "transcript": "Create a P1 task to review the Q2 roadmap by Friday",
        "intent": "task_creation",
        "details": {
            "title": "Review Q2 roadmap",
            "due_date": "Friday",
            "priority": "P1",
            "key_points": ["Q2 roadmap", "Friday deadline"],
        },
    })

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value = \
            _make_text_response(intent_json)

        result = await analyze_audio_intent(DUMMY_AUDIO_B64, mime_type="audio/mp3")

    assert result["success"] is True
    assert result["intent"] == "task_creation"
    assert result["details"]["priority"] == "P1"
    assert "roadmap" in result["details"]["title"].lower()


@pytest.mark.asyncio
async def test_analyze_audio_intent_fallback_on_bad_json():
    """analyze_audio_intent should fallback gracefully if Gemini returns non-JSON."""
    from src.tools.voice_tools import analyze_audio_intent

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value = \
            _make_text_response("I heard you say something but can't parse it")

        result = await analyze_audio_intent(DUMMY_AUDIO_B64)

    assert result["success"] is True
    assert result["intent"] == "general_query"
    assert "transcript" in result


@pytest.mark.asyncio
async def test_synthesize_speech_returns_audio_b64():
    """synthesize_speech should return base64-encoded WAV audio."""
    from src.tools.voice_tools import synthesize_speech

    wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value = \
            _make_audio_response(wav_bytes)

        result = await synthesize_speech(text="Hello, this is AIDEN speaking.")

    assert result["success"] is True
    assert result["mime_type"] == "audio/wav"
    assert result["mode"] == "GEMINI_2.5_FLASH_TTS"
    assert result["voice"] == "Puck"

    decoded = base64.b64decode(result["audio_b64"])
    assert decoded == wav_bytes


@pytest.mark.asyncio
async def test_synthesize_speech_custom_voice():
    """synthesize_speech should respect voice_name parameter."""
    from src.tools.voice_tools import synthesize_speech

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.return_value = \
            _make_audio_response(b"audio_data")

        result = await synthesize_speech(text="Meeting in 30 minutes.", voice_name="Charon")

    assert result["success"] is True
    assert result["voice"] == "Charon"


@pytest.mark.asyncio
async def test_synthesize_speech_api_error():
    """synthesize_speech should return success=False and include the text on error."""
    from src.tools.voice_tools import synthesize_speech

    with patch("src.tools.voice_tools.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.generate_content.side_effect = \
            RuntimeError("TTS model not available")

        result = await synthesize_speech(text="Test TTS failure")

    assert result["success"] is False
    assert result["text"] == "Test TTS failure"
    assert "TTS model not available" in result["error"]
    assert result["mode"] == "GEMINI_2.5_FLASH_TTS_FAILED"

@pytest.mark.asyncio
async def test_generate_speech_response_maps_voice_style():
    """Legacy shim should map voice_style to a Gemini voice name."""
    from src.tools.voice_tools import generate_speech_response

    with patch("src.tools.voice_tools.synthesize_speech") as mock_synth:
        mock_synth.return_value = {"success": True, "voice": "Aoede"}
        await generate_speech_response(text="Hello", voice_style="casual")

    mock_synth.assert_called_once_with(text="Hello", voice_name="Aoede")


@pytest.mark.asyncio
async def test_generate_speech_response_unknown_style_uses_puck():
    """Legacy shim should default to Puck for unknown styles."""
    from src.tools.voice_tools import generate_speech_response

    with patch("src.tools.voice_tools.synthesize_speech") as mock_synth:
        mock_synth.return_value = {"success": True, "voice": "Puck"}
        await generate_speech_response(text="Hello", voice_style="unknown_style")

    mock_synth.assert_called_once_with(text="Hello", voice_name="Puck")

def test_stt_uses_correct_model():
    """process_audio_with_gemini must call gemini-2.5-flash (not the TTS model)."""
    import inspect
    import src.tools.voice_tools as vt

    source = inspect.getsource(vt.process_audio_with_gemini)
    assert "gemini-2.5-flash" in source
    assert "gemini-2.5-flash-preview-tts" not in source, (
        "STT function must NOT use the TTS model"
    )


def test_tts_uses_correct_model():
    """synthesize_speech must call gemini-2.5-flash-preview-tts."""
    import inspect
    import src.tools.voice_tools as vt

    source = inspect.getsource(vt.synthesize_speech)
    assert "gemini-2.5-flash-preview-tts" in source


def test_no_mock_mode_in_voice_agent():
    """voice_agent.py must not contain MOCK MODE language."""
    import src.agents.voice_agent as va
    import inspect

    source = inspect.getsource(va)
    assert "MOCK MODE" not in source, "MOCK MODE string must be removed from voice_agent"
    assert "MOCK" not in va.VOICE_INSTRUCTION, "MOCK must not appear in VOICE_INSTRUCTION"
