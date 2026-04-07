"""
WebSocket endpoint for real-time voice with Gemini Live
Bidirectional audio streaming
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from src.api.middleware import get_current_user, UserClaims
from src.tools.gemini_live import live_session_manager
from src.models.user import UserRole
from jose import jwt
from src.core.config import settings
import structlog
import json
import base64

log = structlog.get_logger()

router = APIRouter(prefix="/ws", tags=["WebSocket"])


async def get_user_from_ws_token(token: str) -> UserClaims:
    """Extract user from WebSocket token parameter"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return UserClaims(
            user_id=payload['sub'],
            role=UserRole(payload.get('role', 'user')),  # Fix Bug #5: cast to enum
            email=payload.get('email')
        )
    except Exception:
        return None


@router.websocket("/voice")
async def websocket_voice_endpoint(websocket: WebSocket, token: str):
    """
    WebSocket endpoint for real-time voice with Gemini Live

    Protocol:
    Client -> Server:
        {"type": "audio", "data": "<base64_pcm16>"}
        {"type": "text", "data": "<message>"}
        {"type": "end_turn"}

    Server -> Client:
        {"type": "text", "content": "<response>"}
        {"type": "audio", "data": "<base64_audio>", "mime_type": "audio/pcm"}
        {"type": "turn_complete"}
        {"type": "error", "message": "<error>"}
    """
    await websocket.accept()

    # Authenticate user
    user = await get_user_from_ws_token(token)
    if not user:
        await websocket.send_json({
            "type": "error",
            "message": "Invalid authentication token"
        })
        await websocket.close()
        return

    session_id = f"voice_{user.user_id}"
    gemini_session = None

    log.info("voice_websocket_connected", user_id=user.user_id, session_id=session_id)

    try:
        # Create Gemini Live session
        gemini_session = await live_session_manager.create_session(session_id)

        await websocket.send_json({
            "type": "session_started",
            "message": "✅ Gemini Live session started! Speak now."
        })

        # Start receiving from Gemini in background
        async def receive_from_gemini():
            try:
                async for response in gemini_session.receive():
                    if response["type"] == "text":
                        await websocket.send_json({
                            "type": "text",
                            "content": response["content"]
                        })

                    elif response["type"] == "audio":
                        # Send audio chunks to client
                        audio_b64 = base64.b64encode(response["content"]).decode()
                        await websocket.send_json({
                            "type": "audio",
                            "data": audio_b64,
                            "mime_type": response.get("mime_type", "audio/pcm")
                        })

                    elif response["type"] == "turn_complete":
                        await websocket.send_json({
                            "type": "turn_complete"
                        })

                    elif response["type"] == "error":
                        await websocket.send_json({
                            "type": "error",
                            "message": response["content"]
                        })

            except Exception as e:
                log.error("gemini_receive_error", error=str(e))
                await websocket.send_json({
                    "type": "error",
                    "message": f"Gemini error: {str(e)}"
                })

        # Start background task
        import asyncio
        receive_task = asyncio.create_task(receive_from_gemini())

        # Handle client messages
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message["type"] == "audio":
                    # Decode and send audio to Gemini
                    audio_data = base64.b64decode(message["data"])
                    await gemini_session.send_audio(audio_data)

                elif message["type"] == "text":
                    # Send text to Gemini
                    await gemini_session.send_text(message["data"])

                elif message["type"] == "end_turn":
                    # Signal end of user turn
                    log.info("user_turn_ended", user_id=user.user_id)

            except WebSocketDisconnect:
                log.info("voice_websocket_disconnected", user_id=user.user_id)
                break

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON message"
                })

            except Exception as e:
                log.error("websocket_message_error", error=str(e))
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })

        # Cancel background task and wait for it to finish cleanly
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        log.error("voice_websocket_error", user_id=user.user_id, error=str(e))
        await websocket.send_json({
            "type": "error",
            "message": f"Session error: {str(e)}"
        })

    finally:
        # Clean up session
        if gemini_session:
            await live_session_manager.close_session(session_id)

        try:
            await websocket.close()
        except:
            pass

        log.info("voice_websocket_closed", user_id=user.user_id)
