# AGENTS.md

## This repository

`kilo323/fish-tts-adapter` — a small FastAPI service that translates OpenAI-format
TTS requests (`POST /v1/audio/speech`) into Fish Audio API calls
(`POST /v1/tts`). Any tool that speaks the OpenAI TTS API can use Fish Audio as a
drop-in provider. Python 3.13.

## Layout

- `app/main.py` — the entire application (one module, ~400 lines): env config, voice
  mapping, model/format mapping, the TTS endpoint, an admin voice- CRUD API, and an
  HTML admin UI.
- `app/requirements.txt` — only `fastapi`, `uvicorn[standard]`, `httpx`.
- `config/voices.json.example` — example of the voice map; the runtime file is
  `config/voices.json` (git-ignored, see below).
- `docker-compose.yml` — builds the image and maps the container to the host.
- `.github/workflows/docker.yml` — builds and pushes the image to GHCR on push to `master`.

## Build / run / test

There is no unit test suite and no lint/format config. To run locally from this repo
root:

```bash
pip install -r app/requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8110   # note the app.main:app module path
```

In the Docker image the working directory is `/app`, so there it is `uvicorn main:app`.
`docker compose up` builds and exposes the service on host port `8110` (container
`8080`).

Verified: `pip install -r app/requirements.txt` succeeds on Python 3.13, the app
imports, and the endpoints behave as documented — `/` and `/v1/models` (GET) return
JSON, `/admin` serves the HTML voice manager, and `POST /v1/audio/speech` returns
`500 "FISH_AUDIO_API_KEY not configured"` until `FISH_AUDIO_API_KEY` is set.

## Config (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `FISH_AUDIO_API_KEY` | *(required)* | Fish Audio API key |
| `FISH_AUDIO_BASE_URL` | `https://api.fish.audio` | Upstream base URL |
| `DEFAULT_FISH_MODEL` | `s2.1-pro-free` | Model for `tts-1` |
| `HD_FISH_MODEL` | `s2.1-pro` | Model for `tts-1-hd` |
| `REQUEST_TIMEOUT` | `60` | Upstream timeout (seconds) |
| `VOICE_MAP_PATH` | `/config/voices.json` | Voice map file path |

## Behaviour to remember when editing

- `config/voices.json` maps OpenAI voice names (`alloy`, `echo`, …) to Fish Audio
  reference IDs and is the only runtime-persisted config (`gitignore`s it). It is
  **read from disk on every request** — edits hot-reload without a restart, and the
  admin UI (`/admin`) edits it live. Missing or invalid file falls back to a default
  map.
- All OpenAI voice names currently default to the Fish Audio reference ID `"default"`
  (see `DEFAULT_VOICE_MAP` in `app/main.py`); real deployments overwrite this file.
- Unknown `model` falls back to `DEFAULT_FISH_MODEL`; unknown `response_format` falls
  back to `mp3`.
- `gitignore` also ignores `.env` and `__pycache__`; `.dockerignore` excludes
  `README.md`, `docker-compose.yml`, `config/`, etc. from the image build.
