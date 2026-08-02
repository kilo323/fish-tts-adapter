# Fish Audio → OpenAI-Compatible TTS Adapter

A lightweight adapter that translates OpenAI-format TTS requests (`POST /v1/audio/speech`) into Fish Audio API calls (`POST /v1/tts`), so any tool that speaks the OpenAI TTS API can use Fish Audio as a drop-in provider.

## What it does

```
Your app                     Adapter                      Fish Audio
(OpenAI format)         (this container)              (api.fish.audio)

POST /v1/audio/speech   →  translates request     →   POST /v1/tts
  { model, input,           to Fish Audio format        { reference_id, text,
    voice, format }                                     format, prosody }
                            
  ←  returns audio       ←  returns audio stream   ←   audio stream
    in OpenAI format
```

## Deploy on Unraid

### 1. Build the image

```bash
# SSH into Unraid, then:
cd /path/to/fish-tts-adapter
docker build -t fish-tts-adapter .
```

### 2. Configure

Edit `.env` with your Fish Audio API key:

```bash
FISH_AUDIO_API_KEY=your_key_here
```

### 3. Start

```bash
docker compose up -d
```

The adapter listens on **port 8110** (configurable in `docker-compose.yml`).

## Usage

### OpenAI-compatible request

```bash
curl -X POST http://10.0.0.10:8110/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "tts-1",
    "input": "Hello! Welcome to Fish Audio.",
    "voice": "alloy",
    "response_format": "mp3",
    "speed": 1.0
  }' \
  --output speech.mp3
```

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://10.0.0.10:8110/v1",
    api_key="not-needed",  # adapter uses its own Fish Audio key
)

response = client.audio.speech.create(
    model="tts-1",
    voice="alloy",
    input="Hello from Fish Audio!",
)
response.stream_to_file("output.mp3")
```

### List available voices

```bash
curl http://10.0.0.10:8110/voices
```

## Voice Mapping

Edit `config/voices.json` to map OpenAI voice names to Fish Audio voice model IDs:

```json
{
  "alloy":   "your-fish-audio-voice-id-1",
  "echo":    "your-fish-audio-voice-id-2",
  "fable":   "your-fish-audio-voice-id-3",
  "onyx":    "your-fish-audio-voice-id-4",
  "nova":    "your-fish-audio-voice-id-5",
  "shimmer": "your-fish-audio-voice-id-6"
}
```

You can also use Fish Audio voice IDs directly as the `voice` parameter — the adapter will pass them through.

## Model Mapping

| OpenAI model | Fish Audio model |
|---|---|
| `tts-1` | `s2.1-pro-free` (default) |
| `tts-1-hd` | `s2.1-pro` |
| `s1` | `s1` |
| `s2-pro` | `s2-pro` |
| `s2.1-pro` | `s2.1-pro` |
| `s2.1-pro-free` | `s2.1-pro-free` |

## Format Mapping

| OpenAI format | Fish Audio format |
|---|---|
| `mp3` | `mp3` |
| `opus` | `opus` |
| `wav` | `wav` |
| `pcm` | `pcm` |
| `aac` | `mp3` (fallback) |
| `flac` | `wav` (fallback) |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FISH_AUDIO_API_KEY` | *(required)* | Your Fish Audio API key |
| `FISH_AUDIO_BASE_URL` | `https://api.fish.audio` | Fish Audio API base URL |
| `DEFAULT_FISH_MODEL` | `s2.1-pro-free` | Default Fish Audio model |
| `HD_FISH_MODEL` | `s2.1-pro` | Model for `tts-1-hd` requests |
| `REQUEST_TIMEOUT` | `60` | Upstream request timeout (seconds) |
| `VOICE_MAP_PATH` | `/config/voices.json` | Path to voice mapping file |
