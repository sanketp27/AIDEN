"""
AIDEN v2.0 Streamlit UI - Phase P2 Complete
Multi-modal interface: Chat, Voice (Mock), and Vision (Gemini)
"""
import streamlit as st
import requests
import os
from datetime import datetime
from ui.components.voice_input import render_voice_input
from ui.components.audio_player import render_speaker_button
from ui.components.image_upload import render_image_upload, show_image_examples
from ui.components.gemini_live_voice import render_gemini_live_voice

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Page config
st.set_page_config(
    page_title="AIDEN v2.0 - Voice & Vision",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main > div {
        padding-top: 2rem;
    }
    .stChatMessage {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 10px;
        margin: 5px 0;
    }
    .agent-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: bold;
        margin-left: 5px;
    }
    .agent-task { background-color: #FFE5E5; color: #D32F2F; }
    .agent-calendar { background-color: #E3F2FD; color: #1976D2; }
    .agent-notes { background-color: #E8F5E9; color: #388E3C; }
    .agent-vision { background-color: #F3E5F5; color: #7B1FA2; }
    .agent-voice { background-color: #FFF3E0; color: #E65100; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "api_token" not in st.session_state:
    st.session_state.api_token = None
if "current_tab" not in st.session_state:
    st.session_state.current_tab = "Chat"

# Sidebar
with st.sidebar:
    st.title("🤖 AIDEN v2.0")
    st.markdown("**AI Intelligent Daily Executive Navigator**")
    st.caption("Phase P2: Voice & Vision Complete ✨")
    st.divider()

    # Authentication
    st.subheader("Authentication")
    if not st.session_state.api_token:
        st.warning("⚠️ JWT token required")
        token_input = st.text_input(
            "JWT Token",
            type="password",
            help="Enter your JWT authentication token"
        )
        if st.button("Connect"):
            if token_input:
                st.session_state.api_token = token_input
                st.success("✅ Connected!")
                st.rerun()
            else:
                st.error("Please enter a token")
    else:
        st.success("✅ Authenticated")
        if st.button("Disconnect"):
            st.session_state.api_token = None
            st.session_state.messages = []
            st.session_state.session_id = None
            st.rerun()

    st.divider()

    # Session info
    st.subheader("Session Info")
    if st.session_state.session_id:
        st.text(f"ID: {st.session_state.session_id[:8]}...")
    else:
        st.text("No active session")

    if st.button("Clear Session"):
        st.session_state.messages = []
        st.session_state.session_id = None
        st.rerun()

    st.divider()

    # Mode selector
    st.subheader("Interface Mode")
    mode = st.radio(
        "Choose mode:",
        ["💬 Chat", "🎤 Voice", "📸 Vision"],
        index=["💬 Chat", "🎤 Voice", "📸 Vision"].index(
            f"💬 {st.session_state.current_tab}" if st.session_state.current_tab == "Chat"
            else f"🎤 {st.session_state.current_tab}" if st.session_state.current_tab == "Voice"
            else "📸 Vision"
        ) if st.session_state.current_tab in ["Chat", "Voice", "Vision"] else 0
    )
    st.session_state.current_tab = mode.split(" ", 1)[1]

    st.divider()

    # Capabilities
    st.subheader("Capabilities")
    st.markdown("""
    **🗂️ TaskMaster**
    - Create & manage tasks
    - Set priorities & due dates

    **📅 CalendarBot**
    - View schedule
    - Create meetings

    **📝 NoteKeeper**
    - Create & organize notes
    - Semantic search

    **🎤 Voice Agent** ✨ Live
    - Gemini 2.5 Flash TTS
    - Real-time transcription

    **📸 Vision Agent** ✨ Live
    - Image classification
    - Extract tasks/notes
    - 8 image types supported
    """)

    st.divider()

    # Quick actions
    st.subheader("Quick Actions")
    if st.button("📋 View Tasks", use_container_width=True):
        st.session_state.example_query = "What tasks do I have?"
        st.session_state.current_tab = "Chat"
        st.rerun()

    if st.button("📅 Today's Schedule", use_container_width=True):
        st.session_state.example_query = "What's on my calendar today?"
        st.session_state.current_tab = "Chat"
        st.rerun()

    if st.button("🔍 Search Notes", use_container_width=True):
        st.session_state.example_query = "Search my notes for Q2"
        st.session_state.current_tab = "Chat"
        st.rerun()

# Main area
st.title(f"{mode}")

# Check authentication
if not st.session_state.api_token:
    st.info("👈 Please authenticate with your JWT token in the sidebar to start.")
    st.markdown("---")
    st.markdown("### 🚀 Get Started")
    st.code("python generate_token.py --user-id your_name --role user", language="bash")
    st.stop()

# === CHAT MODE ===
if st.session_state.current_tab == "Chat":
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            # Show agent badges
            if message["role"] == "assistant" and "agents_used" in message:
                agents_html = ""
                for agent in message["agents_used"]:
                    agent_class = "agent-task" if "task" in agent.lower() else \
                                 "agent-calendar" if "calendar" in agent.lower() else \
                                 "agent-notes" if "note" in agent.lower() else \
                                 "agent-vision" if "vision" in agent.lower() else \
                                 "agent-voice" if "voice" in agent.lower() else "agent-badge"
                    agents_html += f'<span class="agent-badge {agent_class}">{agent}</span>'

                if agents_html:
                    st.markdown(f"Agents: {agents_html}", unsafe_allow_html=True)

            # Add TTS button for assistant messages
            if message["role"] == "assistant" and len(message["content"]) < 1000:
                render_speaker_button(
                    message["content"],
                    API_BASE_URL,
                    st.session_state.api_token,
                    key=f"tts_{hash(message['content'])}"
                )

    # Handle example query
    if "example_query" in st.session_state:
        prompt = st.session_state.example_query
        del st.session_state.example_query
    else:
        prompt = st.chat_input("Ask AIDEN anything...")

    if prompt:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        # Call AIDEN API
        with st.chat_message("assistant"):
            with st.spinner("AIDEN is thinking..."):
                try:
                    response = requests.post(
                        f"{API_BASE_URL}/chat",
                        json={
                            "message": prompt,
                            "session_id": st.session_state.session_id
                        },
                        headers={
                            "Authorization": f"Bearer {st.session_state.api_token}",
                            "Content-Type": "application/json"
                        },
                        timeout=30
                    )

                    if response.status_code == 200:
                        result = response.json()
                        st.session_state.session_id = result.get("session_id")

                        st.markdown(result["response"])

                        agents_used = result.get("agents_used", [])
                        if agents_used:
                            agents_html = ""
                            for agent in agents_used:
                                agent_class = "agent-task" if "task" in agent.lower() else \
                                             "agent-calendar" if "calendar" in agent.lower() else \
                                             "agent-notes" if "note" in agent.lower() else "agent-badge"
                                agents_html += f'<span class="agent-badge {agent_class}">{agent}</span>'
                            st.markdown(f"Agents: {agents_html}", unsafe_allow_html=True)

                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": result["response"],
                            "agents_used": agents_used
                        })

                    elif response.status_code == 401:
                        st.error("❌ Authentication failed. Please check your JWT token.")
                        st.session_state.api_token = None
                    else:
                        st.error(f"❌ Error {response.status_code}: {response.text}")

                except requests.exceptions.ConnectionError:
                    st.error(f"❌ Cannot connect to API at {API_BASE_URL}")
                except requests.exceptions.Timeout:
                    st.error("❌ Request timed out")
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

        st.rerun()

# === VOICE MODE ===
elif st.session_state.current_tab == "Voice":
    st.markdown("### 🎙️ Voice Interaction with Gemini")
    st.success("✅ **LIVE MODE** - Powered by Gemini 2.5 Flash with TTS for audio transcription")

    st.markdown("### How Voice Works")
    st.info("""
    1. Click the microphone to start recording
    2. Speak your message
    3. Click again to stop
    4. **Gemini transcribes your audio** using advanced audio understanding
    5. **AIDEN processes your request** and executes actions
    6. View transcript, intent, and AI response
    """)

    # Render voice recorder
    audio_b64 = render_voice_input()

    if audio_b64:
        st.success("✅ Audio recorded! Processing with Gemini...")

        with st.spinner("Transcribing and analyzing your audio..."):
            try:
                # Call the voice query endpoint
                response = requests.post(
                    f"{API_BASE_URL}/voice/query",
                    json={
                        "audio_b64": audio_b64,
                        "language": "en-US",
                        "auto_execute": True
                    },
                    headers={
                        "Authorization": f"Bearer {st.session_state.api_token}",
                        "Content-Type": "application/json"
                    },
                    timeout=60
                )

                if response.status_code == 200:
                    result = response.json()

                    # Show results
                    st.markdown("---")
                    st.markdown("### 📝 Transcript")
                    st.info(result.get("transcript", "(No transcript)"))

                    st.markdown("### 🎯 Detected Intent")
                    intent = result.get("intent", "general_query")
                    intent_emoji = {
                        "task_creation": "✅",
                        "note_creation": "📝",
                        "calendar_event": "📅",
                        "search": "🔍",
                        "general_query": "💬"
                    }.get(intent, "💬")
                    st.success(f"{intent_emoji} {intent.replace('_', ' ').title()}")

                    if result.get("aiden_response"):
                        st.markdown("### 🤖 AIDEN's Response")
                        st.markdown(result["aiden_response"])

                        # Show agent badges
                        if result.get("actions_taken"):
                            agents_html = ""
                            for agent in result["actions_taken"]:
                                agent_class = "agent-task" if "task" in agent.lower() else \
                                             "agent-calendar" if "calendar" in agent.lower() else \
                                             "agent-notes" if "note" in agent.lower() else "agent-voice"
                                agents_html += f'<span class="agent-badge {agent_class}">{agent}</span>'
                            st.markdown(f"Agents Used: {agents_html}", unsafe_allow_html=True)

                    # Add to chat history button
                    if st.button("💬 Continue in Chat"):
                        st.session_state.current_tab = "Chat"
                        if result.get("transcript"):
                            st.session_state.messages.append({
                                "role": "user",
                                "content": f"🎤 {result['transcript']}"
                            })
                        if result.get("aiden_response"):
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": result['aiden_response'],
                                "agents_used": result.get("actions_taken", [])
                            })
                        st.rerun()

                elif response.status_code == 401:
                    st.error("❌ Authentication failed. Please check your JWT token.")
                    st.session_state.api_token = None
                else:
                    st.error(f"❌ Error {response.status_code}: {response.text}")

            except requests.exceptions.ConnectionError:
                st.error(f"❌ Cannot connect to API at {API_BASE_URL}")
            except requests.exceptions.Timeout:
                st.error("❌ Request timed out (audio processing can take longer)")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

    st.divider()

    st.markdown("### ✨ What You Can Say")
    st.markdown("""
    **Task Management:**
    - "Create a task to review quarterly report by Friday"
    - "Show me my high priority tasks"
    - "Mark task XYZ as complete"

    **Note Taking:**
    - "Take a note about the meeting with John"
    - "Search my notes for project alpha"

    **Calendar:**
    - "What's on my calendar today?"
    - "Schedule a meeting tomorrow at 2 PM"

    **General:**
    - "What do I need to focus on today?"
    - "Give me a summary of my week"
    """)

# === VISION MODE ===
elif st.session_state.current_tab == "Vision":
    st.markdown("### 🎯 Powered by Gemini Vision 2.0")
    st.success("✅ **Vision is FULLY FUNCTIONAL** - Upload images to extract structured data!")

    # Image upload component
    render_image_upload(API_BASE_URL, st.session_state.api_token)

    st.divider()

    # Show examples
    show_image_examples()

# Footer
st.divider()
st.caption(f"AIDEN v2.0 - Phase P2 Complete | API: {API_BASE_URL} | Made with ❤️ using Google Gemini & ADK")
