from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
import logging
import os

logger = logging.getLogger(__name__)

voice_bp = Blueprint('voice', __name__)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB max

@voice_bp.route('/transcribe', methods=['POST'])
@login_required
def transcribe():
    """
    Voice STT endpoint - receives PCM 24kHz mono 16-bit LE octet-stream
    as recorded by frontend AudioContext 24000

    Body: raw bytes (octet-stream) OR multipart with file field
    Returns: {transcript, final_transcript, source, duration_seconds, request_as_code}

    Uses Meta Muse Voice Transcribe via wss://api.meta.ai/v1/asr/realtime
    Fallback mock if no key
    """
    try:
        # Get PCM bytes from request
        pcm_bytes = None
        content_type = request.content_type or ""

        if 'octet-stream' in content_type or 'application/octet-stream' in content_type:
            pcm_bytes = request.get_data()
        elif 'multipart/form-data' in content_type or request.files:
            # File upload field 'audio' or 'file'
            file = request.files.get('audio') or request.files.get('file') or request.files.get('pcm')
            if file:
                pcm_bytes = file.read()
            else:
                # Try form data 'audio' as blob
                pcm_bytes = request.get_data()
        else:
            # Try raw data regardless
            pcm_bytes = request.get_data()
            if not pcm_bytes and request.form.get('audio'):
                # Base64 or other?
                pcm_bytes = request.form.get('audio').encode() if isinstance(request.form.get('audio'), str) else None

        if not pcm_bytes:
            return jsonify({"error": "No audio data received. Send octet-stream PCM 24kHz mono 16-bit LE"}), 400

        if len(pcm_bytes) % 2 != 0:
            return jsonify({"error": "16-bit PCM must have even number of bytes"}), 400

        if len(pcm_bytes) > MAX_UPLOAD_BYTES:
            return jsonify({"error": f"Audio too large: {len(pcm_bytes)} bytes > {MAX_UPLOAD_BYTES} max"}), 400

        if len(pcm_bytes) < 1000:
            return jsonify({"error": "Audio too short - need at least 0.5s"}), 400

        logger.info(f"Voice transcribe: {len(pcm_bytes)} bytes from user {current_user.username}")

        # === REQUEST LOGGING AS CODE (user wants to see logs) ===
        import json
        request_log_code = f"""# REQUEST LOG - Voice Transcribe (Meta Muse)
# User: {current_user.username} (ID {current_user.id})
# Audio: {len(pcm_bytes)} bytes, {len(pcm_bytes) / (24000*2):.2f}s duration
# Format: PCM 24kHz mono 16-bit LE (FRAME_BYTES=3840 per 80ms)

from app.services.meta_stt import transcribe_with_fallback
import os

MODEL_API_KEY = os.environ.get('MODEL_API_KEY')  # LLM_... from .env
pcm_bytes = b'... {len(pcm_bytes)} bytes ...'  # from frontend MediaRecorder + AudioContext 24000

# Meta Muse realtime API
# WSS URI: wss://api.meta.ai/v1/asr/realtime?sessionId=stream-uuid
# Handshake JSON:
# {{
#   "authorization": {{"accessToken": "Bearer {{MODEL_API_KEY}}"}},
#   "audioEncoding": "PCM_24KHZ",
#   "model": "muse-voice-transcribe-1.0",
#   "mode": "PUSH_TO_TALK"
# }}

result = transcribe_with_fallback(pcm_bytes)
print(f"Transcript: {{result['transcript']}}")
print(f"Source: {{result['source']}}")
print(f"Duration: {{result['duration_seconds']}}s")

# Returns dict:
# {{
#   "transcript": "Hey Joana, can you imagine...",
#   "final_transcript": "...",
#   "source": "meta-muse-voice-transcribe-1.0" or "mock-fallback",
#   "duration_seconds": 2.5
# }}
"""

        print(request_log_code)
        logger.info(f"Voice transcribe request logged as code for user {current_user.username}")

        # Call Meta STT service
        from app.services.meta_stt import transcribe_with_fallback
        result = transcribe_with_fallback(pcm_bytes)

        # Log result
        log_result_code = f"""# RESPONSE LOG - Voice Transcribe Result
# Transcript: {result.get('transcript','')[:200]}
# Source: {result.get('source')}
# Duration: {result.get('duration_seconds')}s
# Session: {result.get('session_id')}

# Frontend will fill textarea #chat-content-input with transcript:
# document.getElementById('chat-content-input').value = "{result.get('transcript','')[:100]}"
# Then user can edit and submit as chat message -> broadcast to all bots
"""
        print(log_result_code)

        # Return with request log as code for UI visibility
        response = {
            "transcript": result.get('transcript', ''),
            "final_transcript": result.get('final_transcript', result.get('transcript', '')),
            "source": result.get('source', 'unknown'),
            "duration_seconds": result.get('duration_seconds', 0),
            "session_id": result.get('session_id', ''),
            "pcm_bytes": len(pcm_bytes),
            "request_log": request_log_code,
            "response_log": log_result_code,
            "mock": result.get('mock', False)
        }

        return jsonify(response)

    except Exception as e:
        logger.exception(f"Voice transcribe failed: {e}")
        # Return error with request log for debugging
        return jsonify({
            "error": str(e),
            "transcript": "",
            "request_log": f"# Error in transcribe: {e}\n# Check MODEL_API_KEY in .env\n# Audio length: {len(request.get_data()) if request.get_data() else 0} bytes",
            "source": "error"
        }), 500

@voice_bp.route('/cartesia/tts', methods=['POST'])
@login_required
def cartesia_tts():
    """
    TTS endpoint - Cartesia Sonic (for future voice reply)
    Body JSON: {transcript, voice_id, model_id, speed, volume}
    Returns: audio/wav bytes or JSON with audio_url

    For now, placeholder that returns mock - full implementation needs CARTESIA_API_KEY
    """
    try:
        data = request.get_json() or {}
        transcript = data.get('transcript', '')[:500]
        voice_id = data.get('voice_id', 'db6b0ed5-d5d3-463d-ae85-518a07d3c2b4')  # Skylar default
        model_id = data.get('model_id', 'sonic-3.6')

        if not transcript:
            return jsonify({"error": "transcript required"}), 400

        # Log request as code
        tts_log_code = f"""# REQUEST LOG - Cartesia TTS
from app.services.cartesia_tts import tts_bytes_request

transcript = "{transcript[:100]}"
voice_id = "{voice_id}"  # Skylar default
model_id = "{model_id}"

wav_bytes = tts_bytes_request(
    transcript=transcript,
    voice_id=voice_id,
    model_id=model_id,
    speed=0,
    volume=1.0
)

# Save to uploads/voice/{{task_id}}/{{message_id}}.wav
# Return audio/wav or audio_url
"""

        print(tts_log_code)
        logger.info(f"TTS request: {len(transcript)} chars voice={voice_id} by {current_user.username}")

        # Try real Cartesia if key exists
        cartesia_key = current_app.config.get('CARTESIA_API_KEY') or os.environ.get('CARTESIA_API_KEY')
        if cartesia_key:
            try:
                from app.services.cartesia_tts import tts_bytes_request
                import base64
                wav_bytes = tts_bytes_request(transcript, voice_id, model_id)
                wav_b64 = base64.b64encode(wav_bytes).decode('utf-8')
                # Save to uploads for persistence
                try:
                    os.makedirs('uploads/voice', exist_ok=True)
                    with open(f'uploads/voice/{voice_id[:8]}_{len(transcript)}.wav', 'wb') as f:
                        f.write(wav_bytes)
                except:
                    pass
                return jsonify({
                    "success": True,
                    "message": f"TTS generated {len(wav_bytes)} bytes",
                    "transcript": transcript,
                    "voice_id": voice_id,
                    "model_id": model_id,
                    "wav_bytes": len(wav_bytes),
                    "wav_base64": wav_b64,
                    "audio_url": None,
                    "request_log": tts_log_code,
                    "source": "cartesia-sonic",
                    "mock": False
                })
            except Exception as e:
                logger.warning(f"Cartesia TTS failed, fallback to browser TTS: {e}")

        # Mock fallback - use browser speechSynthesis via frontend
        return jsonify({
            "success": True,
            "message": "TTS mock - set CARTESIA_API_KEY for real Cartesia audio, using browser speechSynthesis fallback",
            "transcript": transcript,
            "voice_id": voice_id,
            "voice_name": data.get('voice_name', ''),
            "model_id": model_id,
            "request_log": tts_log_code,
            "source": "mock-fallback-browser-tts",
            "mock": True,
            "fallback": "browser speechSynthesis"
        })

    except Exception as e:
        logger.exception(f"TTS failed: {e}")
        return jsonify({"error": str(e)}), 500

@voice_bp.route('/status', methods=['GET'])
@login_required
def status():
    """Check voice services availability"""
    has_meta_key = bool(current_app.config.get('MODEL_API_KEY') or os.environ.get('MODEL_API_KEY'))
    has_cartesia_key = bool(current_app.config.get('CARTESIA_API_KEY') or os.environ.get('CARTESIA_API_KEY'))
    
    return jsonify({
        "meta_muse_stt": {
            "available": has_meta_key,
            "model": "muse-voice-transcribe-1.0",
            "encoding": "PCM_24KHZ",
            "uri": "wss://api.meta.ai/v1/asr/realtime",
            "needs_key": "MODEL_API_KEY"
        },
        "cartesia_tts": {
            "available": has_cartesia_key,
            "model": "sonic-3.6",
            "voices": 100,
            "needs_key": "CARTESIA_API_KEY"
        },
        "websocket_library": True,
        "endpoints": {
            "transcribe": "/api/voice/transcribe (POST octet-stream PCM 24kHz)",
            "tts": "/api/voice/cartesia/tts (POST JSON)"
        }
    })
