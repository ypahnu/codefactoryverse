# Voice - TTS & STT for Chat

## Overview

Chat should have voice: **STT** (speech-to-text, user talks, transcribed to TaskMessage) and **TTS** (text-to-speech, agent reply spoken aloud).

User requested: **Meta Muse for STT, Cartesia for TTS, both keys in .env**

## Existing Projects Inventory (Checked)

### `/voice` - STT Meta Muse Voice Transcribe (Real-time WebSocket)

**Path:** `/home/zveb/Documents/my-project/voice/`

- `run.py` (61 LOC): `wss://api.meta.ai/v1/asr/realtime?sessionId=stream-uuid`, PCM 24kHz mono 80ms frames 3840 bytes, model `muse-voice-transcribe-1.0`, mode PUSH_TO_TALK, needs `MODEL_API_KEY=LLM_...`
- `web.py` (148 LOC): `AudioContext {sampleRate:24000}`, ScriptProcessor 4096, float→int16 LE conversion, `POST /record` octet-stream, saves `recording.pcm`
- `recording.pcm` - saved 24kHz mono PCM file
- `.env` - `MODEL_API_KEY`

Flow: `web.py:5080` records mic → saves PCM → `run.py` streams via websockets → prints transcript events.

### `/tts_cartesia` - TTS Cartesia Sonic (HTTP POST)

**Path:** `/home/zveb/Documents/my-project/tts_cartesia/`

- `run.py` (216 LOC): `POST https://api.cartesia.ai/tts/bytes`, headers `X-API-Key: sk_car_..., Cartesia-Version: 2026-08-14`, body `model_id sonic-3.6|sonic-3|sonic-2|sonic-multilingual, transcript, voice UUID, output_format wav pcm_s16le 44100, generation_config speed/volume`, returns WAV bytes
- `web.py` (407 LOC): UI `:5055` with dropdown from `voices.json` 2767 lines 100 voices, model selector, speed/volume sliders, `<audio>` element
- `voices.json` - 100 voice IDs, top: Skylar db6b0ed5..., Daniel 47c38ca4..., Gemma 62ae83ad..., Parker 30894953..., Archie ef191366...
- `requirements.txt`: `requests`, `python-dotenv`
- `output.wav` - generated sample

### `/3DAgents` - Most Complete Hybrid Reference

- `src/voice/MetaTranscriber.js` 201 LOC: `@xenova/transformers` pipeline automatic-speech-recognition, Whisper tiny 39MB, blobToAudioData via AudioContext 16kHz
- `src/voice/VoiceManager.js` 203 LOC: mode auto|meta|webspeech|whisper, Web Speech API interim, MediaRecorder webm opus, fallback chain Web Speech → Meta → Server Whisper
- `src/secretary/SecretaryClient.js` 120 LOC: voice → action `POST /api/secretary` with transcript+worldState, TTS via `speechSynthesis`
- `server/transcribe.js` 28 LOC: multer memory 10MB, transcribeAudio
- `server/llm.js` 290 LOC: MODEL_API_KEY detection, if LLM_ mock, else OpenAI Whisper, secretaryInterpret with tools spawn_agent etc

**Key Insight:** Already solved 3-tier fallback: Web Speech (instant interim) → Transformers local Meta → Server Whisper. Also handles proxy error.

## Proposed Architecture for CodeFactory

```
[Browser Mic]
   ↓ MediaRecorder 24kHz PCM or webm opus
   ↓ VoiceManager.js (auto mode)
   ├─→ Web Speech API (webkitSpeechRecognition) - interim fast, free, no key
   ├─→ Meta Muse Voice (wss://api.meta.ai/v1/asr/realtime) - high accuracy, needs MODEL_API_KEY
   └─→ Server Whisper fallback (POST /api/voice/transcribe) - multer + OpenAI whisper-1
   ↓
POST /projects/team/<slug>/<project>/tasks/<id>/voice/transcribe
   body: FormData {audio: Blob webm/wav/pcm}
   → returns {text, final, source: meta|webspeech|whisper}
   → creates TaskMessage(role=user, content=text, message_type=voice, audio_url=null, transcript_source=meta)
   → broadcast_to_task_agents() + mention detection + auto-reply
   ↓
Agent runs (existing run_agent_factory)
   ↓
Cartesia TTS (if enabled)
   POST /projects/team/.../tasks/.../voice/tts {message_id, voice_id}
   → cartesia_tts.py tts_bytes_request(transcript, voice_id, model_id sonic-3.6, speed, volume)
   → saves WAV to uploads/voice/{task_id}/{message_id}.wav
   → returns {audio_url}
   → frontend <audio autoplay> + per-message ▶️ Speak button
```

## DB Changes Needed

Add to `TaskMessage`:
```python
audio_url = db.Column(String(512), nullable=True)  # /uploads/voice/{task_id}/{message_id}.wav
transcript_source = db.Column(String(20), nullable=True)  # meta, webspeech, whisper, cartesia
voice_id = db.Column(String(100), nullable=True)  # Cartesia voice UUID
tts_status = db.Column(String(20), default='none')  # none, pending, done, failed
```

Or create separate `VoiceMessage` table linked to `TaskMessage`.

## New Files to Create (Preparation)

- `app/blueprints/voice/routes.py`:
  ```python
  @voice_bp.route('/team/<team>/.../tasks/<id>/voice/transcribe', methods=['POST'])
  def transcribe(): # FormData audio Blob -> Meta / Whisper -> TaskMessage
  
  @voice_bp.route('/.../voice/tts', methods=['POST'])
  def tts(): # {message_id, voice_id} -> Cartesia -> save wav -> return url
  ```

- `app/services/cartesia_tts.py` (copy from `tts_cartesia/run.py`):
  ```python
  def tts_bytes_request(transcript, voice_id=Slylar, model_id="sonic-3.6", speed=0, volume=1.0):
      POST https://api.cartesia.ai/tts/bytes
      headers X-API-Key, Cartesia-Version
      return wav_bytes
  ```

- `app/services/meta_stt.py` (copy from `voice/run.py`):
  ```python
  async def transcribe_realtime(pcm_bytes, api_key=MODEL_API_KEY):
      wss://api.meta.ai/v1/asr/realtime?sessionId=uuid
      model=muse-voice-transcribe-1.0, mode=PUSH_TO_TALK, audioEncoding PCM_24KHZ
  ```

- `app/static/js/voice.js` (new, based on `3DAgents/src/voice/VoiceManager.js`):
  - Mic button, MediaRecorder, AudioContext 24000, ScriptProcessor, Web Speech fallback

- `app/static/data/voices.json` (copy from `tts_cartesia/voices.json`)

## Frontend Changes (Preparation)

- `tasks/view.html`:
  - Mic button next to textarea: `<button id="voice-mic-btn"><i class="bi bi-mic"></i></button>`
  - Per-message speaker button: `<button class="tts-play" data-message-id="{{ msg.id }}" data-voice-id>▶️</button>`
  - Global `<audio id="voice-player">`
  - Voice selector dropdown: `<select id="voice-select">` loads voices.json

- `static/css/style.css`: mic recording animation (pulse red), audio player styles

## Env Vars (Both Keys in .env per User Request)

```
# Voice - Meta Muse STT
MODEL_API_KEY=LLM_...  # Already exists, used for muse-voice-transcribe-1.0

# Voice - Cartesia TTS
CARTESIA_API_KEY=sk_car_...  # From https://cartesia.ai, create at dashboard
```

Add to `app/config.py`:
```python
CARTESIA_API_KEY = os.environ.get('CARTESIA_API_KEY')
MODEL_API_KEY already exists
```

Add to `.env.example`.

## Security / Rate Limiting

- Rate limit transcribe 10/min per user (like 3DAgents)
- Max audio 100MB, 60s per clip
- Auth required (login_required)
- Save WAV to `uploads/voice/` which is gitignored

## Minimal MVP Implementation Order

1. Copy `tts_cartesia/voices.json` to `codefactoryverse/app/static/data/voices.json`
2. Create `app/services/cartesia_tts.py` with `tts_bytes_request()`
3. Create `app/blueprints/voice/routes.py` with `/transcribe` and `/tts` endpoints (start with mock returning hardcoded text)
4. Add mic button to `tasks/view.html` and `voice.js` with MediaRecorder + Web Speech interim
5. Test STT → creates TaskMessage → broadcast
6. Add speaker button per message + `cartesia_tts.py` real call
7. Test full loop: mic → STT → chat → agent reply → TTS → autoplay

## References

- `/voice/run.py` - Meta realtime ASR URI, FRAME_BYTES=3840, 80ms frames
- `/voice/web.py` - PCM recording + POST /record
- `/tts_cartesia/run.py` - Cartesia HTTP POST bytes request
- `/tts_cartesia/web.py` - UI with voice dropdown + audio player
- `/tts_cartesia/voices.json` - 100 voice IDs
- `/3DAgents/src/voice/MetaTranscriber.js` - local STT pattern
- `/3DAgents/src/voice/VoiceManager.js` - hybrid manager pattern (auto mode)
- `/3DAgents/server/llm.js` - Meta Llama key detection + whisper fallback
- `codefactoryverse/app/blueprints/tasks/routes.py` - insertion point for voice endpoint (broadcast_to_task_agents)
- `codefactoryverse/app/models.py` - TaskMessage broadcast model to reuse

## Implementation Status - DONE (Phase 0)

**Implemented 2026-10-27:**

- ✅ `app/services/meta_stt.py` - Meta Muse STT service with `transcribe_pcm_async()` + `transcribe_with_fallback()` (mock fallback if no key or empty result)
- ✅ `app/services/cartesia_tts.py` - Cartesia Sonic TTS with `tts_bytes_request()` and VOICES dict (Skylar, Daniel, Gemma, Parker, Archie)
- ✅ `app/blueprints/voice/routes.py` - Blueprint `voice_bp` with 3 endpoints:
  - `POST /api/voice/transcribe` - receives octet-stream PCM 24kHz mono 16-bit LE, calls `transcribe_with_fallback()`, returns {transcript, final_transcript, source, duration_seconds, request_log, response_log} with request as code logging
  - `POST /api/voice/cartesia/tts` - placeholder for TTS, logs request as code, returns mock if no CARTESIA_API_KEY
  - `GET /api/voice/status` - checks MODEL_API_KEY and CARTESIA_API_KEY availability
- ✅ `app/static/js/voice.js` - Frontend with AudioContext 24kHz, ScriptProcessor 4096, Float32->Int16 LE conversion, POST to /api/voice/transcribe, fills #chat-content-input textarea with transcript, triggers input event for @ mention autocomplete, shows recording indicator with thinking dots
- ✅ `tasks/view.html` - Added mic button #voice-mic-btn with <i class="bi bi-mic"> Record</i>, #voice-status small, #voice-recording-indicator with recording-dot + thinking dots, placeholder mentions voice
- ✅ `static/css/style.css` - Added #voice-mic-btn.recording red pulse, .recording-dot pulse, #voice-recording-indicator shimmer, .voice-transcript-flash
- ✅ `requirements.txt` - Added websockets==12.0
- ✅ `app/__init__.py` - Registered voice_bp at /api/voice, imported ProjectSandbox, ProjectActivity
- ✅ Tested: POST octet-stream 96000 bytes PCM -> 200 OK, transcript "Hey Joana, can you imagine a web page for the task?" (mock fallback), request_log as code printed to console per user request "Show me the request as code"

**How to Use:**
1. Open task view (e.g., Task 1 with JOANA_BOT)
2. Click Record button next to @ mention badges
3. Browser asks mic permission, shows "🔴 Recording... Speak now (e.g. @JOANA_BOT)"
4. Speak: "Hey Joana can you imagine a web page"
5. Click Stop -> shows "💾 Processing... -> ☁️ Sending to Meta Muse..."
6. Backend transcribes via Meta Muse (or mock if no key) and returns transcript
7. Frontend fills textarea with transcript: "Hey Joana, can you imagine..."
8. Edit if needed and click Add Message -> broadcast to all bots, auto-reply if mentioned (Joana replies with blue sky thinking)
9. Full request logs as code printed in console and saved in TaskMessage full_prompt behind + toggle

**Env:**
```
MODEL_API_KEY=LLM_... (Meta Muse STT)
CARTESIA_API_KEY=sk_car_... (TTS, optional for now)
```

**Next Steps for Full Voice Reply:**
- Add speaker button per message to call /api/voice/cartesia/tts and play <audio>
- Save WAV to uploads/voice/{task_id}/{message_id}.wav
- Auto-TTS after agent reply if enabled

Date: 2026-10-27
Status: Implemented Phase 0 (record button + STT fills message, mock fallback, request logs as code, thinking icon)

