# 📖 Kokoro Studio — User Guide

> **Version:** 0.1.0 · **Engine:** Kokoro-82M

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Voice Selection](#voice-selection)
3. [Real-Time Streaming](#real-time-streaming)
4. [Multi-Format Export](#multi-format-export)
5. [Document Import](#document-import)
6. [Pronunciation Dictionary](#pronunciation-dictionary)
7. [SSML-Lite Controls](#ssml-lite-controls)
8. [Multi-Speaker Dialogue Mode](#multi-speaker-dialogue-mode)
9. [Voice Blending](#voice-blending)
10. [Character Profiles](#character-profiles)
11. [Audio Post-Processing](#audio-post-processing)
12. [Emotion / Style Sliders](#emotion--style-sliders)
13. [Generation History](#generation-history)
14. [Batch Generation Queue](#batch-generation-queue)
15. [Audiobook Chapter Builder](#audiobook-chapter-builder)
16. [Project Management](#project-management)
17. [Batch CLI Mode](#batch-cli-mode)
18. [API Server Mode](#api-server-mode)
19. [Theme Toggle](#theme-toggle)
20. [Keyboard Shortcuts](#keyboard-shortcuts)
21. [Settings & Info](#settings--info)

---

## Getting Started

### First Launch

When you open Kokoro Studio for the first time, the model downloads automatically (~300 MB). Subsequent launches are instant.

### Main Window Layout

```
┌──────────────────────────────────────────────────────────────┐
│  🎙 Kokoro Studio     [toolbar: 🎛 🎭 📚 🎚 ⚙ 🌙/☀️]     │
├────────────┬─────────────────────────────────────────────────┤
│            │  [text editor — type or drag-and-drop files]    │
│  VOICES    │                                                 │
│  LIST      │  [action row: Dict… ✓Apply rules  ✓SSML ✓Stream │
│            │   🎭 Dialogue  Preview  Generate]               │
│  [Preview] │                                                 │
│  [Blend]   │  [voice / speed / format controls]              │
│  [Profiles]│  [progress bar]  [status bar]                   │
├────────────┴─────────────────────────────────────────────────┤
│  🕒 History  📦 Batch  💾 Save project  📂 Open project     │
└──────────────────────────────────────────────────────────────┘
```

### Basic Workflow

1. **Select a voice** from the left panel.
2. **Type or paste text** into the editor.
3. **Choose output format** (WAV/MP3/FLAC/OGG).
4. **Click Generate** (or press `Ctrl+G`).
5. Audio streams automatically ~200 ms later. Use **Space** to pause/resume.
6. The generated file is saved to `Documents/KokoroStudio/`.

---

## Voice Selection

The left panel lists **29 built-in voices** sorted by grade and gender:

| Prefix | Language | Examples |
|--------|----------|---------|
| `af_` | American English, female | `af_heart`, `af_bella`, `af_alloy` |
| `am_` | American English, male | `am_adam`, `am_onyx`, `am_echo` |
| `bf_` | British English, female | `bf_isabella`, `bf_emma` |
| `bm_` | British English, male | `bm_fable`, `bm_george` |

### Previewing a Voice

Click **Preview selected voice** (or press `Ctrl+P`) to hear a short sample.

---

## Real-Time Streaming

By default, audio plays **as it generates** — no need to wait for full synthesis.

- The **▶ Stream** toggle in the action row enables/disables streaming.
- Streaming automatically disables in headless environments (no audio output device).
- The status bar shows real-time progress: `Generating · chunk 3 · 5.2s of audio so far · ~2s remaining`
- Click **■ Stop** to cancel an in-progress generation.

### How It Works

When streaming is ON:
1. Kokoro emits audio chunks as it processes text.
2. Chunks are pushed into a ring buffer.
3. `QAudioSink` pulls from the buffer and plays immediately.

When streaming is OFF (fallback):
1. Full synthesis completes first.
2. Audio is saved to disk.
3. `QMediaPlayer` plays the saved file.

---

## Multi-Format Export

Choose your output format from the dropdown in the controls panel:

| Format | Quality | Dependency |
|--------|---------|------------|
| **WAV** | 24 kHz, 16-bit PCM (native) | `soundfile` (always available) |
| **FLAC** | Lossless compressed | `soundfile` (always available) |
| **OGG** | Vorbis, lossy | `soundfile` (always available) |
| **MP3** | 192 kbps CBR | `lameenc` (pip install) |

If `lameenc` is not installed, the MP3 option shows an install hint.

---

## Document Import

Kokoro Studio supports three document formats:

| Format | How It Works |
|--------|-------------|
| **TXT** | Read as UTF-8, CRLF → LF normalized. Entire file = single document. |
| **PDF** | Extracted via `pypdf.PdfReader.extract_text()`. Each page is a chapter. |
| **EPUB** | Parsed via `ebooklib`. Each `ITEM_DOCUMENT` in the spine is a chapter. |

### How to Import

- **Open button** (`Ctrl+O`): browse for a file.
- **Drag and drop**: drag a `.txt`, `.pdf`, or `.epub` file onto the editor pane.
- Only single-file drops are accepted (multi-file drops show a status bar hint).

After import, the document's chapters are available in the **Audiobook Chapter Builder**.

---

## Pronunciation Dictionary

Override how words sound with custom substitutions. Click **📖 Dict…** in the action row.

### How It Works

- **Case-sensitive** by default: `"Kokoro"` won't match `"kokoro"`.
- **Whole-word matching**: `"heart"` won't match `"heartbeat"`.
- **Longest rule wins**: if you have rules for `"LA"` and `"Los Angeles"`, the longer match takes priority.
- **Empty replacement** = delete the word.

### Example

| Find | Replace | Effect |
|------|---------|--------|
| `Kokoro` | `Ko-ko-ro` | Fix pronunciation of the model name |
| `LA` | `Los Angeles` | Expand abbreviation |
| `thx` | `thanks` | Expand informal spelling |
| `um` | *(empty)* | Remove filler words |

### Rules Persistence

- Stored at `<Documents>/KokoroStudio/pronunciation.json`
- JSON schema versioned for forward compatibility.
- Legacy flat schema auto-migrates on load.
- Toggle rules on/off with the **✓ Apply rules** checkbox.

---

## SSML-Lite Controls

Add markup tags to your text for finer control over pauses, emphasis, and speed.

Enable with the **✓ Apply SSML** checkbox. An inline chip shows the summary
(e.g., `2 breaks · 1 emphasis · 1 prosody`).

### Supported Tags

#### `<break time="...">`

Inserts silence. Time can be in seconds (`1.5s`) or milliseconds (`500ms`).

```xml
Hello.<break time="1s"/>  <!-- 1 second pause -->
World.<break time="500ms"/>  <!-- half-second pause -->
```

#### `<emphasis>`

Wraps text spoken at a slightly slower speed (0.85×).

```xml
That is <emphasis>very important</emphasis>.
```

#### `<prosody rate="...">`

Changes speaking speed within a span. Supports:

- **Named rates**: `x-slow` (0.5×), `slow` (0.75×), `medium` (1.0×), `fast` (1.5×), `x-fast` (1.75×)
- **Numeric**: any value from 0.5 to 2.0

```xml
<prosody rate="slow">This is said slowly.</prosody>
<prosody rate="1.5">This is sped up 50%.</prosody>
```

### Limitations

- SSML is **automatically disabled** when multi-speaker dialogue mode is active (the chip turns amber).
- Unknown tags are preserved as literal text in the output.
- Nested tags (e.g., `<emphasis>` inside `<prosody>`) are flattened — the innermost tag wins.

---

## Multi-Speaker Dialogue Mode

Create natural-sounding dialogue with multiple voices — perfect for audiobooks, podcasts, and game dialogue.

### Syntax

Start a line with `[voice_name]:` — every line until the next marker is spoken in that voice:

```text
[af_heart]: Hello! My name is Heart. This is a multi-line
turn for Heart — it continues until the next marker.

[am_adam]:  And I'm Adam. Nice to meet you!
[af_heart]: Dialogue mode is pretty cool.
```

### Rules

- **One marker per line**, at the start (leading whitespace is OK).
- **Multi-line turns**: lines after a marker inherit the same voice until a new marker.
- **Pre-marker text**: lines before the first marker use the dropdown's default voice (great for narration + dialogue).
- **Unknown voices**: fall back to the default voice with a visible warning.
- **Blend voices**: use saved blend names as markers: `[my_custom_blend]:`.

### Gap Between Speakers

A 0.25-second silence is automatically inserted between speaker turns so the dialogue sounds natural rather than jump-cut.

### Auto-Detection

The editor detects markers automatically. An inline chip shows the count:
`🎭 3 speaker turn(s): af_heart, am_adam`

Click the **🎭 Dialogue** button to open the syntax reference, or **Insert sample script** to load a working example.

---

## Voice Blending

Create entirely new voices by blending any two built-in voices.

### How to Create a Blend

1. Click **🎛 Blend** in the toolbar.
2. Select **Voice A** and **Voice B** from the dropdowns.
3. Adjust the **Mix (A → B)** slider:
   - `0.00` = 100% Voice A, 0% Voice B
   - `0.50` = 50% each
   - `1.00` = 0% Voice A, 100% Voice B
4. Enter a **Name** (must match `[A-Za-z_][A-Za-z0-9_]*`).
5. Click **▶ Preview** to hear the blend.
6. Click **💾 Save blend**.

### Using Blends

- Saved blends appear in the voice list with a `BLEND` badge.
- The voice readout shows the composition: `🎻 name · 70% af_bella + 30% af_sarah`.
- Blends work in multi-speaker dialogue mode: `[my_blend]:`.
- Blends are persisted to `<Documents>/KokoroStudio/voice_blends.json`.

### Programmatic API

```python
from kokoro_studio.engine import generate_speech
from kokoro_studio.blending import VoiceBlend

blend = VoiceBlend(voice_a="af_bella", voice_b="af_sarah", alpha=0.3)
generate_speech(
    text="This is a blended voice.",
    voice_blend=blend,
    output_path="blended.wav",
)
```

---

## Character Profiles

Save voice + speed combinations as named, one-click presets.

### Built-in Profiles (9)

| Profile | Voice | Speed |
|---------|-------|-------|
| Narrator | `af_heart` | 1.00× |
| News Anchor | `am_adam` | 0.92× |
| Storyteller | `bf_isabella` | 0.85× |
| Professor | `am_michael` | 0.80× |
| Deep Voice | `am_onyx` | 1.00× |
| Whisper | `af_bella` | 0.70× |
| Energetic | `af_alloy` | 1.30× |
| British Narrator | `bm_george` | 1.00× |
| British Deep | `bm_fable` | 0.90× |

### Creating Custom Profiles

1. Set your desired voice and speed in the main window.
2. Click **🎭 Profiles** in the toolbar.
3. Click **💾 Save current as…** and enter a name.
4. The profile appears in the dropdown for one-click recall.

### Profile Features

- Built-in profiles are read-only and never overwritten.
- Profiles can include custom pronunciation rules.
- Profiles persist at `<Documents>/KokoroStudio/profiles.json`.
- A description field helps document what each profile is for.

---

## Audio Post-Processing

Apply DSP effects to every generation for polished, professional audio.

Open the dialog via **🎚 Post-Process** in the toolbar.

### Trim Silence

Removes leading and trailing silence from the generated audio.

- **Threshold**: -60 dB (default) — quieter than this is considered silence.
- **Min silence length**: 10 ms (default) — gaps shorter than this are kept.

### Volume Gain

Boost or cut the overall volume.

- **Range**: ±24 dB
- **0 dB** = no change (default).
- Positive values = louder, negative values = quieter.

### Fade In / Fade Out

Smoothly ramp audio up or down at the beginning/end.

- **Fade in**: 0–5000 ms (default: 0 = off).
- **Fade out**: 0–5000 ms (default: 50 ms = quick fade).

### Normalize

Set the loudest sample to a target level for consistent volume.

| Mode | Target | Description |
|------|--------|-------------|
| **Peak normalization** | -1 dBFS (default) | Sets the loudest sample to the target. Fast, reliable. |
| **Loudness normalization** | -16 dB (RMS) | Matches average perceived loudness. Better for consistent volume across files. |

### Processing Pipeline

Effects are applied in this order: **Trim → Volume → Fade → Normalize**

You can enable any subset. The `PostProcessingParams` dataclass captures all settings and can be saved/loaded in `.ksproj` project files.

---

## Emotion / Style Sliders

Modify the emotional quality of any voice through tensor interpolation.

Click **🎭 Style** in the toolbar to open the dialog.

### The Three Dimensions

| Slider | 0.0 | 0.5 (Neutral) | 1.0 |
|--------|-----|---------------|-----|
| **Energy** | Calm, subdued, laid-back | Natural voice cadence | Bright, energetic, lively |
| **Warmth** | Cool, distant, clinical | Natural voice timbre | Warm, intimate, rich |
| **Expressiveness** | Flat, monotone, even | Natural pitch variation | Varied, dynamic, animated |

### Presets

10 ready-to-use presets:

| Preset | Energy | Warmth | Expressiveness |
|--------|--------|--------|---------------|
| Neutral | 0.5 | 0.5 | 0.5 |
| Warm & Calm | 0.3 | 0.8 | 0.3 |
| Bright & Energetic | 0.9 | 0.5 | 0.7 |
| Dark & Intense | 0.8 | 0.2 | 0.6 |
| Soft & Tender | 0.2 | 0.8 | 0.2 |
| Authoritative | 0.7 | 0.3 | 0.4 |
| Airy & Light | 0.4 | 0.6 | 0.6 |
| Deep & Resonant | 0.6 | 0.2 | 0.3 |
| Melancholic | 0.3 | 0.4 | 0.4 |
| Playful | 0.9 | 0.7 | 0.9 |

### How It Works

The style system manipulates the voice's latent tensor before synthesis:
- **Energy** interpolates between the base voice and an energetic voice from the same group.
- **Warmth** interpolates between cool and warm voice tensors.
- **Expressiveness** adds scaled gaussian noise for subtle variation.

### Notes

- Style is **not applied** when voice blending is active (the two systems are independent).
- The toolbar button shows a **✦** indicator when a non-neutral style is active.

---

## Generation History

Every generation is automatically logged to a SQLite database.

### Accessing History

Click **🕒 History** to open the history panel. It shows the 50 most recent entries:

| Column | Description |
|--------|-------------|
| Time | Timestamp of generation |
| Voice | Voice name used |
| Speed | Speed multiplier |
| Duration | Audio duration |
| Format | Output format |
| Text snippet | First 80 characters of text |

### Actions

| Button | Action |
|--------|--------|
| **▶ Play** | Re-play the audio file |
| **📋 Load text** | Load the original text back into the editor |
| **💾 Re-export** | Save a copy of the audio to a new location |
| **🗑 Delete** | Remove the history entry (file is NOT deleted) |

---

## Batch Generation Queue

Process multiple texts sequentially — useful for generating a whole corpus at once.

### Adding Items

| Button | Behavior |
|--------|----------|
| **📝 Add editor text** | Queue the current editor content as one item |
| **📂 Add from file** | Import a `.txt` file; blank-line paragraphs become individual items |
| **✏️ Add custom text** | Open an inline dialog to type or paste text |

### Settings

Each item uses the current voice, speed, and format settings at the time it was added. You can override these per-batch in the batch dialog's settings row.

### Running a Batch

1. Add items to the queue (minimum 1).
2. Click **▶ Start batch**.
3. Each item shows its progress: `⏳ Queued → ⏳ Generating… → ✅ 3.2s` or `❌ error msg`.
4. When all items finish, a summary dialog shows success/fail counts and total time.
5. Click **■ Stop** to cancel mid-batch.

### Output

- Files are auto-named: `batch_001_voice_name.wav`, `batch_002_voice_name.wav`, etc.
- Output directory defaults to `Documents/KokoroStudio/`.
- Each item reuses all synthesis features: pronunciation rules, blends, SSML, and post-processing.

---

## Audiobook Chapter Builder

Turn EPUB and TXT documents into audiobooks with per-chapter voice assignments.

### Workflow

1. **Import a document**: Open an EPUB or TXT file via `Ctrl+O` or drag-and-drop.
2. **Open the Audiobook dialog**: Click **📚 Audiobook** in the toolbar.
3. **Assign voices**: Double-click the Voice column for any chapter to select a voice.
4. **Set defaults**: Choose a default voice, global speed, and output format.
5. **Choose output**: Select an output directory.
6. **Export type**:
   - **Separate files**: One audio file per chapter, named `001_Chapter_Title.wav`.
   - **Merged single file**: All chapters concatenated into one audio file.
7. **Click Generate Audiobook**.

### Features

- **Apply default voice to all** — set every chapter to the same voice instantly.
- **Per-chapter progress** — the table shows the status of each chapter during generation.
- **0.5 s cross-chapter silence** in merged output for natural chapter transitions.
- **Summary dialog** on completion showing file paths and durations.

---

## Project Management

Save and restore your complete workspace as `.ksproj` files.

### What's Saved

| Setting | Description |
|---------|-------------|
| Editor text | Current content of the text editor |
| Voice | Selected voice |
| Speed | Current speed multiplier |
| Format | Output format |
| Pronunciation rules | Dictionary rules + active toggle |
| SSML toggle | Apply SSML checkbox state |
| Stream toggle | Streaming checkbox state |
| Active profile | Selected character profile |
| Post-processing params | All PP dialog settings |

### Shortcuts

| Action | Shortcut |
|--------|----------|
| **New project** | `Ctrl+Shift+N` — clears the workspace (prompts to save if modified) |
| **Open project** | `Ctrl+Shift+O` — loads a `.ksproj` file |
| **Save project** | `Ctrl+Shift+S` — saves to the current file (or prompts for a new file) |

The window title shows `Project Name •` when there are unsaved changes.

---

## Batch CLI Mode

Process text files without opening the GUI — ideal for scripts and automation.

```bash
# Basic usage
kokoro-studio batch input.txt

# Full options
kokoro-studio batch input.txt \
    --voice af_heart \
    --speed 1.0 \
    --format wav \
    --output-dir ./output \
    --prefix my_audio \
    --lang a

# Dry-run (preview without generating)
kokoro-studio batch input.txt --dry-run
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--voice / -v` | `af_heart` | Voice name |
| `--speed / -s` | `1.0` | Speed multiplier (0.1–3.0) |
| `--format / -f` | `wav` | Output format (`wav`, `mp3`, `flac`, `ogg`) |
| `--output-dir / -o` | `Documents/KokoroStudio/` | Output directory |
| `--prefix` | `batch` | Output filename prefix |
| `--lang / -l` | `a` | Language code |
| `--dry-run` | — | Preview item count without generating |

### Input Format

The input file is split by **blank-line paragraphs**. Each paragraph becomes one audio file:

```text
First paragraph — this becomes batch_001.wav.

Second paragraph — this becomes batch_002.wav.

Third paragraph — this becomes batch_003.wav.
```

---

## API Server Mode

Start a local REST API with OpenAI-compatible endpoints and WebSocket streaming.

```bash
# Start with defaults (127.0.0.1:8000)
kokoro-studio serve

# Custom host and port
kokoro-studio serve --port 8001 --host 0.0.0.0

# Development mode (hot-reload)
kokoro-studio serve --reload
```

See [`API.md`](./API.md) for the complete API reference.

---

## Theme Toggle

Click the **🌙/☀️** button in the header to switch between dark and light themes.

- **Persistent**: your preference is saved via `QSettings` and remembered across sessions.
- **All dialogs** respect the current theme setting.
- The default theme is dark.

---

## Keyboard Shortcuts

| Shortcut | Action | Context |
|----------|--------|---------|
| `Ctrl+G` | Generate audio | Global |
| `Ctrl+P` | Preview selected voice | Global |
| `Ctrl+O` | Open document | Global |
| `Ctrl+S` | Save editor text as `.txt` | Global |
| `Ctrl+Z` | Undo | Editor |
| `Ctrl+Y` | Redo | Editor |
| `Space` | Play / Pause last audio | Editor (only when audio loaded) |
| `Ctrl+Shift+N` | New project | Global |
| `Ctrl+Shift+O` | Open project | Global |
| `Ctrl+Shift+S` | Save project | Global |

> **Note**: Space acts as a regular space character in the editor unless an audio file is loaded for playback.

---

## Settings & Info

Click the **⚙** gear button in the header to open the Settings dialog with four tabs:

### About Tab
- Version number and engine info.
- Links to the Kokoro-82M model and creator's GitHub.
- Technology credits.

### Shortcuts Tab
- Complete list of all keyboard shortcuts.
- Cross-platform notes (macOS uses Cmd instead of Ctrl).

### Support / Donate Tab
- BTC and ETH donation addresses with one-click copy buttons.
- Always double-check addresses against a trusted source.

### License Tab
- Summary of the Kokoro Studio Source-Available License v2.0.
- Links to the full `LICENSE` and `DONATIONS.md` files.
