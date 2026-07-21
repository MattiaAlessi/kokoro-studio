# 🌐 Kokoro Studio — API Reference

> **Base URL:** `http://127.0.0.1:8000` (default)
>
> **Interactive docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (Swagger UI)

---

## Starting the Server

```bash
kokoro-studio serve                    # 127.0.0.1:8000
kokoro-studio serve --port 8001        # 127.0.0.1:8001
kokoro-studio serve --host 0.0.0.0     # All interfaces
kokoro-studio serve --reload           # Dev mode with hot-reload
```

---

## Endpoints

### `GET /health`

Server health check.

**Response:**

```json
{
  "status": "ok",
  "version": "0.1.0",
  "engine": "Kokoro-82M",
  "voices": 29
}
```

---

### `GET /v1/models`

List available models (OpenAI-compatible format).

**Response:**

```json
{
  "object": "list",
  "data": [
    {
      "id": "kokoro-82m",
      "object": "model",
      "capabilities": {
        "tts": true,
        "streaming": true
      }
    },
    {
      "id": "kokoro-82m/af_heart",
      "object": "model",
      "capabilities": {
        "tts": true,
        "streaming": true
      }
    }
  ]
}
```

Each voice also has its own model entry (`kokoro-82m/<voice_name>`).

---

### `GET /v1/voices`

List all available voices with metadata.

**Response:**

```json
{
  "voices": [
    {
      "voice": "af_heart",
      "description": "American female — Heart",
      "language": "a (American English)",
      "gender": "female",
      "openai_compatible": null
    },
    {
      "voice": "af_alloy",
      "description": "American female — Alloy",
      "language": "a (American English)",
      "gender": "female",
      "openai_compatible": "alloy"
    }
  ]
}
```

The `openai_compatible` field shows the OpenAI voice alias when one exists.

---

### `POST /v1/audio/speech`

**OpenAI-compatible text-to-speech.** Generate audio from text.

**Request Body:**

```json
{
  "model": "kokoro-82m",
  "input": "Hello! This is a test of the Kokoro Studio API.",
  "voice": "af_heart",
  "response_format": "wav",
  "speed": 1.0
}
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | string | `"kokoro-82m"` | Model ID. Accepts `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts` for OpenAI compatibility |
| `input` | string | **required** | Text to synthesize. Max 4096 characters. |
| `voice` | string | `"af_heart"` | Voice name. See [Voice Names](#voice-names) below. |
| `response_format` | string | `"wav"` | Audio format. One of: `wav`, `mp3`, `flac`, `ogg`, `pcm`, `opus` (→ ogg) |
| `speed` | number | `1.0` | Speaking speed. Range: 0.25–4.0. |

**Voice Names:**

You can use any of the following formats:

| Format | Example |
|--------|---------|
| Direct Kokoro name | `"af_heart"`, `"am_onyx"`, `"bm_fable"` |
| OpenAI alias | `"alloy"` → `af_alloy`, `"echo"` → `am_echo`, `"fable"` → `bm_fable`, `"nova"` → `af_nova`, `"onyx"` → `am_onyx`, `"shimmer"` → `af_sky` |
| Case-insensitive | `"AF_HEART"`, `"Am_Onyx"` |
| Saved blend | `"my_custom_blend"` (if previously saved in the GUI) |

**Response:**

Returns binary audio data with the appropriate `Content-Type`:

| Format | Content-Type |
|--------|-------------|
| `wav` | `audio/wav` |
| `mp3` | `audio/mpeg` |
| `flac` | `audio/flac` |
| `ogg` | `audio/ogg` |
| `pcm` | `audio/L16;rate=24000;channels=1` |

A `Content-Disposition` header is included for file downloads.

**cURL Example:**

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Hello world","voice":"alloy","response_format":"wav"}' \
  --output speech.wav
```

**Python Example:**

```python
import requests

resp = requests.post("http://localhost:8000/v1/audio/speech", json={
    "input": "Hello from the Kokoro Studio API!",
    "voice": "af_heart",
    "response_format": "wav",
    "speed": 1.0,
})
with open("speech.wav", "wb") as f:
    f.write(resp.content)

print(f"Generated {len(resp.content)} bytes of audio")
```

**JavaScript/Node.js Example:**

```javascript
const response = await fetch("http://localhost:8000/v1/audio/speech", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    input: "Hello from the API!",
    voice: "af_heart",
    response_format: "wav",
  }),
});
const buffer = await response.arrayBuffer();
// Play or save the audio...
```

**Error Codes:**

| Code | Meaning |
|------|---------|
| 400 | Bad request — missing input, unknown voice, unsupported format, speed out of range, text too long (over 4096 chars) |
| 422 | Validation error — invalid JSON body |
| 500 | Internal server error — synthesis failed |

---

### `POST /v1/audio/stream`

Server-Sent Events (SSE) streaming. Audio chunks are sent as base64-encoded events.

**Request Body:** Same as `/v1/audio/speech`.

**Response (SSE):**

```
event: chunk
data: {"data": "AAAIGZ4..."}

event: chunk
data: {"data": "Z4AAAIGZ..."}

event: done
data: [DONE]
```

Each `chunk` event contains a base64-encoded PCM audio chunk (24 kHz, float32, mono). The stream ends with a `done` event.

**Python Example:**

```python
import requests
import base64
import numpy as np

resp = requests.post(
    "http://localhost:8000/v1/audio/stream",
    json={"input": "Hello streaming!", "voice": "af_heart"},
    stream=True,
)

chunks = []
for line in resp.iter_lines():
    if not line:
        continue
    if line.startswith(b"event: done"):
        break
    if line.startswith(b"data: "):
        import json
        payload = json.loads(line[6:].decode())
        chunk_bytes = base64.b64decode(payload["data"])
        chunks.append(np.frombuffer(chunk_bytes, dtype=np.float32))

audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
```

---

### `WebSocket /ws/stream`

Real-time bidirectional streaming via WebSocket.

**Client sends:**

```json
{
  "text": "Hello! This is a WebSocket streaming test.",
  "voice": "af_heart",
  "speed": 1.0
}
```

**Server sends (binary):**

1. One or more PCM chunks (raw float32, 24 kHz, mono) as binary messages.
2. A single binary message containing the complete WAV file.
3. A text message: `[DONE]`

**Python Example:**

```python
import asyncio
import json
import numpy as np
import websockets

async def stream_tts():
    async with websockets.connect("ws://localhost:8000/ws/stream") as ws:
        # Send request
        await ws.send(json.dumps({
            "text": "Hello WebSocket!",
            "voice": "af_heart",
            "speed": 1.0,
        }))

        # Receive audio chunks
        chunks = []
        async for msg in ws:
            if isinstance(msg, str) and msg == "[DONE]":
                break
            chunks.append(np.frombuffer(msg, dtype=np.float32))

        audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
        print(f"Received {len(audio)} samples ({len(audio) / 24000:.2f}s)")

asyncio.run(stream_tts())
```

---

## Speed Ranges

| Context | Min | Max | Default |
|---------|-----|-----|---------|
| API `/v1/audio/speech` | 0.25 | 4.0 | 1.0 |
| API SSML prosody rate | 0.5 | 2.0 | 1.0 |
| GUI speed control | 0.1 | 3.0 | 1.0 |

---

## Audio Format Details

| Format | Sample Rate | Bit Depth | Channels | Notes |
|--------|-------------|-----------|----------|-------|
| WAV | 24 kHz | 16-bit | Mono | Default, highest compatibility |
| PCM | 24 kHz | 32-bit float | Mono | Raw float32, no header |
| MP3 | 24 kHz | 192 kbps CBR | Mono | Requires `lameenc` |
| FLAC | 24 kHz | 16-bit | Mono | Lossless compression |
| OGG / Opus | 24 kHz | Vorbis | Mono | Good compression |
