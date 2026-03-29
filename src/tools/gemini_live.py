"""
Gemini Live API integration for real-time voice
Bidirectional audio streaming with gemini-2.1-flash-exp
"""
from google import genai
from src.core.config import settings
import asyncio
import base64
import structlog

log = structlog.get_logger()

# Initialize Gemini client
client = genai.Client(api_key=settings.GEMINI_API_KEY)


class GeminiLiveSession:
    """
    Manages a Gemini Live API session for real-time voice
    """

    def __init__(self, model: str = "gemini-2.1-flash-exp"):
        self.model = model
        self.session = None
        self.config = {
            "response_modalities": ["AUDIO", "TEXT"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": "Aoede"  # Professional voice
                    }
                }
            }
        }

    async def start_session(self):
        """Start a new Gemini Live session"""
        try:
            self.session = await client.aio.live.connect(
                model=self.model,
                config=self.config
            ).__aenter__()

            log.info("gemini_live_session_started", model=self.model)
            return True

        except Exception as e:
            log.error("gemini_live_session_failed", error=str(e))
            return False

    async def send_audio(self, audio_data: bytes):
        """
        Send audio data to Gemini Live

        Args:
            audio_data: Raw audio bytes (PCM16, 16kHz)
        """
        if not self.session:
            raise RuntimeError("Session not started")

        try:
            await self.session.send(
                {
                    "realtime_input": {
                        "media_chunks": [
                            {
                                "mime_type": "audio/pcm",
                                "data": base64.b64encode(audio_data).decode()
                            }
                        ]
                    }
                }
            )
            log.debug("audio_sent_to_gemini", size=len(audio_data))

        except Exception as e:
            log.error("audio_send_failed", error=str(e))
            raise

    async def send_text(self, text: str):
        """
        Send text message to Gemini Live

        Args:
            text: Text message
        """
        if not self.session:
            raise RuntimeError("Session not started")

        try:
            await self.session.send(text)
            log.info("text_sent_to_gemini", text=text[:100])

        except Exception as e:
            log.error("text_send_failed", error=str(e))
            raise

    async def receive(self):
        """
        Receive responses from Gemini Live

        Yields:
            Dictionary with response data (text or audio)
        """
        if not self.session:
            raise RuntimeError("Session not started")

        try:
            async for response in self.session.receive():
                # Parse response
                if hasattr(response, 'server_content'):
                    content = response.server_content

                    # Text response
                    if hasattr(content, 'model_turn'):
                        for part in content.model_turn.parts:
                            if hasattr(part, 'text') and part.text:
                                yield {
                                    "type": "text",
                                    "content": part.text
                                }
                                log.debug("text_received", length=len(part.text))

                            if hasattr(part, 'inline_data') and part.inline_data:
                                # Audio response
                                audio_data = base64.b64decode(part.inline_data.data)
                                yield {
                                    "type": "audio",
                                    "content": audio_data,
                                    "mime_type": part.inline_data.mime_type
                                }
                                log.debug("audio_received", size=len(audio_data))

                    # Turn complete
                    if hasattr(content, 'turn_complete') and content.turn_complete:
                        yield {
                            "type": "turn_complete"
                        }
                        log.debug("turn_complete")

        except Exception as e:
            log.error("receive_failed", error=str(e))
            yield {
                "type": "error",
                "content": str(e)
            }

    async def close(self):
        """Close the session"""
        if self.session:
            try:
                await self.session.__aexit__(None, None, None)
                log.info("gemini_live_session_closed")
            except Exception as e:
                log.error("session_close_failed", error=str(e))


# Session manager for multiple concurrent sessions
class GeminiLiveSessionManager:
    """Manages multiple Gemini Live sessions"""

    def __init__(self):
        self.sessions = {}  # session_id -> GeminiLiveSession

    async def create_session(self, session_id: str) -> GeminiLiveSession:
        """
        Create a new Gemini Live session

        Args:
            session_id: Unique session identifier

        Returns:
            GeminiLiveSession instance
        """
        if session_id in self.sessions:
            await self.close_session(session_id)

        session = GeminiLiveSession()
        started = await session.start_session()

        if started:
            self.sessions[session_id] = session
            log.info("session_manager_created", session_id=session_id, total=len(self.sessions))
            return session
        else:
            raise RuntimeError("Failed to start Gemini Live session")

    def get_session(self, session_id: str) -> GeminiLiveSession:
        """Get existing session"""
        return self.sessions.get(session_id)

    async def close_session(self, session_id: str):
        """Close and remove session"""
        if session_id in self.sessions:
            await self.sessions[session_id].close()
            del self.sessions[session_id]
            log.info("session_manager_closed", session_id=session_id, remaining=len(self.sessions))

    async def close_all(self):
        """Close all sessions"""
        for session_id in list(self.sessions.keys()):
            await self.close_session(session_id)


# Singleton session manager
live_session_manager = GeminiLiveSessionManager()
