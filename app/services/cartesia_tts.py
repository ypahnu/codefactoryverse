"""
Cartesia TTS Service - for CodeFactory voice reply
Based on /tts_cartesia/run.py
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

CARTESIA_URL = "https://api.cartesia.ai/tts/bytes"
CARTESIA_VERSION = "2026-08-14"

def get_cartesia_key():
    try:
        from flask import current_app
        key = current_app.config.get('CARTESIA_API_KEY') or os.environ.get('CARTESIA_API_KEY')
        if key:
            return key
    except:
        pass
    return os.environ.get('CARTESIA_API_KEY')

def tts_bytes_request(transcript: str, voice_id: str = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4", model_id: str = "sonic-3.6", speed: float = 1.0, volume: float = 1.0, sample_rate: int = 44100) -> bytes:
    """
    Calls Cartesia Sonic TTS and returns WAV bytes
    Default voice: Skylar db6b0ed5-d5d3-463d-ae85-518a07d3c2b4
    Models: sonic-3.6, sonic-3, sonic-2, sonic-multilingual
    """
    api_key = get_cartesia_key()
    if not api_key:
        raise ValueError("CARTESIA_API_KEY not set - needed for TTS")

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "Cartesia-Version": CARTESIA_VERSION
    }

    # Use string format for voice ID (as in tts_cartesia/run.py which works)
    # Some API versions accept dict with mode/id, but string is more compatible
    body = {
        "model_id": model_id,
        "transcript": transcript,
        "voice": voice_id,  # String ID like "db6b0ed5-..." - matches run.py
        "output_format": {
            "container": "wav",
            "encoding": "pcm_s16le",
            "sample_rate": sample_rate
        },
        "generation_config": {
            "speed": speed,
            "volume": volume
        }
    }

    resp = requests.post(CARTESIA_URL, json=body, headers=headers, timeout=30)
    resp.raise_for_status()

    wav_bytes = resp.content

    # Validate RIFF header
    if not wav_bytes.startswith(b'RIFF'):
        logger.warning(f"Cartesia response not WAV: {wav_bytes[:100]}")
        # Might be JSON error
        try:
            err = resp.json()
            raise RuntimeError(f"Cartesia error: {err}")
        except:
            pass

    return wav_bytes

# Top 5 curated voices from tts_cartesia/voices.json
VOICES = {
    "Skylar": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",
    "Daniel": "47c38ca4-5f35-497b-b1a3-415245fb35e1",
    "Gemma": "62ae83ad-4f6a-430b-af41-a9bede9286ca",
    "Parker": "30894953-bcce-41fe-892c-15ce19c843ff",
    "Archie": "ef191366-f52f-447a-a398-ed8c0f2943a1",
}
