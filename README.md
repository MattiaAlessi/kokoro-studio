# 🎙  Kokoro Studio

> **FREE · OFFLINE · PRIVATE · FAST · NO CREDITS**

A full-featured PySide6 desktop GUI for the [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
neural text-to-speech model — a competitive local alternative to cloud TTS
services, with **no API costs, no rate limits, no data leaving your machine.**

29 built-in voices · real-time streaming · multi-speaker dialogue ·
voice blending · SSML controls · audiobook builder · batch processing ·
CLI mode · local REST API · and more.

---

## ✨ Features at a Glance

### Core TTS

| Feature | Description |
|---------|-------------|
| **29 built-in voices** | American & British English, male/female, with grade/gender/language metadata |
| **Real-time streaming** 🎧 | Audio starts playing ~200 ms after clicking Generate — no waiting |
| **Speed control** | 0.1× to 3.0× via coupled slider + spinbox |
| **Multi-format export** | WAV, FLAC, OGG (via `soundfile`), MP3 (via `lameenc`, no FFmpeg) |
| **Multi-speaker dialogue** 🎭 | Switch voices mid-script with `[voice_name]:` markers |
| **SSML-lite controls** 🎙 | `<break>`, `<emphasis>`, `<prosody rate="...">` tags |
| **Voice blending** 🎻 | Blend any two voices with an alpha slider, save as presets |

### Workflow & Productivity

| Feature | Description |
|---------|-------------|
| **Document import** | Open `.txt`, `.pdf`, `.epub` files; drag-and-drop onto the editor |
| **Pronunciation dictionary** | Whole-word substitutions with case-sensitive, longest-rule-first matching |
| **Audio post-processing** 🎚 | Trim silence, volume boost/cut, fade in/out, normalize (peak or RMS loudness) |
| **Character profiles** 🎭 | Save voice + speed + pronunciation rules as named one-click presets (9 built-in profiles) |
| **Emotion / style sliders** 🎭 | Energy, Warmth, Expressiveness sliders + 10 named presets |
| **Generation history** 🕒 | SQLite-backed log — replay, re-export, or reload past generations |
| **Batch generation queue** 📦 | Generate multiple texts sequentially with per-item progress |
| **Audiobook chapter builder** 📚 | Import EPUB/TXT, assign voices per chapter, export as separate files or merged audio |
| **Project management** 💾 | Save/load complete workspace state as `.ksproj` files |
| **Keyboard shortcuts** | Ctrl+G Generate, Ctrl+P Preview, Space Play/Pause, and more |

### Platform & Integration

| Feature | Description |
|---------|-------------|
| **Light / Dark theme toggle** 🌙☀️ | Persistent preference |
| **Batch CLI mode** 💻 | `kokoro-studio batch input.txt --voice af_heart` — headless generation |
| **Local REST API** 🌐 | FastAPI server with OpenAI-compatible `/v1/audio/speech` endpoint |
| **WebSocket streaming** | Real-time audio streaming via WebSocket and SSE |
| **Swagger docs** | Interactive API docs at `http://localhost:8000/docs` |

---

## 📦 Install

### 1. Prerequisites

- **Python 3.10+**
- The Kokoro model voice pack (~300 MB) downloads automatically on first run.

### 2. Clone & install

```bash
git clone <repo-url> kokoro-studio
cd kokoro-studio
pip install -r requirements.txt
```

This installs:

| Package | Purpose |
|---------|---------|
| `PySide6` | Qt GUI framework |
| `kokoro` | TTS engine + voice packs |
| `soundfile` | WAV / FLAC / OGG I/O |
| `numpy` | Audio array handling |
| `lameenc` | Pure-Python MP3 encoding (no FFmpeg) |
| `pypdf`, `ebooklib`, `beautifulsoup4`, `lxml` | Document parsers (PDF, EPUB) |

### 3. Launch

```bash
python -m kokoro_studio
```

Or with the optional editable install:

```bash
pip install -e .
kokoro-studio
```

### Optional: API Server dependencies

```bash
pip install -e '.[server]'
# or: pip install fastapi uvicorn python-multipart sse-starlette
```

---

## 🚀 Quick Start

1. **Pick a voice** from the left panel (29 English presets).
2. **Type or paste** text into the editor — or **drop a `.txt` / `.pdf` / `.epub` file** onto it.
3. **Choose an output format** (WAV / MP3 / FLAC / OGG).
4. **Click Generate**. The status bar shows live chunk progress. Audio plays automatically ~200 ms later via real-time streaming.
5. **Stop playback** with the ■ Stop button, or **Space** to play/pause.

> **Tip**: The **Preview selected voice** button under the voice list generates a short fixed-phrase sample — great for browsing voices.

---

## 🎭 Multi-Speaker Dialogue Mode

Switch voices mid-script by starting a line with a `[voice_name]:` marker:

```text
[af_heart]: Hello! My name is Heart.
[am_adam]:  And I'm Adam. Nice to meet you.
[af_heart]: Dialogue mode automatically inserts a 0.25 s gap between speakers.
```

- One marker per line, at the start (leading whitespace allowed).
- Lines after a marker stay on the previous voice until the next marker.
- Lines before the first marker use the default voice (dropdown selection).
- Unknown voice tokens fall back to the default voice with a warning.
- Works with blended voices too — `[my_custom_blend]:` is supported.

---

## 🎻 Voice Blending

Create custom voices by blending any two built-in voices:

1. Click **🎛 Blend** in the toolbar.
2. Select **Voice A** and **Voice B**.
3. Adjust the **Mix** slider (A → B) to control the blend ratio.
4. Enter a **name** and click **Save blend**.
5. The blend appears in the voice list with a `BLEND` badge.

Blends are persisted to `<Documents>/KokoroStudio/voice_blends.json`.

---

## 🎙 SSML-Lite Controls

Add markup to your text for finer control. Enable with the **Apply SSML** checkbox.

```xml
Normal text.
<break time="0.5s"/>
<emphasis>This is emphasized</emphasis> (spoken slightly slower).
<prosody rate="slow">This is slowed down.</prosody>
<prosody rate="1.5">This is sped up.</prosody>
```

Supported tags:
- `<break time="1.5s"/>` — pause (seconds or milliseconds)
- `<emphasis>` — spoken at 0.85× speed
- `<prosody rate="...">` — rate aliases: `x-slow`, `slow`, `medium`, `fast`, `x-fast`, or numeric 0.5-2.0

> **Note**: SSML is automatically disabled when multi-speaker dialogue mode is active.

---

## 🎚 Audio Post-Processing

Apply DSP effects to every generation. Click **🎚 Post-Process** in the toolbar.

| Effect | Default | Range |
|--------|---------|-------|
| **Trim silence** | On | Threshold: -60 dB, min silence: 10 ms |
| **Volume gain** | 0 dB | ±24 dB |
| **Fade in** | 0 ms | 0-5000 ms |
| **Fade out** | 50 ms | 0-5000 ms |
| **Normalize peak** | -1 dBFS | On/Off |
| **Normalize loudness** | Off (RMS -16 dB) | On/Off |

---

## 🎭 Emotion / Style Sliders

Modify the emotional quality of any voice:

| Slider | 0.0 | 0.5 (neutral) | 1.0 |
|--------|-----|---------------|-----|
| **Energy** | Calm, subdued | Natural | Bright, energetic |
| **Warmth** | Cool, distant | Natural | Warm, intimate |
| **Expressiveness** | Flat, monotone | Natural | Varied, dynamic |

**10 Presets**: Neutral, Warm & Calm, Bright & Energetic, Dark & Intense, Soft & Tender, Authoritative, Airy & Light, Deep & Resonant, Melancholic, Playful.

---

## 📚 Audiobook Chapter Builder

1. Open an EPUB or TXT file (drag-and-drop onto the editor or use Open).
2. Click **📚 Audiobook** in the toolbar.
3. Assign voices to each chapter (double-click the Voice column).
4. Set global speed, format, and output directory.
5. Choose export mode: **separate files** or **merged single file**.
6. Click **Generate Audiobook**.

Chapter files are auto-named as `001_Chapter_Title.wav`.

---

## 📦 Batch Generation

Queue multiple texts for sequential processing:

- **Add editor text** — queue the current editor content.
- **Add from file** — import a `.txt` file; blank-line paragraphs become individual items.
- **Add custom text** — paste text into an inline dialog.

Each item shows live status (⏳ → Generating → ✅ / ❌). A summary dialog reports success/fail/timing on completion.

---

## 💾 Project Management (.ksproj)

Save and restore your complete workspace:

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+N` | New project |
| `Ctrl+Shift+O` | Open project |
| `Ctrl+Shift+S` | Save project |

Project files capture: editor text, voice, speed, format, pronunciation/SSML/stream toggles, active profile, and post-processing parameters.

The window title shows `Project Name •` when there are unsaved changes.

---

## 💻 CLI Mode (Headless)

Process text files without opening the GUI:

```bash
kokoro-studio batch input.txt --voice af_heart --speed 1.0 --format wav --output-dir ./output
```

Options:
- `--voice / -v` — voice name (default: `af_heart`)
- `--speed / -s` — speed multiplier (0.1–3.0, default: `1.0`)
- `--format / -f` — output format (wav/mp3/flac/ogg, default: `wav`)
- `--output-dir / -o` — output directory (default: `Documents/KokoroStudio/`)
- `--prefix` — output filename prefix (default: `batch`)
- `--lang / -l` — language code (default: `a`)
- `--dry-run` — preview the item count without generating

Input is split by blank-line paragraphs; each paragraph becomes one audio file.

---

## 🌐 API Server Mode

Start a local REST API with OpenAI-compatible endpoints:

```bash
kokoro-studio serve
# or: kokoro-studio serve --port 8001 --host 0.0.0.0
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server status + version |
| `GET` | `/v1/models` | List available models |
| `GET` | `/v1/voices` | List all voices with metadata |
| `POST` | `/v1/audio/speech` | **OpenAI-compatible TTS** |
| `POST` | `/v1/audio/stream` | SSE streaming (base64 chunks) |
| `WS` | `/ws/stream` | Real-time WebSocket streaming |
| `GET` | `/docs` | Swagger UI |

### OpenAI-Compatible Request

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Hello world","voice":"alloy","response_format":"wav"}' \
  --output speech.wav
```

Voice aliases: `alloy` → `af_alloy`, `echo` → `am_echo`, `fable` → `bm_fable`, `nova` → `af_nova`, `onyx` → `am_onyx`, `shimmer` → `af_sky`. Direct Kokoro names also work.

### Python Client

```python
import requests
resp = requests.post("http://localhost:8000/v1/audio/speech", json={
    "input": "Hello from the API!",
    "voice": "af_heart",
    "response_format": "wav",
})
with open("speech.wav", "wb") as f:
    f.write(resp.content)
```

---

## 🖱️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+G` | Generate audio |
| `Ctrl+P` | Preview selected voice |
| `Ctrl+O` | Open document |
| `Ctrl+S` | Save editor text as `.txt` |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Space` | Play / Pause last audio |
| `Ctrl+Shift+N` | New project |
| `Ctrl+Shift+O` | Open project |
| `Ctrl+Shift+S` | Save project |

---

## 🌙☀️ Theme Toggle

Click the **🌙/☀️** button in the header to switch between dark and light themes. Your preference is saved via `QSettings` and persists across sessions.

---

## 🗂️ Project Structure

```
kokoro_studio/
├── __init__.py              # Package metadata
├── __main__.py              # `python -m kokoro_studio` entry point
├── engine.py                # Kokoro-82M wrapper, synthesis orchestrator
├── cli.py                   # CLI mode (batch + serve subcommands)
├── api_server.py            # FastAPI REST server (OpenAI-compatible)
├── audio_processing.py      # DSP effects (trim, volume, fade, normalize)
├── audiobook.py             # Chapter builder core logic
├── blending.py              # Voice blending dataclass + tensor ops
├── dialogue.py              # Multi-speaker marker parser
├── document_loader.py       # TXT / PDF / EPUB document parsers
├── emotional_style.py       # Style parameters + tensor interpolation
├── history.py               # SQLite-backed generation history
├── profiles.py              # Character profiles dataclass + persistence
├── project_manager.py       # .ksproj project file save/load
├── pronunciation.py         # Pronunciation dictionary
├── ssml.py                  # SSML-lite parser
├── streaming.py             # PCM ring buffer for real-time playback
└── gui/
    ├── __init__.py
    ├── app.py               # QApplication setup
    ├── main_window.py       # Main window (toolbar, controls, editor)
    ├── dialogs.py           # All feature dialogs (settings, blend, history,
    │                        #   pronunciation, batch, profiles, post-processing,
    │                        #   emotion/style, audiobook)
    ├── editor.py            # Custom editor with drag-drop
    ├── workers.py           # Synthesis worker (QThread)
    ├── batch_worker.py      # Batch queue worker (QThread)
    └── theme.py             # QSS stylesheets (dark + light)

tests/                       # 312+ unit tests
```

---

## 🧪 Development

### Run tests

```bash
pytest tests/ -v
```

### Editable install

```bash
pip install -e .
kokoro-studio serve   # start API server
kokoro-studio batch input.txt    # headless batch generation
```

---

## 📜 License

**Kokoro Studio Source-Available License v2.0**

- ✅ Personal, educational, **and commercial** use
- ✅ Modifications and redistribution
- ✅ If you use this project as a base or inspiration, **attribution is required**: include a link to the original project and mention it was used as a base or reference.
- ❌ Selling the original Software to the Licensor

See [`LICENSE`](./LICENSE) for the full text and [`DONATIONS.md`](./DONATIONS.md) for donation channels.

---

## ☕ Donations

Donations are appreciated and help sustain the project. Crypto addresses are in the Settings dialog (Support / Donate tab) and in [`DONATIONS.md`](./DONATIONS.md).

---

## 🙏 Acknowledgements

- The [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model by hexgrad and the Kokoro contributors.
- The [PySide6](https://wiki.qt.io/Qt_for_Python) team for Qt for Python.
- All the open-source libraries this project depends on.
