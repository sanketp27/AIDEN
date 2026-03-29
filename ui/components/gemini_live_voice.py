"""
Real-time voice component using Gemini Live API
WebSocket-based bidirectional audio streaming
"""
import streamlit as st
import streamlit.components.v1 as components


GEMINI_LIVE_VOICE_HTML = """
<div id="gemini-live-voice" style="padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 16px; color: white; margin: 10px 0;">
    <div style="display: flex; align-items: center; gap: 16px; margin-bottom: 16px;">
        <button id="voice-btn" onclick="toggleVoice()"
                style="width: 70px; height: 70px; border-radius: 50%; border: 4px solid white;
                       background: rgba(255,255,255,0.2); cursor: pointer; font-size: 32px;
                       transition: all 0.3s; box-shadow: 0 4px 15px rgba(0,0,0,0.3);
                       backdrop-filter: blur(10px);">
            🎤
        </button>

        <div style="flex: 1;">
            <div style="font-size: 20px; font-weight: bold; margin-bottom: 4px;">
                Gemini Live Voice
            </div>
            <div id="status" style="font-size: 14px; opacity: 0.9;">
                Click to start real-time conversation
            </div>
        </div>
    </div>

    <canvas id="visualizer" width="600" height="80"
            style="width: 100%; border-radius: 8px; background: rgba(0,0,0,0.2);"></canvas>

    <div id="transcript" style="margin-top: 16px; padding: 12px; background: rgba(0,0,0,0.2);
                                border-radius: 8px; min-height: 60px; font-size: 15px; line-height: 1.5;">
        <em>Transcription will appear here...</em>
    </div>
</div>

<script>
let ws = null;
let mediaRecorder = null;
let audioContext = null;
let analyser = null;
let isActive = false;
let animId = null;

// WebSocket URL - replace with your actual backend URL
const WS_URL = 'ws://localhost:8000/ws/voice';
const TOKEN = new URLSearchParams(window.location.search).get('token') || 'YOUR_JWT_TOKEN';

async function toggleVoice() {
    if (!isActive) {
        await startVoice();
    } else {
        stopVoice();
    }
}

async function startVoice() {
    try {
        // Update UI
        document.getElementById('voice-btn').textContent = '⏹';
        document.getElementById('voice-btn').style.background = 'rgba(239, 68, 68, 0.8)';
        document.getElementById('status').innerHTML = '<span style="color: #fbbf24;">⚡ Connecting to Gemini Live...</span>';

        // Connect WebSocket
        ws = new WebSocket(`${WS_URL}?token=${TOKEN}`);

        ws.onopen = () => {
            console.log('WebSocket connected');
            document.getElementById('status').innerHTML = '<span style="color: #10b981;">🟢 Connected! Speak now...</span>';
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleServerMessage(data);
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            document.getElementById('status').innerHTML = '<span style="color: #ef4444;">❌ Connection error</span>';
        };

        ws.onclose = () => {
            console.log('WebSocket closed');
            stopVoice();
        };

        // Start audio capture
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true
            }
        });

        // Setup audio visualization
        audioContext = new AudioContext({ sampleRate: 16000 });
        analyser = audioContext.createAnalyser();
        audioContext.createMediaStreamSource(stream).connect(analyser);
        analyser.fftSize = 256;
        visualize();

        // Setup MediaRecorder for sending audio
        mediaRecorder = new MediaRecorder(stream, {
            mimeType: 'audio/webm;codecs=opus',
            audioBitsPerSecond: 16000
        });

        mediaRecorder.ondataavailable = async (event) => {
            if (event.data.size > 0 && ws && ws.readyState === WebSocket.OPEN) {
                // Convert to arraybuffer and send
                const arrayBuffer = await event.data.arrayBuffer();
                const base64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));

                ws.send(JSON.stringify({
                    type: 'audio',
                    data: base64
                }));
            }
        };

        // Send audio chunks every 100ms
        mediaRecorder.start(100);
        isActive = true;

    } catch (err) {
        console.error('Failed to start voice:', err);
        document.getElementById('status').innerHTML = `<span style="color: #ef4444;">❌ Error: ${err.message}</span>`;
        stopVoice();
    }
}

function stopVoice() {
    isActive = false;

    // Stop media recorder
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
    }

    // Stop visualization
    if (animId) {
        cancelAnimationFrame(animId);
    }

    // Close WebSocket
    if (ws) {
        ws.close();
        ws = null;
    }

    // Update UI
    document.getElementById('voice-btn').textContent = '🎤';
    document.getElementById('voice-btn').style.background = 'rgba(255,255,255,0.2)';
    document.getElementById('status').textContent = 'Click to start real-time conversation';
}

function handleServerMessage(data) {
    const transcriptEl = document.getElementById('transcript');

    switch(data.type) {
        case 'session_started':
            transcriptEl.innerHTML = `<em style="color: #10b981;">${data.message}</em>`;
            break;

        case 'text':
            // Show Gemini's text response
            transcriptEl.innerHTML += `<br><strong style="color: #fbbf24;">Gemini:</strong> ${data.content}`;
            transcriptEl.scrollTop = transcriptEl.scrollHeight;
            break;

        case 'audio':
            // Play audio response
            playAudio(data.data, data.mime_type);
            break;

        case 'turn_complete':
            console.log('Turn complete');
            break;

        case 'error':
            transcriptEl.innerHTML += `<br><span style="color: #ef4444;">❌ Error: ${data.message}</span>`;
            break;
    }
}

function playAudio(base64Data, mimeType) {
    // Convert base64 to audio and play
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }

    const blob = new Blob([bytes], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play().catch(err => console.error('Audio playback failed:', err));
}

function visualize() {
    const canvas = document.getElementById('visualizer');
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
        animId = requestAnimationFrame(draw);

        analyser.getByteFrequencyData(dataArray);

        // Clear canvas
        ctx.fillStyle = 'rgba(0, 0, 0, 0.2)';
        ctx.fillRect(0, 0, width, height);

        // Draw bars
        const barWidth = (width / bufferLength) * 2.5;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
            const barHeight = (dataArray[i] / 255) * height * 0.8;

            // Gradient effect
            const gradient = ctx.createLinearGradient(0, height - barHeight, 0, height);
            gradient.addColorStop(0, '#fbbf24');
            gradient.addColorStop(1, '#f59e0b');

            ctx.fillStyle = gradient;
            ctx.fillRect(x, height - barHeight, barWidth - 2, barHeight);

            x += barWidth;
        }
    }

    draw();
}
</script>
"""


def render_gemini_live_voice(api_url: str, token: str) -> None:
    """
    Render Gemini Live real-time voice interface

    Args:
        api_url: API base URL
        token: JWT token for WebSocket authentication
    """
    st.markdown("### 🎙️ Gemini Live - Real-Time Voice")
    st.success("✅ **LIVE MODE** - Powered by Gemini 2.1 Flash (Experimental)")

    st.info("""
    **How it works:**
    1. Click the microphone to start
    2. Speak naturally - Gemini listens in real-time
    3. Gemini responds with both text and audio
    4. Click again to stop

    ⚡ **Low latency** bidirectional audio streaming!
    """)

    # Inject WebSocket URL and token into HTML
    html = GEMINI_LIVE_VOICE_HTML.replace('YOUR_JWT_TOKEN', token)
    html = html.replace('ws://localhost:8000', api_url.replace('http', 'ws'))

    components.html(html, height=350)

    st.markdown("---")
    st.markdown("**Note:** This uses the experimental `gemini-2.1-flash-exp` model with live audio streaming.")
