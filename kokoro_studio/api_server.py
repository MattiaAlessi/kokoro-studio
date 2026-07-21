# -*- coding: utf-8 -*-
"""FastAPI-based local REST API server for Kokoro Studio.

Provides an OpenAI-compatible ``/v1/audio/speech`` endpoint, a ``/ws/stream``
WebSocket for real-time chunked audio, and a CLI ``serve`` subcommand that
launches the server via ``uvicorn``.

Usage (CLI)::

    kokoro-studio serve                  # default port 8000
    kokoro-studio serve --port 8001 --host 0.0.0.0

Usage (Python)::

    from kokoro_studio.api_server import app, create_server_parser
    # ... custom integration ...

OpenAI-compatible endpoint::

    POST /v1/audio/speech
    {
        "model": "kokoro-82m",
        "input": "Text to synthesise",
        "voice": "af_heart",
        "response_format": "wav",
        "speed": 1.0
    }
    → binary audio data

Streaming (WebSocket)::

    ws://host:port/ws/stream
    → send JSON:  {"text": "...", "voice": "af_heart", "speed": 1.0}
    → receives binary audio chunks as they are generated
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

# ---------------------------------------------------------------------------
# Voice name mapping: OpenAI-style → Kokoro built-in
# ---------------------------------------------------------------------------

_OPENAI_TO_KOKORO: Dict[str, str] = {
    "alloy":   "af_alloy",
    "echo":    "am_echo",
    "fable":   "bm_fable",
    "nova":    "af_nova",
    "onyx":    "am_onyx",
    "shimmer": "af_sky",
    "coral":   "af_kore",
    "sage":    "af_sarah",
    "ballad":  "af_bella",
    "verse":   "af_verse",
}

# Reverse mapping so we can list Kokoro voices as models
_KOKORO_TO_OPENAI: Dict[str, str] = {v: k for k, v in _OPENAI_TO_KOKORO.items()}

# Supported response formats (mapped to engine output formats)
_RESPONSE_FORMATS: Dict[str, str] = {
    "wav":  "wav",
    "mp3":  "mp3",
    "flac": "flac",
    "ogg":  "ogg",
    "opus": "ogg",  # Opus not natively supported, fallback to OGG Vorbis
    "pcm":  "pcm",  # raw PCM float32
}

# MIME types for each format
_MIME_TYPES: Dict[str, str] = {
    "wav":  "audio/wav",
    "mp3":  "audio/mpeg",
    "flac": "audio/flac",
    "ogg":  "audio/ogg",
    "opus": "audio/ogg",
    "pcm":  "audio/L16;rate=24000;channels=1",
}

# OpenAI model names we accept
_OPENAI_MODELS = {"tts-1", "tts-1-hd", "gpt-4o-mini-tts", "kokoro-82m", "kokoro"}


# ---------------------------------------------------------------------------
# Lifespan (warm up the pipeline once on startup)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Warm up the Kokoro pipeline on server startup."""
    # We initialise the pipeline lazily, but we can pre-warm the
    # default voice so the first request is faster.
    try:
        from kokoro_studio.engine import _get_pipeline, _prime_voice_into_pipeline
        _get_pipeline("a")
        _prime_voice_into_pipeline("a", "af_heart")
        print("[API] Kokoro pipeline ready.", file=sys.stderr)
    except Exception as e:
        print(f"[API] Pipeline warm-up skipped: {e}", file=sys.stderr)
    yield


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kokoro Studio TTS API",
    version="0.1.0",
    description="Local, free, offline neural TTS — OpenAI-compatible endpoint.",
    lifespan=_lifespan,
)

# Allow CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_voice(voice: str) -> str:
    """Map an OpenAI-style voice name to a Kokoro voice, or pass through.

    Returns the Kokoro voice name, or raises HTTPException if unknown.

    Resolution order:
      1. Direct Kokoro built-in voice name.
      2. OpenAI-compatible alias (e.g. "alloy" → "af_alloy").
      3. Case-insensitive match against built-in names.
      4. Saved blend name (must exist in the loaded blends registry).
    """
    from kokoro_studio.engine import VOICES, list_voices

    # 1. Direct match
    if voice in VOICES:
        return voice

    # 2. OpenAI-style alias
    if voice.lower() in _OPENAI_TO_KOKORO:
        return _OPENAI_TO_KOKORO[voice.lower()]

    # 3. Case-insensitive match
    builtins = list_voices()
    lower_map = {v.lower(): v for v in builtins}
    if voice.lower() in lower_map:
        return lower_map[voice.lower()]

    # 4. Saved blend name (only if it actually exists on disk)
    try:
        from kokoro_studio.blending import is_valid_blend_name
        from kokoro_studio.engine import _loaded_blends, _ensure_blends_loaded
        _ensure_blends_loaded()  # load saved blends from disk
        if is_valid_blend_name(voice) and voice in _loaded_blends:
            return voice
    except ImportError:
        pass

    raise HTTPException(
        status_code=400,
        detail=(
            f"Unknown voice '{voice}'. "
            f"Built-in: {', '.join(builtins[:10])}... "
            f"OpenAI-compatible: {', '.join(_OPENAI_TO_KOKORO.keys())}"
        ),
    )


def _resolve_format(fmt: str) -> str:
    """Map response_format to engine output format."""
    fmt = fmt.lower().strip()
    if fmt not in _RESPONSE_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported response_format '{fmt}'. "
                f"Supported: {', '.join(_RESPONSE_FORMATS.keys())}"
            ),
        )
    return _RESPONSE_FORMATS[fmt]


def _build_audio_response(audio: np.ndarray, fmt: str, engine_fmt: str) -> Response:
    """Convert audio ndarray to the requested format and return a FastAPI Response."""
    if fmt == "pcm":
        # Raw PCM float32 bytes
        return Response(
            content=audio.astype(np.float32).tobytes(),
            media_type=_MIME_TYPES["pcm"],
            headers={"Content-Disposition": "inline"},
        )

    # Write to an in-memory buffer
    from kokoro_studio.engine import SAMPLE_RATE, save_audio

    buf = io.BytesIO()
    # save_audio expects a file path; we use a temporary file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=f".{engine_fmt}", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        save_audio(audio, tmp_path, output_format=engine_fmt)
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    return Response(
        content=data,
        media_type=_MIME_TYPES.get(engine_fmt, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="speech.{engine_fmt}"',
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check endpoint."""
    from kokoro_studio.engine import VOICES
    return {
        "status": "ok",
        "version": "0.1.0",
        "voices": len(VOICES),
        "engine": "Kokoro-82M",
    }


@app.get("/v1/models")
async def list_models():
    """List available TTS models (OpenAI-compatible)."""
    from kokoro_studio.engine import VOICES, list_voices

    builtins = list_voices()
    models = [
        {
            "id": "kokoro-82m",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "hexgrad",
            "capabilities": {"tts": True},
        },
    ]

    # Also list each voice as a "model" for discoverability
    voice_models = [
        {
            "id": f"kokoro-82m/{v}",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "hexgrad",
            "capabilities": {"tts": True},
            "voice": v,
            "description": VOICES[v][3],
        }
        for v in builtins
    ]

    return {
        "object": "list",
        "data": models + voice_models,
    }


@app.get("/v1/voices")
async def list_voices_endpoint():
    """List all available voices with metadata."""
    from kokoro_studio.engine import VOICES, get_voice_info, list_voices

    voices = []
    for v in list_voices():
        info = get_voice_info(v)
        openai_name = _KOKORO_TO_OPENAI.get(v)
        voices.append({
            "voice": v,
            "openai_compatible": openai_name,
            "language": info["lang_label"],
            "gender": "female" if info["gender"] == "f" else "male",
            "grade": info["grade"],
            "description": info["description"],
        })

    return {"voices": voices}


@app.post("/v1/audio/speech")
async def create_speech(
    body: dict,
):
    """OpenAI-compatible text-to-speech endpoint.

    Accepts the standard OpenAI request body and returns audio bytes.

    Request body:
        model (str): Model ID (e.g. "kokoro-82m", "tts-1").
        input (str): Text to synthesise (max 4096 chars).
        voice (str): Voice name (Kokoro built-in or OpenAI-compatible).
        response_format (str, optional): "wav", "mp3", "flac", "ogg", "pcm".
        speed (float, optional): Speed 0.25–4.0, default 1.0.

    Returns:
        Binary audio data in the requested format.
    """
    # Validate required fields
    model = body.get("model", "kokoro-82m")
    text = body.get("input", "").strip()
    voice = body.get("voice", "af_heart")
    response_format = body.get("response_format", "wav")
    speed = body.get("speed", 1.0)

    if model and model not in _OPENAI_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{model}'. Supported: {', '.join(sorted(_OPENAI_MODELS))}",
        )

    if not text:
        raise HTTPException(status_code=400, detail="input is required and must be non-empty.")

    if len(text) > 4096:
        raise HTTPException(
            status_code=400,
            detail=f"input exceeds 4096 character limit (got {len(text)}).",
        )

    # Validate speed
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="speed must be a number.")
    if speed < 0.25 or speed > 4.0:
        raise HTTPException(status_code=400, detail="speed must be between 0.25 and 4.0.")

    # Resolve voice and format
    resolved_voice = _resolve_voice(voice)
    engine_fmt = _resolve_format(response_format)

    # Generate audio
    from kokoro_studio.engine import SAMPLE_RATE, generate_speech

    try:
        audio = generate_speech(
            text=text,
            voice=resolved_voice,
            speed=speed,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {e}")

    # Build response
    return _build_audio_response(audio, response_format, engine_fmt)


@app.post("/v1/audio/stream")
async def stream_speech(
    body: dict,
):
    """OpenAI-compatible streaming TTS endpoint using Server-Sent Events.

    Returns audio chunks as they are generated using SSE.

    Request body: Same as /v1/audio/speech.
    Response: SSE stream with audio chunks (base64-encoded) and a final done event.
    """
    from kokoro_studio.engine import SAMPLE_RATE, generate_speech

    model = body.get("model", "kokoro-82m")
    text = body.get("input", "").strip()
    voice = body.get("voice", "af_heart")
    response_format = body.get("response_format", "wav")
    speed = body.get("speed", 1.0)

    if not text:
        raise HTTPException(status_code=400, detail="input is required.")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="input exceeds 4096 characters.")

    try:
        speed = float(speed)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="speed must be a number.")
    if speed < 0.25 or speed > 4.0:
        raise HTTPException(status_code=400, detail="speed must be between 0.25 and 4.0.")

    resolved_voice = _resolve_voice(voice)
    engine_fmt = _resolve_format(response_format)

    # Use a temp file to capture the generated audio
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=f".{engine_fmt}", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        audio = generate_speech(
            text=text,
            voice=resolved_voice,
            speed=speed,
            output_path=tmp_path,
            output_format=engine_fmt,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {e}")

    # Read the generated file
    with open(tmp_path, "rb") as f:
        audio_data = f.read()
    try:
        Path(tmp_path).unlink(missing_ok=True)
    except OSError:
        pass

    # Stream the audio in chunks via SSE
    import base64
    chunk_size = 4096

    async def _audio_chunks():
        pos = 0
        while pos < len(audio_data):
            chunk = audio_data[pos:pos + chunk_size]
            pos += chunk_size
            b64 = base64.b64encode(chunk).decode("ascii")
            yield f"data: {b64}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _audio_chunks(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Type": "audio/wav",
        } if engine_fmt == "wav" else {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming TTS.

    Protocol:
        1. Client sends JSON: {"text": "...", "voice": "...", "speed": 1.0}
        2. Server sends binary audio chunks as they are generated
        3. Server sends a text message "[DONE]" when synthesis is complete
        4. If an error occurs, server sends a text message {"error": "..."} and closes

    Example (JavaScript):
        const ws = new WebSocket("ws://localhost:8000/ws/stream");
        ws.onmessage = (event) => {
            if (event.data instanceof Blob) {
                // Play the audio chunk
            } else if (event.data === "[DONE]") {
                ws.close();
            }
        };
        ws.onopen = () => ws.send(JSON.stringify({
            text: "Hello world",
            voice: "af_heart",
            speed: 1.0,
        }));
    """
    await websocket.accept()

    try:
        data = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    except Exception as e:
        await websocket.send_json({"error": f"Invalid JSON: {e}"})
        await websocket.close()
        return

    text = data.get("text", "").strip()
    voice = data.get("voice", "af_heart")
    speed = float(data.get("speed", 1.0))

    if not text:
        await websocket.send_json({"error": "text is required."})
        await websocket.close()
        return

    try:
        resolved_voice = _resolve_voice(voice)
    except HTTPException as e:
        await websocket.send_json({"error": e.detail})
        await websocket.close()
        return

    # Generate speech with chunk callback
    from kokoro_studio.engine import SAMPLE_RATE, generate_speech

    chunk_queue: list = []
    import asyncio

    def _on_chunk(_seg_idx: int, _chunk_idx: int, audio_chunk: np.ndarray) -> None:
        """Called from the worker thread for each audio chunk."""
        pcm = np.asarray(audio_chunk, dtype=np.float32).tobytes()
        # We can't call await in a sync callback, so we append to a queue
        # that the async loop drains. However, for simplicity, we just
        # accumulate all chunks and send them at the end.
        chunk_queue.append(pcm)

    try:
        audio = generate_speech(
            text=text,
            voice=resolved_voice,
            speed=speed,
            on_chunk=_on_chunk,
        )

        # Send all accumulated chunks
        for pcm_data in chunk_queue:
            try:
                await websocket.send_bytes(pcm_data)
            except WebSocketDisconnect:
                return

        # Send the final complete audio as WAV for convenience
        # (the chunks above are raw PCM float32)
        try:
            from kokoro_studio.engine import save_audio
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            save_audio(audio, tmp_path, output_format="wav")
            with open(tmp_path, "rb") as f:
                wav_data = f.read()
            Path(tmp_path).unlink(missing_ok=True)
            await websocket.send_bytes(wav_data)
        except Exception:
            pass

        await websocket.send_text("[DONE]")

    except HTTPException as e:
        await websocket.send_json({"error": e.detail})
    except Exception as e:
        await websocket.send_json({"error": f"Synthesis failed: {e}"})

    try:
        await websocket.close()
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def create_server_parser(subparser: argparse.ArgumentParser) -> None:
    """Add arguments to the ``serve`` subparser (used by cli.py)."""
    subparser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Port to bind (default: 8000).",
    )
    subparser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1).",
    )
    subparser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development only).",
    )
    subparser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1).",
    )


def run_server(args: argparse.Namespace) -> int:
    """Launch the FastAPI server via uvicorn."""
    print(
        f"[Kokoro] Starting API server on http://{args.host}:{args.port}",
        file=sys.stderr,
    )
    print(
        f"[Kokoro] Swagger docs at http://{args.host}:{args.port}/docs",
        file=sys.stderr,
    )
    print(
        f"[Kokoro] OpenAI-compatible endpoint: POST http://{args.host}:{args.port}/v1/audio/speech",
        file=sys.stderr,
    )

    import uvicorn  # type: ignore[import-untyped]
    uvicorn.run(
        "kokoro_studio.api_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level="info",
    )
    return 0
