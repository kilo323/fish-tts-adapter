"""
Fish Audio → OpenAI-Compatible TTS Adapter
Translates OpenAI /v1/audio/speech requests to Fish Audio /v1/tts format.
"""

import json
import os
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fish-tts-adapter")

app = FastAPI(title="Fish Audio OpenAI-Compatible TTS Adapter")

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
FISH_API_KEY = os.environ.get("FISH_AUDIO_API_KEY", "")
FISH_BASE_URL = os.environ.get("FISH_AUDIO_BASE_URL", "https://api.fish.audio")
DEFAULT_MODEL = os.environ.get("DEFAULT_FISH_MODEL", "s2.1-pro-free")
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# Voice mapping: OpenAI voice names → Fish Audio reference_ids
# Loaded from /config/voices.json if present, otherwise uses defaults.
# ---------------------------------------------------------------------------
DEFAULT_VOICE_MAP = {
    "alloy":   "default",
    "echo":    "default",
    "fable":   "default",
    "onyx":    "default",
    "nova":    "default",
    "shimmer": "default",
}

VOICE_MAP: dict[str, str] = {}

def load_voice_map():
    global VOICE_MAP
    config_path = os.environ.get("VOICE_MAP_PATH", "/config/voices.json")
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                VOICE_MAP = json.load(f)
            logger.info("Loaded voice map from %s (%d entries)", config_path, len(VOICE_MAP))
        except Exception as e:
            logger.warning("Failed to load voice map from %s: %s — using defaults", config_path, e)
            VOICE_MAP = DEFAULT_VOICE_MAP.copy()
    else:
        logger.info("No voice map found at %s — using defaults", config_path)
        VOICE_MAP = DEFAULT_VOICE_MAP.copy()

load_voice_map()

# ---------------------------------------------------------------------------
# Model name mapping: OpenAI model names → Fish Audio model header values
# ---------------------------------------------------------------------------
MODEL_MAP = {
    "tts-1":     os.environ.get("DEFAULT_FISH_MODEL", "s2.1-pro-free"),
    "tts-1-hd":  os.environ.get("HD_FISH_MODEL", "s2.1-pro"),
    # Pass-through: if someone sends a Fish Audio model name directly
    "s1":        "s1",
    "s2-pro":    "s2-pro",
    "s2.1-pro":  "s2.1-pro",
    "s2.1-pro-free": "s2.1-pro-free",
}

# Format mapping: OpenAI format names → Fish Audio format values
FORMAT_MAP = {
    "mp3":  "mp3",
    "opus": "opus",
    "aac":  "mp3",   # Fish Audio doesn't support AAC, fall back to MP3
    "flac": "wav",   # Fish Audio doesn't support FLAC, fall back to WAV
    "wav":  "wav",
    "pcm":  "pcm",
}

# Content-Type mapping
CONTENT_TYPE_MAP = {
    "mp3":  "audio/mpeg",
    "wav":  "audio/wav",
    "opus": "audio/opus",
    "pcm":  "audio/pcm",
}


# ---------------------------------------------------------------------------
# Health / root endpoint
# ---------------------------------------------------------------------------
@app.get("/")
async def health():
    return {
        "service": "Fish Audio OpenAI-Compatible TTS Adapter",
        "endpoints": {
            "/v1/audio/speech": "OpenAI-compatible TTS (POST)",
            "/v1/models":       "List available voices (GET)",
            "/voices":          "List voice mappings (GET)",
        },
        "upstream": FISH_BASE_URL,
        "default_model": DEFAULT_MODEL,
    }


# ---------------------------------------------------------------------------
# GET /v1/models — list available voices in OpenAI-compatible format
# ---------------------------------------------------------------------------
@app.get("/v1/models")
async def list_models():
    models = []
    for voice_name, fish_id in VOICE_MAP.items():
        models.append({
            "id": voice_name,
            "object": "model",
            "created": 0,
            "owned_by": "fish-audio",
            "meta": {"fish_audio_reference_id": fish_id},
        })
    # Also list Fish Audio models
    for model_name in MODEL_MAP:
        models.append({
            "id": model_name,
            "object": "model",
            "created": 0,
            "owned_by": "fish-audio",
        })
    return {"object": "list", "data": models}


# ---------------------------------------------------------------------------
# GET /voices — simple voice mapping reference
# ---------------------------------------------------------------------------
@app.get("/voices")
async def list_voices():
    return {"voices": VOICE_MAP}


# ---------------------------------------------------------------------------
# POST /v1/audio/speech — the main OpenAI-compatible TTS endpoint
# ---------------------------------------------------------------------------
@app.post("/v1/audio/speech")
async def tts_speech(request: Request):
    if not FISH_API_KEY:
        raise HTTPException(status_code=500, detail="FISH_AUDIO_API_KEY not configured")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Extract OpenAI-format fields
    text = body.get("input", "")
    if not text:
        raise HTTPException(status_code=400, detail="'input' field is required")

    voice = body.get("voice", "alloy")
    response_format = body.get("response_format", "mp3")
    speed = body.get("speed", 1.0)
    model = body.get("model", "tts-1")

    # Resolve Fish Audio voice (reference_id)
    # If the voice looks like a Fish Audio ID (long hex/hash), use directly
    fish_voice = VOICE_MAP.get(voice, voice)

    # Resolve Fish Audio model
    fish_model = MODEL_MAP.get(model, DEFAULT_MODEL)

    # Resolve Fish Audio format
    fish_format = FORMAT_MAP.get(response_format, "mp3")

    logger.info(
        "TTS request: voice=%s → %s, model=%s → %s, format=%s, speed=%.1f, text_len=%d",
        voice, fish_voice, model, fish_model, response_format, speed, len(text),
    )

    # Build Fish Audio request body
    fish_body = {
        "text": text,
        "reference_id": fish_voice if fish_voice != "default" else None,
        "format": fish_format,
        "prosody": {
            "speed": speed,
            "normalize_loudness": True,
        },
        "normalize": True,
        "chunk_length": 300,
        "latency": "normal",
    }

    # Remove None values
    fish_body = {k: v for k, v in fish_body.items() if v is not None}

    # Forward to Fish Audio
    headers = {
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
        "model": fish_model,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{FISH_BASE_URL}/v1/tts",
                headers=headers,
                json=fish_body,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Fish Audio upstream timeout")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Fish Audio upstream error: {e}")

    # Check upstream response
    if resp.status_code != 200:
        detail = resp.text[:500] if resp.text else "Unknown upstream error"
        logger.error("Fish Audio returned %d: %s", resp.status_code, detail)
        raise HTTPException(status_code=resp.status_code, detail=detail)

    # Return audio response
    content_type = CONTENT_TYPE_MAP.get(fish_format, "audio/mpeg")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="speech.{fish_format}"',
        },
    )


# ---------------------------------------------------------------------------
# Catch-all for unimplemented OpenAI endpoints
# ---------------------------------------------------------------------------
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(path: str):
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "message": f"Endpoint /v1/{path} is not implemented. Only /v1/audio/speech is supported.",
                "type": "invalid_request_error",
            }
        },
    )
