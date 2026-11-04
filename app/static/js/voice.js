// Voice - Meta Muse STT - Record button that fills message + TTS Play buttons for agent messages
// Based on /voice/web.py and /tts_cartesia
// Uses AudioContext 24kHz mono PCM for STT, Cartesia for TTS

document.addEventListener('DOMContentLoaded', () => {
  const micBtn = document.getElementById('voice-mic-btn');
  const textarea = document.getElementById('chat-content-input');
  const statusEl = document.getElementById('voice-status');
  const recordingIndicator = document.getElementById('voice-recording-indicator');

  // TTS Play Buttons for agent messages - listen to them
  const playButtons = document.querySelectorAll('.tts-play-btn');
  const audioPlayer = document.getElementById('global-audio-player') || (() => {
    const audio = document.createElement('audio');
    audio.id = 'global-audio-player';
    audio.style.display = 'none';
    document.body.appendChild(audio);
    return audio;
  })();

  playButtons.forEach(btn => {
    btn.addEventListener('click', async () => {
      const messageId = btn.dataset.messageId;
      const transcript = btn.dataset.transcript;
      const voiceId = btn.dataset.voiceId;
      const voiceName = btn.dataset.voiceName || 'agent';

      if (!transcript) {
        console.warn('[TTS] No transcript for message', messageId);
        return;
      }

      const originalHTML = btn.innerHTML;
      btn.innerHTML = '<span class="reasoning-icon">🧠</span> Loading';
      btn.disabled = true;

      // Log request as code
      const ttsRequestLog = `# REQUEST LOG - Play Button TTS (Cartesia)
# Agent message ID: ${messageId}
# Voice: ${voiceName} (${voiceId || 'default Skylar'})
# Transcript: "${transcript.substring(0,80)}..."

from app.services.cartesia_tts import tts_bytes_request

transcript = """${transcript.substring(0,200)}"""
voice_id = "${voiceId || 'db6b0ed5-d5d3-463d-ae85-518a07d3c2b4'}"  # ${voiceName || 'Skylar'}

wav_bytes = tts_bytes_request(transcript, voice_id)
# Save to uploads/voice/... and play via <audio>

print(f"TTS generated {len(wav_bytes)} bytes for {voiceName}")
`;
      console.log(ttsRequestLog);

      try {
        const resp = await fetch('/api/voice/cartesia/tts', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            transcript: transcript,
            voice_id: voiceId || 'db6b0ed5-d5d3-463d-ae85-518a07d3c2b4',
            model_id: 'sonic-3.6'
          })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'TTS failed');

        if (statusEl) statusEl.textContent = `🔊 Playing ${voiceName} - ${transcript.substring(0,40)}... (${data.source})`;

        // If real audio URL returned, play it. For mock, use Web Speech API fallback
        if (data.audio_url) {
          audioPlayer.src = data.audio_url;
          audioPlayer.play();
        } else if (data.wav_base64) {
          // Play base64 wav
          const audio = new Audio('data:audio/wav;base64,' + data.wav_base64);
          audio.play();
        } else {
          // Fallback: browser TTS via speechSynthesis (no CARTESIA_API_KEY)
          if ('speechSynthesis' in window) {
            const utter = new SpeechSynthesisUtterance(transcript);
            utter.rate = 1;
            speechSynthesis.speak(utter);
            if (statusEl) statusEl.textContent = `🔊 Speaking via browser TTS (set CARTESIA_API_KEY for Cartesia): ${voiceName}`;
          } else {
            if (statusEl) statusEl.textContent = `🔊 TTS mock: ${data.voice_id} - set CARTESIA_API_KEY for real audio - transcript: ${transcript.substring(0,50)}`;
          }
        }

        btn.innerHTML = '<i class="bi bi-stop-fill"></i> Playing...';
        setTimeout(() => {
          btn.innerHTML = originalHTML;
          btn.disabled = false;
        }, 3000);

      } catch (e) {
        console.error('[TTS] Play failed', e);
        if (statusEl) statusEl.textContent = `❌ TTS failed: ${e.message}`;
        btn.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Error';
        btn.disabled = false;
        setTimeout(() => {
          btn.innerHTML = originalHTML;
        }, 2000);
      }
    });
  });

  if (!micBtn || !textarea) {
    console.log('[Voice] Mic button or textarea not found, skipping voice init for STT, but TTS play buttons initialized');
    // Don't return, we already initialized TTS buttons above
    if (!micBtn) return;
  }

  let stream = null;
  let context = null;
  let processor = null;
  let source = null;
  let chunks = [];
  let isRecording = false;

  // Check if browser supports getUserMedia
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    micBtn.disabled = true;
    micBtn.title = 'Voice recording not supported in this browser';
    if (statusEl) statusEl.textContent = '🎤 Voice not supported';
    return;
  }

  function logAsCode(transcript, source, duration, pcmBytes) {
    const code = `# REQUEST LOG - Voice Record Button (Meta Muse)
# User clicked mic button, recorded ${duration.toFixed(2)}s, ${pcmBytes} bytes PCM 24kHz

import os
from app.services.meta_stt import transcribe_with_fallback

MODEL_API_KEY = os.environ.get('MODEL_API_KEY')  # LLM_... from .env
pcm_bytes = b'... ${pcmBytes} bytes PCM 24kHz mono 16-bit LE ...'

# Frontend AudioContext 24kHz capture:
# const context = new AudioContext({sampleRate: 24000})
# processor.onaudioprocess = (e) => chunks.push(Float32Array from getChannelData(0))
# Convert Float32 -> Int16 LE PCM

result = transcribe_with_fallback(pcm_bytes)
transcript = result['transcript']  # "${transcript.substring(0, 80)}"

# Fill message textarea:
# document.getElementById('chat-content-input').value = transcript
# Then user can edit and submit -> broadcast to all bots

print(f"Transcript: {transcript}")
print(f"Source: {source}")
`;
    console.log(code);
    if (statusEl) {
      statusEl.textContent = `📝 Transcript filled from voice (${source})`;
      statusEl.title = code;
    }
  }

  async function startRecording() {
    try {
      micBtn.disabled = true;
      if (statusEl) statusEl.textContent = '🎤 Waiting for mic permission...';
      
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      context = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
      source = context.createMediaStreamSource(stream);
      processor = context.createScriptProcessor(4096, 1, 1);
      chunks = [];

      processor.onaudioprocess = (event) => {
        chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };

      source.connect(processor);
      processor.connect(context.destination);

      isRecording = true;
      micBtn.classList.add('recording', 'btn-danger');
      micBtn.classList.remove('btn-ghost');
      micBtn.innerHTML = '<i class="bi bi-stop-fill"></i> Stop';
      micBtn.disabled = false;

      if (recordingIndicator) {
        recordingIndicator.classList.remove('d-none');
        recordingIndicator.innerHTML = '<span class="recording-dot"></span> Listening... <span class="thinking-dots"><span></span><span></span><span></span></span> Speak now, e.g. "Hey Joana can you imagine a web page"';
      }
      if (statusEl) statusEl.textContent = '🔴 Recording... Speak now (e.g. @JOANA_BOT)';

      console.log('[Voice] Started recording 24kHz');

    } catch (error) {
      console.error('[Voice] Could not start recording:', error);
      if (statusEl) statusEl.textContent = `❌ Mic error: ${error.message}`;
      isRecording = false;
      micBtn.disabled = false;
      micBtn.classList.remove('recording', 'btn-danger');
      micBtn.classList.add('btn-ghost');
      micBtn.innerHTML = '<i class="bi bi-mic"></i> Record';
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    }
  }

  async function stopRecording() {
    if (!isRecording) return;

    micBtn.disabled = true;
    if (statusEl) statusEl.textContent = '💾 Processing recording...';
    if (recordingIndicator) recordingIndicator.innerHTML = '<span class="reasoning-icon">🧠</span> Transcribing via Meta Muse... <span class="thinking-dots"><span></span><span></span><span></span></span>';

    try {
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach(track => track.stop());
      await context.close();

      const sampleCount = chunks.reduce((total, chunk) => total + chunk.length, 0);
      const pcm = new ArrayBuffer(sampleCount * 2);
      const view = new DataView(pcm);
      let offset = 0;
      for (const chunk of chunks) {
        for (const sample of chunk) {
          const value = Math.max(-1, Math.min(1, sample));
          view.setInt16(offset, value < 0 ? value * 32768 : value * 32767, true);
          offset += 2;
        }
      }

      const pcmBytes = new Uint8Array(pcm);
      console.log(`[Voice] PCM ready: ${pcmBytes.length} bytes, ${sampleCount} samples, ${(sampleCount/24000).toFixed(2)}s`);

      if (pcmBytes.length < 1000) {
        throw new Error('Recording too short - need at least 0.5s');
      }

      if (statusEl) statusEl.textContent = '☁️ Sending to Meta Muse Voice Transcribe...';

      // POST to Flask voice endpoint
      const response = await fetch('/api/voice/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: pcm
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || 'Transcription failed');
      }

      const transcript = result.transcript || result.final_transcript || '';

      if (!transcript) {
        throw new Error('No transcript returned');
      }

      // Fill message textarea
      const currentText = textarea.value.trim();
      if (currentText) {
        textarea.value = currentText + ' ' + transcript;
      } else {
        textarea.value = transcript;
      }

      // Trigger input event for @ mention autocomplete to detect
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      textarea.focus();

      // Show success
      if (statusEl) {
        statusEl.textContent = `✅ "${transcript.substring(0, 60)}..." filled from voice (${result.source}) - edit and send!`;
      }
      if (recordingIndicator) {
        recordingIndicator.classList.add('d-none');
      }

      logAsCode(transcript, result.source, result.duration_seconds || (sampleCount/24000), pcmBytes.length);

      // Auto-resize textarea
      textarea.style.height = 'auto';
      textarea.style.height = textarea.scrollHeight + 'px';

      console.log('[Voice] Transcript filled:', transcript);

    } catch (error) {
      console.error('[Voice] Transcription error:', error);
      if (statusEl) statusEl.textContent = `❌ Voice error: ${error.message} - try again or type manually`;
      if (recordingIndicator) {
        recordingIndicator.innerHTML = `<span style="color:#ef4444;">❌ ${error.message}</span>`;
        setTimeout(() => recordingIndicator.classList.add('d-none'), 3000);
      }
    } finally {
      chunks = [];
      isRecording = false;
      micBtn.disabled = false;
      micBtn.classList.remove('recording', 'btn-danger');
      micBtn.classList.add('btn-ghost');
      micBtn.innerHTML = '<i class="bi bi-mic"></i> Record';
    }
  }

  micBtn.addEventListener('click', () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  console.log('[Voice] Initialized with Meta Muse STT - button ready');
});
