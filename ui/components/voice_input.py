"""
Voice input component for Streamlit
Browser-based audio recording with MediaRecorder API
"""
import streamlit as st
import streamlit.components.v1 as components


VOICE_RECORDER_HTML = """
<div id="voice-recorder" style="display: flex; align-items: center; gap: 12px; padding: 16px; background: #f8f9fa; border-radius: 12px; margin: 10px 0;">
    <button id="mic-btn" onclick="toggleRecording()"
            style="width: 56px; height: 56px; border-radius: 50%; border: 3px solid #1A56DB;
                   background: #EFF6FF; cursor: pointer; font-size: 24px; transition: all 0.3s;
                   box-shadow: 0 2px 8px rgba(26, 86, 219, 0.2);">
        🎤
    </button>

    <div style="flex: 1;">
        <canvas id="waveform" width="400" height="60"
                style="border-radius: 8px; background: #E5E7EB; width: 100%;"></canvas>
        <div id="status" style="margin-top: 8px; color: #6B7280; font-size: 14px; font-weight: 500;">
            Click microphone to start recording
        </div>
    </div>
</div>

<script>
let recorder, audioChunks = [], isRecording = false, animId, audioContext, analyser;

async function toggleRecording() {
    if (!isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({audio: true});

            // Setup MediaRecorder
            recorder = new MediaRecorder(stream, {mimeType: 'audio/webm;codecs=opus'});
            audioChunks = [];

            recorder.ondataavailable = e => audioChunks.push(e.data);
            recorder.onstop = async () => {
                const blob = new Blob(audioChunks, {type: 'audio/webm'});
                const reader = new FileReader();
                reader.onload = () => {
                    const b64 = reader.result.split(',')[1];
                    // Send to Streamlit
                    window.parent.postMessage({
                        type: 'streamlit:setComponentValue',
                        value: b64
                    }, '*');
                };
                reader.readAsDataURL(blob);
                document.getElementById('status').textContent = '⏳ Processing audio...';

                // Stop all tracks
                stream.getTracks().forEach(track => track.stop());
            };

            recorder.start();
            isRecording = true;
            document.getElementById('mic-btn').style.background = '#FEE2E2';
            document.getElementById('mic-btn').style.borderColor = '#DC2626';
            document.getElementById('mic-btn').textContent = '⏹';
            document.getElementById('status').innerHTML = '<span style="color: #DC2626; font-weight: bold;">🔴 Recording... Click to stop</span>';

            // Start waveform animation
            drawWaveform(stream);
        } catch(err) {
            document.getElementById('status').textContent = '❌ Microphone access denied: ' + err.message;
        }
    } else {
        recorder.stop();
        isRecording = false;
        cancelAnimationFrame(animId);
        document.getElementById('mic-btn').style.background = '#EFF6FF';
        document.getElementById('mic-btn').style.borderColor = '#1A56DB';
        document.getElementById('mic-btn').textContent = '🎤';
    }
}

function drawWaveform(stream) {
    audioContext = new AudioContext();
    analyser = audioContext.createAnalyser();
    audioContext.createMediaStreamSource(stream).connect(analyser);

    const canvas = document.getElementById('waveform');
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    analyser.fftSize = 256;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
        animId = requestAnimationFrame(draw);
        analyser.getByteFrequencyData(dataArray);

        // Clear canvas
        ctx.fillStyle = '#E5E7EB';
        ctx.fillRect(0, 0, width, height);

        // Draw bars
        const barWidth = (width / bufferLength) * 2;
        let barHeight;
        let x = 0;

        for(let i = 0; i < bufferLength; i++) {
            barHeight = (dataArray[i] / 255) * height * 0.8;

            // Gradient color based on frequency
            const hue = 210 + (i / bufferLength) * 30;
            const lightness = 40 + (dataArray[i] / 255) * 30;
            ctx.fillStyle = `hsl(${hue}, 80%, ${lightness}%)`;

            ctx.fillRect(x, height - barHeight, barWidth - 1, barHeight);
            x += barWidth;
        }
    }
    draw();
}
</script>
"""


def render_voice_input(key="voice_input") -> str | None:
    """
    Render voice recording component

    Returns:
        Base64-encoded audio if recorded, None otherwise
    """
    st.markdown("### 🎤 Voice Input with Gemini")
    st.success("✅ **LIVE MODE**: Powered by Gemini 2.5 Flash with TTS for audio transcription")

    # Render the voice recorder
    audio_b64 = components.html(VOICE_RECORDER_HTML, height=140, key=key)

    return audio_b64
