# Kokoro Studio — Feature Roadmap

> **Goal:** Evolve Kokoro Studio into a competitive local alternative to ElevenLabs.
> **Unique Value Proposition:** FREE · OFFLINE · PRIVATE · FAST · NO CREDITS

---

## Progress Legend

- `[ ]` = Not started
- `[~]` = In progress
- `[x]` = Completed
- `[-]` = Skipped / Deferred

---

## Phase 1: Quick Wins — Remove Workflow Friction

> Low complexity, high immediate impact. Focus on removing everyday friction.

### Features

- [x] **Multi-format Export** ✅ *shipped*
  - WAV / FLAC / OGG via `soundfile`; MP3 via `lameenc` (pure-Python, no FFmpeg)
  - Format dropdown in the controls panel (`_format_combo`)
  - `generate_speech(..., output_format=...)` (last parameter, default `None` → auto-detect from extension — preserves positional backwards-compat)
  - Worker threads stay free of Qt widget access; `ImportError` for missing `lameenc` surfaces with a context-aware install hint (`pip install lameenc`)
  _Complexity: Low_

- [x] **Document Import (TXT, PDF, EPUB)** ✅ *shipped*
  - TXT via binary read + UTF-8 (`errors='replace'`) with CRLF → LF normalisation
  - PDF via `pypdf.PdfReader.extract_text()` with per-page try/except
  - EPUB via `ebooklib.book.spine` + `BeautifulSoup(.., 'html.parser')`
  - Open… button + drag-and-drop on the editor pane (`DocumentDropEditor`)
  - Multi-file drops explicitly refused with a status-bar hint (no silent swallow)
  - New module `document_loader.py` exposes `Document` dataclass with
    `title / chapters / full_text / author / language / source_path / skipped`
    so Phase 4's Audiobook Builder can reuse it without re-parsing.
  _Complexity: Low_

- [x] **Pronunciation Dictionary** ✅ *shipped*
  - New module `pronunciation.py` (pure-Python, lazy-imported): load / save / `apply_substitutions`
  - Whole-word, case-sensitive, longest-rule-first substitution (single-pass regex; Unicode-aware `\b`)
  - JSON schema: versioned (`"version": 1`) wrapper around `rules: [{find, replace}]` for forward compat; automatic legacy flat-schema migration
  - File persisted at `Documents/KokoroStudio/pronunciation.json`
  - GUI: `Apply rules` checkbox + `📖 Dict…` button + rules-count label in the action row
  - Modal editor dialog (`QTableWidget` + Add/Remove/Save/Cancel) with duplicate-key warning
  - Flow: `generate_speech(..., pronunciation_rules=...)` kwarg (added last to preserve positional compat), threaded through `SynthesisWorker`
  _Complexity: Low_

- [x] **Keyboard Shortcuts** ✅ *shipped*
  - Ctrl+G → Generate; Ctrl+P → Preview voice
  - Ctrl+O → Open document; Ctrl+S → Save editor text as `.txt`
  - Ctrl+Z / Ctrl+Y → Undo / Redo in editor
  - Space → Play/Pause last audio (only when a generated audio file is loaded; otherwise Space types normally)
  - Implemented as window-level `QAction`s with `Qt.WindowShortcut` context (per the QAction vs QShortcut research note below)
  - `QKeySequence.StandardKey` for Open / Save / Undo / Redo so the same physical keys work cross-platform (Cmd on macOS, Ctrl on Win/Linux)
  - Space is routed through `installEventFilter` on the editor instead of a QAction shortcut — this avoids the `Qt.WindowShortcut` Space-stealing gotcha so the editor still inserts spaces when no audio is loaded
  - Undo/Redo enabled state mirrors the editor's `undoAvailable` / `redoAvailable` signals → no manual refresh needed after every keystroke
  - _Complexity: Low_

- [x] **Settings & Info Dialog** ✅ *shipped* (bonus UX)
  - ⚙ gear button in the header opens a modal `SettingsDialog` with 4 tabs: About, Shortcuts, Support / Donate, License
  - About tab: app name + version, Kokoro-82M credit by hexgrad, and a hyperlink to the creator's GitHub (MattiaAlessi)
  - Shortcuts tab: all 7 keyboard shortcuts rendered in a monospace `QTableWidget` (mirrors tooltips + PLAN's keyboard reference, always-visible as a cheat-sheet)
  - Support / Donate tab: BTC + ETH donation addresses as read-only monospace `QLineEdit`s, each with a `Copy` button that flashes "Copied!" for 1.4 s via `QTimer.singleShot`
  - License tab: short summary of the source-available license + pointers to `LICENSE` and `DONATIONS.md`
  - Addresses stored as `_DONATE_BTC` / `_DONATE_ETH` class constants so a single grep finds them — kept in sync with `DONATIONS.md` per release
  - Dark QSS for the dialog is **scoped** (applied via `dialog.setStyleSheet(SETTINGS_QSS)`) so the rest of the app's main-window theme stays untouched
  - _Complexity: Low_

- [x] **Estimated Generation Time** ✅ *shipped*
  - Status bar during synthesis now reads `Generating · chunk N · X.YYs of audio so far · ~Z remaining`
  - The 4th arg of the `SynthesisWorker.progress` signal carries a best-effort ETA in wall-clock seconds; `-1.0` while we're still warming up
  - ETA strategy: rate = `cumulative_audio_seconds / elapsed_wallclock` (calmed by a ≥0.5 s + ≥2 chunks warmup gate), then `remaining_audio / rate`, where `remaining_audio ≈ text_chars / _EMPIRICAL_CHARS_PER_AUDIO_SEC - cumulative_audio`
  - `_EMPIRICAL_CHARS_PER_AUDIO_SEC = 13.0` matches ~150 wpm English narration; tune for non-English / atypical pacing without code edits
  - Class-level constants `_ETA_MIN_WARMUP_S` and `_ETA_MIN_CHUNKS` gate noisy first-chunk rate estimates
  - _Complexity: Low_

### Research Tasks

- [x] Research `pydub` MP3 export on Windows — does it need FFmpeg installed separately?
  > **Answer:** Yes, pydub requires FFmpeg for MP3 — it has no native compressed-format support.
  > Alternative: use `lameenc` for pure-Python MP3 encoding (no FFmpeg dependency).
  > Can also call `ffmpeg` directly via `subprocess` for better performance.
  > If using pydub, set path explicitly: `AudioSegment.converter = r"C:\\ffmpeg\\bin\\ffmpeg.exe"`
- [x] Research `PyPDF2` vs `pypdf` (newer fork) — which is more maintained?
  > **Answer:** PyPDF2 is **deprecated** — merged into `pypdf`. For new projects use `pypdf` (pure Python, lightweight).
  > For best structure preservation (paragraphs, reading order), use **`PyMuPDF`** (imported as `fitz`) — 10-50x faster, supports blocks/spans/fonts.
  > For AI-ready Markdown output: `pymupdf4llm.to_markdown("file.pdf")`.
  > **Decision:** Use `pypdf` for simplicity (pure Python, no C deps). Fall back to PyMuPDF if extraction quality is poor.
- [x] Research `ebooklib` EPUB parsing — does it handle chapters cleanly?
  > **Answer:** ebooklib does NOT have built-in plain-text extraction. Workflow:
  > 1. Iterate `book.get_items()`, filter for `ITEM_DOCUMENT` (type 9)
  > 2. Get raw XHTML via `item.get_body_content().decode('utf-8')`
  > 3. Strip HTML with `BeautifulSoup(body, 'html.parser').get_text()`
  > Use `book.spine` to maintain correct chapter order.
  > Known issues: fails on broken links in manifest; all items loaded into memory.
  > Alternatives: `epub2txt` (simpler), `pandoc` (most robust CLI).
- [x] Research Qt keyboard shortcut best practices (QAction vs QShortcut)
  > **Answer:** Use **`QAction`** for all user-facing commands (auto-syncs with menus/toolbar/tooltips).
  > Use `Qt.WindowShortcut` context so shortcuts work regardless of focused widget.
  > Use `QKeySequence.StandardKey` (e.g., `StandardKey.Save`) for cross-platform compat (Cmd on macOS).
  > Avoid mixing QAction + QShortcut for same key (causes ambiguity).
  > Gotcha: QAction objects must be added to a widget via `addWidget()` or `insertAction()` to receive events.

### Technical Notes

```
# Multi-format export approach:
# - WAV:  soundfile.write(path, audio, SAMPLE_RATE)  — already in kokoro_TTS.py
# - FLAC: soundfile.write(path, audio, SAMPLE_RATE, format='FLAC')  — native
# - OGG:  soundfile.write(path, audio, SAMPLE_RATE, format='OGG', subtype='VORBIS')  — native
# - MP3:  Two options (in order of preference):
#   Option A: lameenc (pure Python, no FFmpeg dep)
#     import lameenc
#     encoder = lameenc.Encoder()
#     encoder.set_bit_rate(192)
#     encoder.set_in_sample_rate(SAMPLE_RATE)
#     encoder.set_channels(1)
#     mp3_data = encoder.encode(audio_int16.tobytes()) + encoder.flush()
#     open(path, 'wb').write(mp3_data)
#   Option B: pydub + FFmpeg (heavier, but well-known)
#     from pydub import AudioSegment
#     seg = AudioSegment(audio_int16.tobytes(), frame_rate=24000, sample_width=2, channels=1)
#     seg.export(path, format='mp3', bitrate='192k')
#   Option C: subprocess call to ffmpeg directly (most control)
#     subprocess.run(['ffmpeg', '-y', '-f', 'f32le', '-ar', '24000', '-ac', '1',
#                     '-i', 'pipe:0', '-b:a', '192k', path], input=audio.tobytes())
#
# PDF text extraction:
#   from pypdf import PdfReader
#   reader = PdfReader('file.pdf')
#   text = '\n\n'.join(page.extract_text() or '' for page in reader.pages)
#
# EPUB text extraction:
#   from ebooklib import epub
#   from bs4 import BeautifulSoup
#   book = epub.read_epub('file.epub')
#   for item in book.get_items():
#       if item.get_type() == 9:  # ITEM_DOCUMENT
#           body = item.get_body_content().decode('utf-8')
#           text = BeautifulSoup(body, 'html.parser').get_text()
#
# Keyboard shortcuts:
#   Use QAction with QKeySequence.StandardKey where possible.
#   Set context to Qt.WindowShortcut for window-wide activation.
#   Example:
#     action = QAction('Generate', self)
#     action.setShortcut(QKeySequence('Ctrl+G'))
#     action.triggered.connect(self._on_generate_clicked)
#     self.addAction(action)
```

### Dependencies to Install

```
pip install pypdf ebooklib beautifulsoup4 lameenc
# FFmpeg NOT required if using lameenc for MP3
# If using pydub instead: FFmpeg must be on PATH
```

---

## Phase 2: Core TTS Advancements — The "ElevenLabs Feel"

> Medium complexity, highest differentiating impact. These features make Kokoro Studio feel like a premium product.

### Features

- [x] **Real-Time Streaming Playback** 🔥 ✅ *shipped*
  - Play audio *as it generates* — no waiting for full synthesis
  - Custom `QIODevice` subclass (`StreamingPcmDevice`) backed by a thread-safe
    `PcmRingBuffer`; the buffer is split into pure-Python core so the
    semantics (underrun → silence, EOS → empty bytes) are unit-testable
    without PySide6
  - `QAudioSink` pulls from the device in push mode; synthesis worker
    pushes chunks through the ring buffer on a Qt signal
  - Streaming toggle in the GUI ("▶ Stream", default ON); auto-disables
    when the platform reports no audio output device (headless CI / RDP)
  - Critical GC safety: `_audio_sink`, `_streaming_device`, `_ring_buffer`
    kept as long-lived `KokoroStudioMain` members so PySide6 GC can't
    segfault the C++ audio thread mid-playback
  - File-based fallback (`QMediaPlayer`) is preserved for users who want
    the older "wait for full synthesis" flow
  - Status bar shows real-time progress while the QAudioSink drains
    naturally into IdleState after EOS
  - _Complexity: Medium-High_

- [x] **Multi-Speaker Dialogue Mode** 🎭 ✅ *shipped*
  - Parse `[voice_name]:` syntax (one marker per line, line-start only)
  - Auto-detect in editor: any marker triggers the dialogue engine path via
    inline `🎭 N speakers · summary` chip + `?` help button (syntax modal)
  - Each `KPipeline` call gets its own voice (Kokoro bakes the style vector
    into the forward pass — voice swaps mid-call are NOT possible in v0.9);
    audio concatenated with configurable cross-segment silence default 0.25 s
  - Per-segment streaming: chunks flow through the existing ring buffer in
    order; silence gap emitted as a synthetic chunk with `chunk_idx = -1`
    so the real-time playback plays a natural pause
  - Pronunciation dictionary applied per-segment in the multi-speaker path
  - 26 new tests in `tests/test_dialogue.py` cover parser semantics, line
    continuation, unknown-voice fallback, CRLF, whitespace, edge cases
  - Empty-markers-only scripts surface a friendly QMessageBox instead of
    routing a doomed job to the engine
  - SynthesisWorker uses a cumulative chunk counter so the status bar
    resets only at the start of a fresh job, not at every speaker change
  _Complexity: Medium_

- [x] **Voice Blending / Mixing** 🎻 ✅ *shipped*
  - New `kokoro_studio.blending` module: `VoiceBlend` frozen dataclass with
    alpha bounds enforcement, versioned JSON persistence at
    `<Documents>/KokoroStudio/voice_blends.json` (legacy flat schema
    auto-migrates), `compute_blend_tensor` with rounded-alpha cache,
    `resolve_voice_param`, `is_valid_blend_name` (shared regex with the
    dialogue-marker tokens so blend names are accepted in `[my_blend]:` markers)
  - Engine integration: `generate_speech(voice_blend=..., blends=...)` kwargs,
    per-segment blend resolution in `_generate_dialogue_segments`, lazy
    disk-load of `voice_blends.json` via `_ensure_blends_loaded`
  - GUI: inline "CREATE BLEND" frame (Voice A / Voice B dropdowns + alpha
    slider + spin + name + Save / Preview buttons), saved blends appear in
    the voice list with a `BLEND` badge, voice readout renders blend
    composition (`🎻 name · 70% af_bella + 30% af_sarah`), multi-speaker
    dialogue parser widens `known_voices` with blend names
  - `SynthesisWorker` snapshots `blends=` at construction time and passes
    it to the engine on the worker thread
  - Preview re-entrancy guard prevents Generate clicks from racing the
    synchronous preview `generate_speech` call
  - 61 unit tests in `tests/test_blending.py` cover dataclass validation,
    schema migration, name validation, tensor caching, round-trip
    save/load, and reserved-name collision
  - _Complexity: Medium-High_

- [x] **SSML-lite Controls** 🎙 ✅ *shipped*
  - New `kokoro_studio.ssml` module: `SSMLSegment` frozen dataclass
    with `kind` ∈ {'text','break','emphasis','prosody'} + 4 classmethod
    factories + `parse_ssml` (lenient regex parser, no external deps),
    `detect_ssml` (cheap pre-check), `summarize_ssml` (chip-text
    formatter). Whitespace-only segments are dropped; unknown tags are
    preserved as raw text so typos surface as literal characters in stderr.
  - Engine integration: `generate_speech(apply_ssml: bool = False, ...)`
    opt-in kwarg routes through `_generate_ssml_segments` whenever the
    text contains SSML-lite markup AND multi-speaker is OFF.
    Per-segment synthesis handles `<break time="..."/>` silence via
    `np.zeros(duration_s * SAMPLE_RATE)` (length 1 ms – 60 s validated
    by the parser) and `<prosody rate="...">` per-segment speed scaling
    (numeric 0.5..2.0 + token aliases x-slow/slow/medium/fast/x-fast,
    all clamped to engine's `[SPEED_MIN, SPEED_MAX]` safe band before
    `pipeline(text, voice=..., speed=effective)` is called). `<emphasis>`
    is a fixed 0.85× rate.
  - Multi-speaker mode takes precedence when both are set; the engine
    silently drops SSML and the GUI chip turns amber (`#F59E0B`) with
    "(ignored in dialogue mode)" so the user knows their tags are inert.
  - 56 unit tests in `tests/test_ssml.py` cover dataclass factories,
    whitespace-dropping, unknown-tag preservation, rate-token aliases
    (numeric + named), `detect_ssml` fast-path, unicode round-trip
    (`c\u00e9f\u00e9 na\u00eefvely`), back-to-back breaks, `parse_ssml(None)`
    graceful handling, and the speed-mult clamp invariants.
  - GUI: "Apply SSML" checkbox on the controls panel (default OFF for
    backward-compat) + inline emerald SSML chip (`#10B981` on dark
    surfaces) that updates on every keystroke AND on checkbox toggle,
    paired with a `?` help-button modal containing the `SSML_HELP_SAMPLE`
    syntax cheatsheet. `SynthesisWorker` snapshots `apply_ssml` at
    `.start()` time so a mid-run checkbox flip never changes what gets run.
  - _Complexity: Medium_

### Research Tasks

- [x] Research PySide6 `QAudioSink` / `QAudioOutput` for real-time PCM streaming (push mode)
  > **Answer:** Use `QAudioSink(format).start(my_qio_device)` where
  > `my_qio_device` is a sequential `QIODevice` subclass with
  > `readData(maxlen)` returning PCM bytes from a thread-safe ring buffer.
  > `QAudioSink.start()` does NOT take ownership of the QIODevice; keep a
  > strong Python reference on the main window or the C++ audio thread
  > segfaults when GC collects it mid-playback. On underrun (empty
  > buffer), return `silence_bytes = b'\x00' * maxlen` — NOT empty bytes
  > — because `b''` is the EOF signal and would prematurely end
  > playback. Only return `b''` once `eos=True`.
- [ ] Research StyleTTS 2 style vector access from the `kokoro` Python library — can we get/set style tensors?
- [x] Research `kokoro` pipeline internals — how to swap voices mid-generation for multi-speaker
  > **Answer:** Not possible. Kokoro-82M bakes the voice style vector into
  > the model's forward pass, so a single `KPipeline(...)` call can only
  > produce audio in ONE voice. To get multi-speaker audio we segment the
  > script at the orchestrator level (one `pipeline(text, voice=X)` call
  > per segment) and concatenate the resulting audio arrays. Implemented
  > in `kokoro_studio.engine._generate_dialogue_segments`. Cross-segment
  > silence is fed through the same `on_chunk` callback as a synthetic
  > chunk with `chunk_idx = dialogue.CHUNK_IDX_GAP` so the streaming
  > ring buffer plays the natural pause.
- [ ] Research SSML tag parsing libraries (e.g. `ssml-parser` or custom regex)
- [ ] Investigate whether Kokoro's `KPipeline` exposes phoneme-level timing for better streaming sync

### Technical Notes

```
# Streaming playback approach:
# 1. QAudioSink(QAudioFormat) with PCM format matching Kokoro (24kHz, float32, mono)
# 2. on_chunk callback writes to a QIODevice (QBuffer or custom)
# 3. QAudioSink auto-plays from the buffer as data arrives
# Key: must handle buffer underrun gracefully (silence, not crash)

# Voice blending approach:
# 1. Load two voice tensors (numpy arrays from kokoro voice pack)
# 2. blended = alpha * voice_a + (1 - alpha) * voice_b
# 3. Pass blended tensor as the `voice` parameter to pipeline()
```

---

## Phase 3: Professional Workflow — Power User Features

> Medium complexity, retention-focused. These features make Kokoro Studio a daily-driver tool.

### Features

- [x] **Generation History** ✅ *shipped*
  - SQLite-backed log of every generation (built-in `sqlite3`, no extra deps)
  - Stores: text, voice, speed, timestamp, output path, duration, format
  - Instant re-play and re-export without re-generating
  - Searchable/filterable history panel with 50-entry default limit
  - 25 unit tests in `tests/test_history.py`
  - _Complexity: Medium_

- [x] **Batch Generation Queue** ✅ *shipped*
  - Queue multiple text blocks or import a list of texts (.txt paragraphs)
  - Background `BatchWorker` processes sequentially with per-item progress signals
  - Each item gets its own output file with auto-naming
  - Summary report dialog when batch completes (success/fail/timing)
  - Reuses all synthesis features: pronunciation, blends, SSML, post-processing
  - _Complexity: Medium_

- [x] **Character Profiles** ✅ *shipped*
  - Save named presets: voice + speed + optional pronunciation rules + description
  - One-click recall from a dropdown in the controls panel
  - 9 built-in presets: Narrator, News Anchor, Storyteller, Professor, Deep Voice, Whisper, Energetic, British Narrator, British Deep
  - JSON persistence at `<Documents>/KokoroStudio/profiles.json` (versioned schema)
  - Full `ProfilesDialog` with table view, save-from-current, delete
  - Built-in profiles are read-only and never shadowed by user data
  - 30+ unit tests in `tests/test_profiles.py`
  - _Complexity: Medium_

- [x] **Audio Post-Processing** 🎚 ✅ *shipped*
  - Pure-DSP module `kokoro_studio.audio_processing` (zero Qt deps, pure numpy)
  - `PostProcessingParams` frozen dataclass with validation
  - `trim_silence()` — leading/trailing silence removal with configurable threshold & min-silence length
  - `apply_volume()` — fixed gain boost/cut (±24 dB range)
  - `fade_in()` / `fade_out()` — linear ramps (controllable duration)
  - `normalize_peak()` — set the loudest sample to a target dBFS (default -1 dBFS)
  - `normalize_loudness()` — RMS-based loudness normalisation (default -16 dBFS)
  - `apply_all()` — pipeline: trim → volume → fade → normalise
  - Applied inside `generate_speech` before `save_audio` in ALL three paths (single, dialogue, SSML)
  - Threaded through `SynthesisWorker` into the main GUI flow
  - Also wired into `BatchWorker` for batch queue items
  - Full `PostProcessingDialog` with descriptive labels, tooltips, and real-world value examples
  - 53 unit tests in `tests/test_audio_processing.py`
  - _Complexity: Medium_

- ~~**Waveform Visualization**~~ **removed**
  - Caused `STATUS_FATAL_APP_EXIT` (0xC0000409) in Qt FFmpeg backend
  - `kokoro_studio/gui/waveform.py` deleted
  - All `self._waveform.*` calls stripped from `main_window.py`
  - Playback toggle reverts to simple `stop(); setSource(); play()`
  - _Complexity: N/A_

### Research Tasks

- [x] Research SQLite vs JSON for generation history — tradeoffs for this use case
- [x] Research `pyqtgraph` vs `QGraphicsView` for waveform rendering in PySide6
  > **Decision:** Neither. Pure `QPainter` with pre-downsampled numpy array is faster and lighter for a simple waveform overview.
  > No extra dependencies needed.
- [x] Research audio normalization algorithms (peak vs LUFS)
  > **Decision:** Use simple peak normalisation (default, fast) and RMS-based loudness normalisation
  > as a toggle option.  Full ITU-R BS.1770-4 LUFS would add a `pyloudnorm` dependency;
  > RMS is sufficient for the uniform dynamic range of TTS speech output.
- [ ] Research `scipy.signal` functions useful for audio post-processing
- [ ] Research Qt threading best practices for batch queue management

### Dependencies to Install

```
pip install scipy
# Optional: pip install pyqtgraph  (for waveform viz)
```

---

## Phase 4: Premium & Platform Features

> Higher complexity, long-term differentiation. These make Kokoro Studio a platform, not just a tool.

### Features

- [x] **Project Management** ✅ *shipped*
  - New module `kokoro_studio/project_manager.py` (zero Qt deps)
  - `ProjectData` frozen dataclass — captures editor text, voice, speed, format,
    pronunciation/SSML/stream toggles, active profile, post-processing params
  - `PostProcessingSnapshot` frozen dataclass for serialising PP params
  - JSON `.ksproj` format with version field for forward-compat schema migration
  - `save_project(path, data)` / `load_project(path)` public API
  - 3 project buttons in toolbar: 📄 New Project, 📂 Open Project, 💾 Save Project
  - Window title + inline `_project_indicator` show project name and • dirty flag
  - `_mark_project_modified()` tracks unsaved changes through all state mutators
  - `_prompt_save_if_modified()` — Save / Discard / Cancel dialog on close/open/new
  - `_load_project_from_file()` with full `blockSignals` guard during state restore
  - Round-trip unit test passes: JSON ↔ dataclass
  - _Complexity: High_

- [x] **Audiobook Chapter Builder** 📚 ✅ *shipped*
  - New module `kokoro_studio/audiobook.py` (zero Qt deps): `ChapterInfo`,
    `AudiobookProject`, `generate_audiobook()`, `merge_audio_segments()`
  - Reads `Document.chapters` from existing `document_loader.py` (EPUB
    per-ITEM_DOCUMENT split, TXT single-chapter)
  - Per-chapter voice assignment via combo in the table (double-click to open)
  - "Apply default voice to all" button for bulk voice assignment
  - Global speed, format, output directory controls
  - Export options: ✓ separate chapter-per-file ✓ merged single file
  - Background `QThread` generation with per-chapter progress bar + table status
  - Summary dialog on completion showing files created
  - GUI: `AudiobookDialog` in `dialogs.py` + 📚 button in toolbar
  - 0.5 s configurable cross-chapter silence gap in merged output
  - Files auto-named as `001_Chapter_Title.wav` etc.
  - _Complexity: High_

- [x] **Emotion / Style Sliders** ✅ *shipped*
  - New `kokoro_studio/emotional_style.py` module: `StyleParameters` dataclass,
    `compute_style_tensor()` for tensor interpolation + noise perturbation,
    10 named presets, `summarize_style()` helper
  - 3 sliders: Energy (calm→energetic), Warmth (cool→warm), Expressiveness (flat→varied)
  - Each slider 0.0–1.0 range, 0.5 = neutral (no modification)
  - `voice_style` kwarg integrated into `generate_speech()`, threaded through
    single-speaker, SSML, and multi-speaker dialogue paths
  - `SynthesisWorker` passes style to engine via `voice_style` param
  - GUI: `EmotionStyleDialog` in `dialogs.py` with sliders + preset dropdown +
    reset button + live summary; 🎭 Style toolbar button with ✦ active indicator
  - Zero PySide6 deps in the core module; lazy imports throughout engine + GUI
  - 276 existing tests pass (no regressions)
  - _Complexity: High_

- [x] **API / CLI Server Mode** ✅ *shipped*
  - New `kokoro_studio/api_server.py` module (zero Qt deps)
  - FastAPI app with CORS and lifespan-based pipeline warm-up
  - `GET /health` — server health + version info
  - `GET /v1/models` — list available models (OpenAI-compatible)
  - `GET /v1/voices` — list all voices with metadata
  - `POST /v1/audio/speech` — OpenAI-compatible TTS: accepts `model`,
    `input` (max 4096 chars), `voice` (OpenAI-style + direct Kokoro names),
    `response_format` (wav/mp3/flac/ogg/pcm), `speed` (0.25–4.0);
    returns binary audio with correct Content-Type
  - `POST /v1/audio/stream` — SSE streaming with base64-encoded chunk events
  - `WebSocket /ws/stream` — real-time streaming: JSON request →
    binary PCM chunks + final WAV + `[DONE]` signal
  - CLI: `kokoro-studio serve --port 8000 --host 127.0.0.1`
  - Dependencies: fastapi, uvicorn, python-multipart, sse-starlette
    (optional: `pip install -e '.[server]'`)
  - Swagger docs at `http://localhost:8000/docs`
  - _Complexity: High_

- [x] **Light / Dark Theme Toggle** ✅ *shipped*
  - `QSS_DARK` (was `QSS`) + new `QSS_LIGHT` and `SETTINGS_QSS_DARK`/`SETTINGS_QSS_LIGHT` in `theme.py`
  - `get_qss(mode)` and `get_settings_qss(mode)` helpers
  - 🌙/☀️ toggle button in header, switches theme on click
  - Preference persisted via `QSettings("Kokoro Studio", "Kokoro Studio")`
  - All dialogs use `_resolve_settings_qss()` to read theme from QSettings
  - _Complexity: Low_

- [x] **API / CLI Server Mode** ✅ *shipped*
  - New `kokoro_studio/api_server.py` module (zero Qt deps)
  - FastAPI app with CORS and lifespan-based pipeline warm-up
  - `GET /health` — server health + version info
  - `GET /v1/models` — list available models (OpenAI-compatible)
  - `GET /v1/voices` — list all voices with metadata
  - `POST /v1/audio/speech` — OpenAI-compatible TTS: accepts `model`,
    `input` (max 4096 chars), `voice` (OpenAI-style + direct Kokoro names),
    `response_format` (wav/mp3/flac/ogg/pcm), `speed` (0.25–4.0);
    returns binary audio with correct Content-Type
  - `POST /v1/audio/stream` — SSE streaming with base64-encoded chunk events
  - `WebSocket /ws/stream` — real-time streaming: JSON request →
    binary PCM chunks + final WAV + `[DONE]` signal
  - CLI: `kokoro-studio serve --port 8000 --host 127.0.0.1`
  - Dependencies: fastapi, uvicorn, python-multipart, sse-starlette
    (optional: `pip install -e '.[server]'`)
  - Swagger docs at `http://localhost:8000/docs`
  - _Complexity: High_

- [x] **Batch CLI Mode** ✅ *shipped*
  - `kokoro-studio batch <input_file> [options]` — headless CLI batch generation
  - New module `kokoro_studio/cli.py` with argparse: `--voice/-v`, `--speed/-s`, `--format/-f`, `--output-dir/-o`, `--prefix`, `--lang`, `--dry-run`
  - Splits input .txt file by blank-line paragraphs, generates one audio file per paragraph
  - Lazy imports `blending` only for blend-name validation (so `scipy` stays optional)
  - `__main__.py` dispatches to CLI or GUI based on first argument
  - Zero Qt dependency in the CLI path — works headless
  - _Complexity: Medium_

### Research Tasks

- [ ] Research StyleTTS 2 style vector dimensions and how to manipulate them
- [ ] Research OpenAI TTS API format for compatibility layer
- [ ] Research M4B audiobook format and how to create it programmatically
- [ ] Research `FastAPI` + WebSocket streaming for TTS API
- [ ] Research QSettings persistence patterns in PySide6
- [ ] Research EPUB chapter parsing — reliable methods for chapter boundary detection

### Dependencies to Install

```
pip install fastapi uvicorn
# For M4B: pip install mutagen  (metadata) + FFmpeg
```

---

## Dependency Graph

```
Phase 1 (Quick Wins) — No inter-dependencies, can be done in any order
  │
  ├── Multi-format Export
  ├── Document Import
  ├── Pronunciation Dictionary
  ├── Keyboard Shortcuts
  └── Est. Generation Time
          │
Phase 2 (Core TTS) — Streaming is independent; Dialogue & Blending are independent
  │
  ├── Real-Time Streaming ◄── uses existing on_chunk callback
  ├── Multi-Speaker Dialogue ◄── needs voice-switching logic
  ├── Voice Blending ◄── needs StyleTTS2 tensor access
  └── SSML-lite ◄── needs text preprocessor (can use Pronunciation Dict infra)
          │
Phase 3 (Workflow) — History first, then features that use it
  │
  ├── Generation History ◄── needs SQLite/JSON store (do first)
  ├── Batch Queue ◄── extends SynthesisWorker
  ├── Character Profiles ◄── benefits from Voice Blending (Phase 2)
  ├── Audio Post-Processing ◄── numpy/scipy DSP
  └── Waveform Visualization ◄── needs audio ndarray (independent)
          │
Phase 4 (Platform) — Most features depend on earlier phases
  │
  ├── Project Management ◄── depends on History + Profiles
  ├── Audiobook Builder ◄── depends on Batch + Document Import + Multi-Speaker
  ├── Emotion Sliders ◄── depends on Voice Blending
  ├── Light/Dark Theme ◄── independent (Low complexity)
  ├── API/CLI Server ◄── depends on core engine being mature
  └── Batch CLI ◄── depends on Batch Queue logic
```

---

## Competitive Analysis Reference

| Feature | ElevenLabs | Kokoro Studio (Current) | Kokoro Studio (After Roadmap) |
|---|---|---|---|
| **Cost** | $5-330/mo | ✅ Free | ✅ Free |
| **Privacy** | Cloud | ✅ Offline | ✅ Offline |
| **Voice Count** | 1000s | 29 presets | 29 presets + ∞ blends |
| **Voice Cloning** | ✅ Zero-shot | ❌ | ⚡ Via blending (pseudo) |
| **Emotion Control** | ✅ Advanced | ❌ | ✅ Sliders + SSML-lite |
| **Multi-Speaker** | ✅ | ❌ | ✅ Dialogue mode |
| **Streaming** | ✅ | ❌ | ✅ Real-time |
| **Batch Processing** | ✅ | ❌ | ✅ Queue |
| **Export Formats** | MP3, WAV, PCM | WAV only | WAV, MP3, FLAC, OGG |
| **Offline/Private** | ❌ | ✅ | ✅ |
| **Unlimited Gen** | ❌ (credits) | ✅ | ✅ |
| **API Access** | ✅ Cloud API | ❌ | ✅ Local REST API |
| **Audiobook Tools** | ❌ | ❌ | ✅ Chapter Builder |

---

## Estimated Timeline

| Phase | Features | Effort |
|---|---|---|
| Phase 1 | 5 features | ~1-2 days |
| Phase 2 | 4 features | ~3-5 days |
| Phase 3 | 5 features | ~3-4 days |
| Phase 4 | 6 features | ~5-7 days |
| **Total** | **20 features** | **~2-3 weeks** |

---

## Current Status

**Overall Progress:** 14 / 20 features completed

**Current Phase:** Phase 3 — Professional Workflow ✅ *(complete, minus removed Waveform)*

**Removed:** Waveform Visualization (native crash, too unstable with current Qt/FFmpeg stack)

**Next Up:** Phase 4 — Premium & Platform Features

---

_Last updated: 2026-07-20_ (Waveform Visualization removed)
