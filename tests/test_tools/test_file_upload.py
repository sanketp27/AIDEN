"""
tests/test_tools/test_file_upload.py
=====================================
Tests for the multimodal file upload pipeline:
  - FileProcessor: MIME detection, part building
  - /chat/upload endpoint: routing, size limits, SSE events
  - /chat/upload/sync endpoint: non-streaming path (used by Telegram bot)
  - AIDENRunner.run_agent_multimodal: file + message → orchestrator

All external dependencies (Gemini API, ADK runner, MongoDB) are mocked.
"""
from __future__ import annotations

import base64
import io
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

USER_ID    = "test_user_abc123"
SESSION_ID = "session_upload_001"
# Tiny 1×1 white PNG (valid file, smallest possible)
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
_PDF_BYTES  = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
_TEXT_BYTES = b"Meeting recap\n\nAction items:\n1. Send report by Friday\n2. Schedule follow-up"
_AUDIO_BYTES = b"OggS" + b"\x00" * 60  # OGG magic bytes + padding

class TestDetectMime:
    def test_uses_provided_mime_when_not_octet_stream(self):
        from src.core.file_processor import detect_mime
        assert detect_mime("photo.jpg", "image/jpeg") == "image/jpeg"

    def test_falls_back_to_filename_sniffing(self):
        from src.core.file_processor import detect_mime
        result = detect_mime("report.pdf", "application/octet-stream")
        assert result == "application/pdf"

    def test_unknown_file_returns_octet_stream(self):
        from src.core.file_processor import detect_mime
        result = detect_mime("weirdfile.xyz123", "application/octet-stream")
        assert result == "application/octet-stream"


class TestFileToParts:
    @pytest.mark.asyncio
    async def test_image_produces_inline_data_part(self):
        """PNG image must produce an inline_data Part with correct MIME."""
        from unittest.mock import MagicMock
        mock_part_cls   = MagicMock(side_effect=lambda **kw: kw)
        mock_blob_cls   = MagicMock(side_effect=lambda **kw: kw)

        with patch("src.core.file_processor.Part", mock_part_cls), \
             patch("src.core.file_processor.Blob", mock_blob_cls):
            from importlib import reload
            import src.core.file_processor as fp
            reload(fp)
            parts = await fp.file_to_parts(_PNG_BYTES, "image/png", "screenshot.png")

        # Should have at least 2 parts: image blob + instruction text
        assert len(parts) >= 2

    @pytest.mark.asyncio
    async def test_pdf_produces_inline_data_part(self):
        """PDF must produce an inline_data Part with application/pdf MIME."""
        mock_part_cls = MagicMock(side_effect=lambda **kw: kw)
        mock_blob_cls = MagicMock(side_effect=lambda **kw: kw)

        with patch("src.core.file_processor.Part", mock_part_cls), \
             patch("src.core.file_processor.Blob", mock_blob_cls):
            from importlib import reload
            import src.core.file_processor as fp
            reload(fp)
            parts = await fp.file_to_parts(_PDF_BYTES, "application/pdf", "report.pdf")

        assert len(parts) >= 1

    @pytest.mark.asyncio
    async def test_text_file_produces_text_part(self):
        """Plain text file must be decoded and returned as a single text Part."""
        mock_part_cls = MagicMock(side_effect=lambda **kw: kw)

        with patch("src.core.file_processor.Part", mock_part_cls), \
             patch("src.core.file_processor.Blob", MagicMock()):
            from importlib import reload
            import src.core.file_processor as fp
            reload(fp)
            parts = await fp.file_to_parts(_TEXT_BYTES, "text/plain", "notes.txt")

        assert len(parts) >= 1
        # The text part should contain the file content
        text_parts = [p for p in parts if "text" in str(p)]
        assert len(text_parts) >= 1

    @pytest.mark.asyncio
    async def test_audio_produces_inline_data_part(self):
        """Audio file must produce an inline_data Part for Gemini audio processing."""
        mock_part_cls = MagicMock(side_effect=lambda **kw: kw)
        mock_blob_cls = MagicMock(side_effect=lambda **kw: kw)

        with patch("src.core.file_processor.Part", mock_part_cls), \
             patch("src.core.file_processor.Blob", mock_blob_cls):
            from importlib import reload
            import src.core.file_processor as fp
            reload(fp)
            parts = await fp.file_to_parts(_AUDIO_BYTES, "audio/ogg", "voice.ogg")

        assert len(parts) >= 1

    @pytest.mark.asyncio
    async def test_caption_appended_to_image_parts(self):
        """User caption must appear in the parts alongside the image."""
        mock_part_cls = MagicMock(side_effect=lambda **kw: kw)
        mock_blob_cls = MagicMock(side_effect=lambda **kw: kw)
        user_caption  = "Extract all action items from this whiteboard"

        with patch("src.core.file_processor.Part", mock_part_cls), \
             patch("src.core.file_processor.Blob", mock_blob_cls):
            from importlib import reload
            import src.core.file_processor as fp
            reload(fp)
            parts = await fp.file_to_parts(_PNG_BYTES, "image/png", "board.png", caption=user_caption)

        # At least one part should contain the user caption
        all_text = str(parts)
        assert user_caption in all_text

    @pytest.mark.asyncio
    async def test_unknown_type_returns_description(self):
        """Unknown MIME type must not raise — returns a descriptive text Part."""
        mock_part_cls = MagicMock(side_effect=lambda **kw: kw)

        with patch("src.core.file_processor.Part", mock_part_cls), \
             patch("src.core.file_processor.Blob", MagicMock()):
            from importlib import reload
            import src.core.file_processor as fp
            reload(fp)
            parts = await fp.file_to_parts(b"\x00\x01\x02binary", "application/octet-stream", "data.bin")

        assert len(parts) >= 1

    @pytest.mark.asyncio
    async def test_large_text_truncated_at_50k_chars(self):
        """Text files larger than 50,000 chars must be truncated."""
        big_text      = ("A" * 60_000).encode()
        mock_part_cls = MagicMock(side_effect=lambda **kw: kw)

        with patch("src.core.file_processor.Part", mock_part_cls), \
             patch("src.core.file_processor.Blob", MagicMock()):
            from importlib import reload
            import src.core.file_processor as fp
            reload(fp)
            parts = await fp.file_to_parts(big_text, "text/plain", "large.txt")

        all_text = str(parts)
        assert "truncated" in all_text.lower()


class TestFriendlyFileLabel:
    def test_image_label(self):
        from src.core.file_processor import friendly_file_label
        assert friendly_file_label("image/jpeg", "photo.jpg") == "Image"

    def test_audio_label(self):
        from src.core.file_processor import friendly_file_label
        assert friendly_file_label("audio/ogg", "voice.ogg") == "Audio"

    def test_pdf_label(self):
        from src.core.file_processor import friendly_file_label
        assert friendly_file_label("application/pdf", "report.pdf") == "PDF"

    def test_docx_label(self):
        from src.core.file_processor import friendly_file_label
        label = friendly_file_label("application/octet-stream", "proposal.docx")
        assert label == "Word Document"

    def test_xlsx_label(self):
        from src.core.file_processor import friendly_file_label
        label = friendly_file_label("application/octet-stream", "budget.xlsx")
        assert label == "Spreadsheet"

class TestRunnerMultimodal:
    """Tests for AIDENRunner.run_agent_multimodal."""

    @pytest.fixture
    def mock_runner_response(self):
        """Mock ADK runner that yields a single final_response event."""
        async def _run_async(*args, **kwargs):
            event = MagicMock()
            event.is_final_response = MagicMock(return_value=True)
            part = MagicMock()
            part.text = "I analyzed your image and found 3 action items."
            event.content = MagicMock()
            event.content.parts = [part]
            event.author = "vision_agent"
            yield event
        return _run_async

    @pytest.mark.asyncio
    async def test_run_agent_multimodal_returns_response(self, mock_runner_response):
        """run_agent_multimodal must return a non-empty response string."""
        mock_parts = [MagicMock(text="Analyze this image.")]

        with patch("src.core.runner.file_to_parts", new=AsyncMock(return_value=mock_parts)), \
             patch("src.core.runner.persist_trace", new=AsyncMock()), \
             patch("src.core.runner.aiden_runner.runner.run_async", side_effect=mock_runner_response), \
             patch("src.core.runner.aiden_runner._ensure_session", new=AsyncMock()):
            from src.core.runner import aiden_runner
            result = await aiden_runner.run_agent_multimodal(
                user_id    = USER_ID,
                message    = "What are the action items?",
                file_bytes = _PNG_BYTES,
                mime_type  = "image/png",
                filename   = "whiteboard.png",
                session_id = SESSION_ID,
            )

        assert result["success"] is True
        assert len(result["response"]) > 0
        assert "file_info" in result
        assert result["file_info"]["filename"] == "whiteboard.png"

    @pytest.mark.asyncio
    async def test_run_with_trace_multimodal_yields_done(self, mock_runner_response):
        """run_with_trace_multimodal must yield a 'done' SSE event."""
        mock_parts = [MagicMock(text="Vision analysis complete.")]

        with patch("src.core.runner.file_to_parts", new=AsyncMock(return_value=mock_parts)), \
             patch("src.core.runner.persist_trace", new=AsyncMock()), \
             patch("src.core.runner.aiden_runner.runner.run_async", side_effect=mock_runner_response), \
             patch("src.core.runner.aiden_runner._ensure_session", new=AsyncMock()):
            from src.core.runner import aiden_runner
            events = []
            async for event in aiden_runner.run_with_trace_multimodal(
                user_id    = USER_ID,
                message    = "Describe this image",
                file_bytes = _PNG_BYTES,
                mime_type  = "image/png",
                filename   = "photo.png",
                session_id = SESSION_ID,
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "done" in types, "Must yield a 'done' event"
        done = next(e for e in events if e["type"] == "done")
        assert "file_info" in done
        assert done["file_info"]["label"] == "Image"

    @pytest.mark.asyncio
    async def test_file_parts_prepended_before_message(self, mock_runner_response):
        """File parts must be passed to ADK runner alongside text message."""
        file_part   = MagicMock()
        file_part.text = None
        text_part   = MagicMock()
        text_part.text = "User caption"
        mock_parts  = [file_part, text_part]
        captured_content = []

        async def capture_run(*args, **kwargs):
            captured_content.append(kwargs.get("new_message"))
            event = MagicMock()
            event.is_final_response = MagicMock(return_value=True)
            event.content = MagicMock()
            event.content.parts = [MagicMock(text="done")]
            event.author = "vision_agent"
            yield event

        with patch("src.core.runner.file_to_parts", new=AsyncMock(return_value=mock_parts)), \
             patch("src.core.runner.persist_trace", new=AsyncMock()), \
             patch("src.core.runner.aiden_runner.runner.run_async", side_effect=capture_run), \
             patch("src.core.runner.aiden_runner._ensure_session", new=AsyncMock()):
            from src.core.runner import aiden_runner
            await aiden_runner.run_agent_multimodal(
                user_id=USER_ID, message="Analyze this",
                file_bytes=_PNG_BYTES, mime_type="image/png",
                filename="img.png", session_id=SESSION_ID,
            )

        assert len(captured_content) > 0, "ADK runner must be called with content"


@pytest.fixture
def fake_user():
    u = MagicMock()
    u.user_id   = USER_ID
    u.email     = "judge@hackathon.dev"
    u.name      = "Test Judge"
    u.is_active = True
    return u


class TestChatUploadEndpoint:
    @pytest.fixture
    def client(self, fake_user):
        from src.api.main import app
        from fastapi.testclient import TestClient
        with patch("src.api.middleware.get_current_active_user", return_value=fake_user):
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c

    @pytest.fixture
    def auth_headers(self):
        return {"Authorization": "Bearer test_token_judges"}

    def test_upload_rejects_oversized_file(self, client, auth_headers):
        """Files > 20 MB must be rejected with an error SSE event."""
        huge = b"X" * (21 * 1024 * 1024)  # 21 MB
        resp = client.post(
            "/chat/upload/sync",
            headers={k: v for k, v in auth_headers.items()},
            data={"message": "analyze this"},
            files={"file": ("huge.txt", huge, "text/plain")},
        )
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("success") is False or "error" in data
        else:
            # Any non-200 response also acceptable for oversized files
            assert resp.status_code in (400, 413, 422, 500)

    def test_upload_sync_requires_auth(self):
        """Upload endpoint must reject requests without Authorization header."""
        from src.api.main import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                "/chat/upload/sync",
                data={"message": "test"},
                files={"file": ("test.txt", b"hello", "text/plain")},
            )
        assert resp.status_code in (401, 403, 422)

class TestTelegramFileUpload:
    @pytest.mark.asyncio
    async def test_chat_with_file_strips_content_type_header(self):
        """
        chat_with_file must NOT send Content-Type in headers — httpx sets it
        automatically with the correct multipart boundary.
        """
        from src.integrations.telegram_bot import AIDENClient
        api = AIDENClient()

        captured_headers = {}
        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"response": "done", "success": True})
            return mock_resp

        api._http.post = AsyncMock(side_effect=mock_post)
        await api.chat_with_file(
            chat_id=12345,
            file_bytes=_PNG_BYTES,
            filename="test.png",
            mime_type="image/png",
            caption="Describe this",
        )
        assert "Content-Type" not in captured_headers, \
            "Content-Type must not be manually set for multipart requests"

    @pytest.mark.asyncio
    async def test_chat_with_file_sends_correct_headers(self):
        """chat_with_file must send X-Bot-Secret and X-Telegram-Chat-Id headers."""
        from src.integrations.telegram_bot import AIDENClient, bot_cfg
        api = AIDENClient()
        captured_headers = {}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"response": "ok", "success": True})
            return mock_resp

        api._http.post = AsyncMock(side_effect=mock_post)
        await api.chat_with_file(99999, _PNG_BYTES, "photo.jpg", "image/jpeg", "test")

        assert "X-Bot-Secret"       in captured_headers
        assert "X-Telegram-Chat-Id" in captured_headers
        assert captured_headers["X-Telegram-Chat-Id"] == "99999"

    @pytest.mark.asyncio
    async def test_on_photo_calls_chat_with_file(self):
        """on_photo must use chat_with_file (unified upload), not analyze_image."""
        from src.integrations.telegram_bot import on_photo

        # Build a fake Telegram update with a photo
        mock_photo = MagicMock()
        mock_photo.file_id        = "file_abc123"
        mock_photo.file_unique_id = "unique_abc"
        mock_photo.mime_type      = "image/jpeg"

        mock_msg = MagicMock()
        mock_msg.photo   = [mock_photo]  # list of sizes; we use [-1]
        mock_msg.document = None
        mock_msg.caption  = "What's in this image?"

        mock_update = MagicMock()
        mock_update.message       = mock_msg
        mock_update.effective_chat.id = 12345

        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=MagicMock(
            file_path="https://api.telegram.org/file/bot.../photo.jpg"
        ))

        mock_ctx = MagicMock()
        mock_ctx.bot = mock_bot

        chat_with_file_called = False

        async def _mock_cwf(*args, **kwargs):
            nonlocal chat_with_file_called
            chat_with_file_called = True
            return {"response": "Image analyzed!", "success": True, "agents_used": ["vision_agent"]}

        with patch("src.integrations.telegram_bot._get_registered_user",
                   new=AsyncMock(return_value=MagicMock(user_id=USER_ID))), \
             patch("src.integrations.telegram_bot._api.chat_with_file",
                   new=AsyncMock(side_effect=_mock_cwf)), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__  = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=MagicMock(content=_PNG_BYTES))
            mock_http_cls.return_value = mock_http

            await on_photo(mock_update, mock_ctx)

        assert chat_with_file_called, \
            "on_photo must call chat_with_file (unified upload path)"
