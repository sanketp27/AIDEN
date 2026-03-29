"""
Audio player component for Streamlit
Plays TTS audio responses
"""
import streamlit as st
import streamlit.components.v1 as components


def play_audio(audio_b64: str, autoplay: bool = False) -> None:
    """
    Display audio player with optional autoplay

    Args:
        audio_b64: Base64-encoded audio (MP3)
        autoplay: Whether to auto-play the audio
    """
    autoplay_attr = "autoplay" if autoplay else ""

    audio_html = f"""
    <div style="margin: 10px 0; padding: 12px; background: #f8f9fa; border-radius: 8px;">
        <div style="margin-bottom: 8px; color: #6B7280; font-size: 14px; font-weight: 500;">
            🔊 Audio Response
        </div>
        <audio controls {autoplay_attr} style="width: 100%; border-radius: 6px;">
            <source src="data:audio/mp3;base64,{audio_b64}" type="audio/mp3">
            Your browser does not support the audio element.
        </audio>
    </div>
    """

    components.html(audio_html, height=100)


def render_speaker_button(text: str, api_url: str, token: str, key: str = "tts") -> None:
    """
    Render a speaker button that converts text to speech

    Args:
        text: Text to convert to speech
        api_url: API base URL
        token: JWT token
        key: Unique key for the button
    """
    import requests

    col1, col2 = st.columns([10, 1])

    with col2:
        if st.button("🔊", key=key, help="Read aloud (Mock Mode)"):
            with st.spinner("Generating speech..."):
                try:
                    response = requests.post(
                        f"{api_url}/voice/synthesize",
                        params={"text": text[:500]},  # Limit text length
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=10
                    )

                    if response.status_code == 200:
                        result = response.json()

                        if result.get("mode") == "MOCK":
                            st.warning("⚠️ Mock audio - Real TTS requires Google Cloud credentials")

                        play_audio(result["audio_b64"], autoplay=True)
                    else:
                        st.error(f"TTS failed: {response.text}")

                except Exception as e:
                    st.error(f"Error: {str(e)}")
