"""
Fish Audio → OpenAI-Compatible TTS Adapter
Translates OpenAI /v1/audio/speech requests to Fish Audio /v1/tts format.
Includes a web admin UI for managing voice mappings.
"""

import json
import os
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse, HTMLResponse

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
VOICE_MAP_PATH = os.environ.get("VOICE_MAP_PATH", "/config/voices.json")

# ---------------------------------------------------------------------------
# Voice map — read from disk every request (hot reload)
# ---------------------------------------------------------------------------
DEFAULT_VOICE_MAP = {
    "alloy": "default",
    "echo": "default",
    "fable": "default",
    "onyx": "default",
    "nova": "default",
    "shimmer": "default",
}


def get_voice_map() -> dict:
    """Load voice map from disk. Returns defaults if file missing or invalid."""
    if os.path.exists(VOICE_MAP_PATH):
        try:
            with open(VOICE_MAP_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning("Failed to load voice map: %s", e)
    return DEFAULT_VOICE_MAP.copy()


def save_voice_map(voices: dict):
    """Write voice map to disk."""
    os.makedirs(os.path.dirname(VOICE_MAP_PATH), exist_ok=True)
    with open(VOICE_MAP_PATH, "w") as f:
        json.dump(voices, f, indent=2)
    logger.info("Saved voice map (%d entries)", len(voices))


# ---------------------------------------------------------------------------
# Model mapping
# ---------------------------------------------------------------------------
MODEL_MAP = {
    "tts-1": os.environ.get("DEFAULT_FISH_MODEL", "s2.1-pro-free"),
    "tts-1-hd": os.environ.get("HD_FISH_MODEL", "s2.1-pro"),
    "s1": "s1",
    "s2-pro": "s2-pro",
    "s2.1-pro": "s2.1-pro",
    "s2.1-pro-free": "s2.1-pro-free",
}

FORMAT_MAP = {
    "mp3": "mp3",
    "opus": "opus",
    "aac": "mp3",
    "flac": "wav",
    "wav": "wav",
    "pcm": "pcm",
}

CONTENT_TYPE_MAP = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/opus",
    "pcm": "audio/pcm",
}


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------
@app.get("/")
async def health():
    voices = get_voice_map()
    return {
        "service": "Fish Audio OpenAI-Compatible TTS Adapter",
        "admin": "/admin",
        "endpoints": {
            "/v1/audio/speech": "OpenAI-compatible TTS (POST)",
            "/v1/models": "List available models (GET)",
            "/voices": "List voice mappings (GET)",
        },
        "voices_count": len(voices),
        "upstream": FISH_BASE_URL,
        "default_model": DEFAULT_MODEL,
    }


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------
@app.get("/v1/models")
async def list_models():
    voices = get_voice_map()
    models = []
    for voice_name, fish_id in voices.items():
        models.append({
            "id": voice_name,
            "object": "model",
            "created": 0,
            "owned_by": "fish-audio",
            "meta": {"fish_audio_reference_id": fish_id},
        })
    for model_name in MODEL_MAP:
        models.append({
            "id": model_name,
            "object": "model",
            "created": 0,
            "owned_by": "fish-audio",
        })
    return {"object": "list", "data": models}


# ---------------------------------------------------------------------------
# GET /voices
# ---------------------------------------------------------------------------
@app.get("/voices")
async def list_voices():
    return {"voices": get_voice_map()}


# ---------------------------------------------------------------------------
# POST /v1/audio/speech
# ---------------------------------------------------------------------------
@app.post("/v1/audio/speech")
async def tts_speech(request: Request):
    if not FISH_API_KEY:
        raise HTTPException(status_code=500, detail="FISH_AUDIO_API_KEY not configured")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    text = body.get("input", "")
    if not text:
        raise HTTPException(status_code=400, detail="'input' field is required")

    voice = body.get("voice", "alloy")
    response_format = body.get("response_format", "mp3")
    speed = body.get("speed", 1.0)
    model = body.get("model", "tts-1")

    voices = get_voice_map()
    fish_voice = voices.get(voice, voice)
    fish_model = MODEL_MAP.get(model, DEFAULT_MODEL)
    fish_format = FORMAT_MAP.get(response_format, "mp3")

    logger.info(
        "TTS: voice=%s→%s model=%s→%s fmt=%s speed=%.1f len=%d",
        voice, fish_voice, model, fish_model, response_format, speed, len(text),
    )

    fish_body = {
        "text": text,
        "reference_id": fish_voice if fish_voice != "default" else None,
        "format": fish_format,
        "prosody": {"speed": speed, "normalize_loudness": True},
        "normalize": True,
        "chunk_length": 300,
        "latency": "normal",
    }
    fish_body = {k: v for k, v in fish_body.items() if v is not None}

    headers = {
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
        "model": fish_model,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{FISH_BASE_URL}/v1/tts", headers=headers, json=fish_body)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Fish Audio upstream timeout")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Fish Audio upstream error: {e}")

    if resp.status_code != 200:
        detail = resp.text[:500] if resp.text else "Unknown upstream error"
        logger.error("Fish Audio returned %d: %s", resp.status_code, detail)
        raise HTTPException(status_code=resp.status_code, detail=detail)

    content_type = CONTENT_TYPE_MAP.get(fish_format, "audio/mpeg")
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="speech.{fish_format}"'},
    )


# ---------------------------------------------------------------------------
# Admin API — voice CRUD
# ---------------------------------------------------------------------------
@app.get("/admin/voices")
async def admin_get_voices():
    return get_voice_map()


@app.put("/admin/voices")
async def admin_put_voices(request: Request):
    try:
        voices = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(voices, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    save_voice_map(voices)
    return {"status": "ok", "count": len(voices)}


@app.post("/admin/voices/add")
async def admin_add_voice(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    name = data.get("name", "").strip()
    fish_id = data.get("fish_id", "").strip()
    if not name or not fish_id:
        raise HTTPException(status_code=400, detail="Both 'name' and 'fish_id' are required")
    voices = get_voice_map()
    voices[name] = fish_id
    save_voice_map(voices)
    return {"status": "ok", "voices": voices}


@app.delete("/admin/voices/{name}")
async def admin_delete_voice(name: str):
    voices = get_voice_map()
    if name not in voices:
        raise HTTPException(status_code=404, detail=f"Voice '{name}' not found")
    del voices[name]
    save_voice_map(voices)
    return {"status": "ok", "voices": voices}


# ---------------------------------------------------------------------------
# Admin UI
# ---------------------------------------------------------------------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_ui():
    return ADMIN_HTML


ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fish Audio TTS — Voice Manager</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 2rem; }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; color: #38bdf8; }
  .subtitle { color: #94a3b8; margin-bottom: 1.5rem; font-size: 0.9rem; }
  .card { background: #1e293b; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem;
          border: 1px solid #334155; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 0.5rem; color: #94a3b8; font-size: 0.8rem;
       text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #334155; }
  td { padding: 0.6rem 0.5rem; border-bottom: 1px solid #1e293b; }
  tr:hover td { background: #334155; }
  .name { font-weight: 600; color: #f1f5f9; }
  .id { font-family: monospace; font-size: 0.85rem; color: #94a3b8; }
  input { background: #0f172a; border: 1px solid #475569; color: #e2e8f0;
          padding: 0.5rem 0.75rem; border-radius: 6px; font-size: 0.9rem; }
  input:focus { outline: none; border-color: #38bdf8; }
  .add-row { display: flex; gap: 0.5rem; margin-top: 1rem; align-items: center; }
  .add-row input { flex: 1; }
  button { padding: 0.5rem 1rem; border-radius: 6px; border: none; cursor: pointer;
           font-size: 0.9rem; font-weight: 500; }
  .btn-add { background: #2563eb; color: white; }
  .btn-add:hover { background: #1d4ed8; }
  .btn-del { background: #ef4444; color: white; padding: 0.3rem 0.6rem; font-size: 0.8rem; }
  .btn-del:hover { background: #dc2626; }
  .toast { position: fixed; top: 1rem; right: 1rem; background: #16a34a; color: white;
           padding: 0.75rem 1.25rem; border-radius: 8px; font-weight: 500;
           opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 100; }
  .toast.show { opacity: 1; }
  .empty { color: #64748b; text-align: center; padding: 2rem; }
  a { color: #38bdf8; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<h1>🎤 Voice Manager</h1>
<p class="subtitle">Fish Audio TTS Adapter — <a href="/">API</a> · <a href="/v1/models">Models</a> · <a href="/voices">Voices JSON</a></p>

<div class="card">
  <table>
    <thead><tr><th>Voice Name</th><th>Fish Audio ID</th><th></th></tr></thead>
    <tbody id="voices"></tbody>
  </table>
  <div class="add-row">
    <input id="newName" placeholder="voice name (e.g. cortana)" />
    <input id="newId" placeholder="Fish Audio voice ID" />
    <button class="btn-add" onclick="addVoice()">+ Add</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2000);
}

async function load() {
  const r = await fetch('/admin/voices');
  const data = await r.json();
  const tbody = document.getElementById('voices');
  if (Object.keys(data).length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="empty">No voices configured</td></tr>';
    return;
  }
  tbody.innerHTML = Object.entries(data).map(([name, id]) =>
    `<tr>
      <td class="name">${esc(name)}</td>
      <td class="id">${esc(id)}</td>
      <td><button class="btn-del" onclick="delVoice('${esc(name)}')">✕</button></td>
    </tr>`
  ).join('');
}

function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

async function addVoice() {
  const name = document.getElementById('newName').value.trim();
  const fish_id = document.getElementById('newId').value.trim();
  if (!name || !fish_id) { toast('Fill in both fields'); return; }
  await fetch('/admin/voices/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, fish_id})
  });
  document.getElementById('newName').value = '';
  document.getElementById('newId').value = '';
  toast('Added ' + name);
  load();
}

async function delVoice(name) {
  if (!confirm('Delete voice "' + name + '"?')) return;
  await fetch('/admin/voices/' + encodeURIComponent(name), {method: 'DELETE'});
  toast('Deleted ' + name);
  load();
}

load();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Catch-all
# ---------------------------------------------------------------------------
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(path: str):
    return JSONResponse(
        status_code=404,
        content={"error": {"message": f"Endpoint /v1/{path} not implemented", "type": "invalid_request_error"}},
    )
