# -*- coding: utf-8 -*-
"""Kokoro Studio — a PySide6 desktop GUI for Kokoro-82M TTS.

MVP features (in scope):
  - Plain text editor with live character/word counter.
  - Voice library browser with metadata (language, gender, grade, description)
    and per-language filtering.
  - Synthesis speed control (slider + spinbox, 0.1x..3.0x).
  - Output path field with file-browser, defaulting to Documents/KokoroStudio/.
  - "Generate" runs the synthesis in a background QThread so the UI stays
    responsive; per-chunk progress is shown in the status bar.
  - "Stop" cancels the in-flight synthesis cleanly (via engine stop_check).
  - In-app audio playback of the generated WAV via QMediaPlayer.
  - "Preview selected voice" button to generate a short fixed-phrase sample
    and auto-play it.
  - Long texts are chunked by Kokoro's own tokenizer (with SentencePiece) — no
    hand-rolled paragraph splitter needed for the MVP.

Picked by the user (not in MVP — left for later):
  - Voice cloning, presets/history, MP3 export.

Dependencies (install before running):
    pip install PySide6 kokoro soundfile numpy

Run:
    python kokoro_gui.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from PySide6.QtCore import (
        QEvent, QIODevice, QObject, QSize, QStandardPaths, Qt, QThread,
        QTimer, QUrl, Signal,
    )
    from PySide6.QtGui import QAction, QFont, QKeySequence
    from PySide6.QtMultimedia import (
        QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer,
    )
    from PySide6.QtWidgets import (
        QAbstractItemView, QApplication, QCheckBox, QComboBox,
        QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
        QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
        QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
        QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy,
        QSlider, QSplitter, QStatusBar, QTableWidget,
        QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    )
    _HAS_PYSIDE6 = True
    _PYSIDE_IMPORT_ERR: str = ""
except ImportError as _e:
    _HAS_PYSIDE6 = False
    _PYSIDE_IMPORT_ERR: str = str(_e)

# When PySide6 is missing, the module-level class definitions below
# (`class SynthesisWorker(QThread):`, `class KokoroStudioMain(QMainWindow):`,
# `progress = Signal(...)`, `class DocumentDropEditor(QPlainTextEdit):`)
# would raise `NameError` on import — which is a much worse first
# impression than a clean install-hint message. Provide harmless stub
# names so the file PARSES even without PySide6. `main()` refuses to
# launch the app in that case, so these stubs are never actually
# instantiated or called.
if not _HAS_PYSIDE6:
    QThread = object           # type: ignore[assignment,misc]
    QMainWindow = object       # type: ignore[assignment,misc]
    QPlainTextEdit = object    # type: ignore[assignment,misc]
    Signal = (                 # type: ignore[assignment,misc]
        lambda *args, **kwargs: None
    )
    # QAction / QKeySequence / QEvent / QTabWidget / QTimer / QIODevice /
    # QAudioSink / QMediaDevices are referenced only inside methods that
    # never run when PySide6 is missing (main() gates on _HAS_PYSIDE6 before
    # constructing KokoroStudioMain). We expose harmless stubs so editor
    # auto-complete and type-checkers flag the names properly.
    QAction = object           # type: ignore[assignment,misc]
    QKeySequence = object      # type: ignore[assignment,misc]
    QEvent = object            # type: ignore[assignment,misc]
    QTabWidget = object        # type: ignore[assignment,misc]
    QTimer = object            # type: ignore[assignment,misc]
    QIODevice = object         # type: ignore[assignment,misc]
    QAudioSink = object        # type: ignore[assignment,misc]
    QMediaDevices = object     # type: ignore[assignment,misc]
    # QDialog is the base class of SettingsDialog which is declared at
    # module scope; without this stub the parse fails when PySide6 is
    # missing (headless CI). Other QtWidgets classes (QApplication,
    # QStringListModel, etc.) are only referenced inside method bodies
    # that main() never invokes without Qt available.
    QDialog = object            # type: ignore[assignment,misc]

try:
    # Streaming audio backend (Phase 2 - Real-Time Playback).
    # Mirrors the lazy-import pattern used for PySide6 above:
    # `sd` is bound at module scope so BOTH `_start_streaming_sink`
    # AND `_sd_stream_callback` (which is a class method, NOT a
    # closure inside _start_streaming_sink) can reference it.
    # A previous version lazy-imported inside `_start_streaming_sink`
    # only, which made the callback raise `NameError: name 'sd'
    # is not defined` on EOS.
    import sounddevice as sd  # type: ignore[import-not-found]
    _HAS_SOUNDDEVICE = True
except ImportError:
    sd = None  # type: ignore[assignment]
    _HAS_SOUNDDEVICE = False

import numpy as np

# Reuse the engine: list_voices, get_voice_info, generate_speech,
# DEFAULT_VOICE, SAMPLE_RATE, LANG_CODES, VOICES, SPEED_MIN, SPEED_MAX.
from kokoro_studio.engine import (  # type: ignore
    DEFAULT_VOICE,
    LANG_CODES,
    OUTPUT_FORMATS,
    SAMPLE_RATE,
    SPEED_MAX,
    SPEED_MIN,
    VOICES,
    generate_speech,
    get_voice_info,
    list_voices,
)
from kokoro_studio.streaming import (  # type: ignore
    PcmRingBuffer,
    StreamingPcmDevice,
    default_audio_output_is_available,
    make_kokoro_audio_format,
)


# ===========================================================================
# Theme: dark UI inspired by modern TTS products
# ===========================================================================

QSS = """
* { font-family: 'Segoe UI', 'Inter', system-ui, sans-serif; }

QMainWindow, QWidget {
    background-color: #0F1115;
    color: #E8EAED;
}

QFrame#Panel {
    background-color: #1A1D24;
    border: 1px solid #252932;
    border-radius: 12px;
}

QLabel#H1 {
    color: #FFFFFF;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
}
QLabel#Subtitle {
    color: #8B8F98;
    font-size: 11px;
}
QLabel#SectionTitle {
    color: #6B7280;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.5px;
}
QLabel#Counter {
    color: #6B7280;
    font-size: 11px;
}
QLabel#VoiceReadout {
    color: #E8EAED;
    font-size: 13px;
    font-weight: 600;
}
QLabel#Badge {
    color: #FFFFFF;
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 1.2px;
    padding: 4px 10px;
    border-radius: 6px;
}

QPlainTextEdit {
    background-color: #252932;
    color: #E8EAED;
    border: 1px solid #2F3340;
    border-radius: 10px;
    padding: 14px;
    selection-background-color: #7B61FF;
    selection-color: white;
    font-family: 'Consolas', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 12px;
}
QPlainTextEdit:focus { border: 1px solid #7B61FF; }

QListWidget {
    background-color: #1F2329;
    color: #E8EAED;
    border: 1px solid #2F3340;
    border-radius: 10px;
    padding: 6px;
    outline: 0;
}
QListWidget::item {
    border-radius: 8px;
    padding: 10px 12px;
    margin: 3px 1px;
}
QListWidget::item:hover { background-color: #252932; }
QListWidget::item:selected { background-color: #7B61FF; color: #FFFFFF; }
QListWidget::item QLabel { background-color: transparent; color: #E8EAED; }
QListWidget::item:selected QLabel { color: #FFFFFF; }

QPushButton {
    background-color: #252932;
    color: #E8EAED;
    border: 1px solid #2F3340;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 500;
}
QPushButton:hover { background-color: #2F3340; border-color: #3F4350; }
QPushButton:pressed { background-color: #1F2329; }
QPushButton:disabled { color: #5F6370; border-color: #252932; background-color: #1A1D24; }

QPushButton[role="primary"] {
    background-color: #7B61FF;
    color: white;
    border: 1px solid #7B61FF;
    font-weight: 600;
    padding: 9px 22px;
}
QPushButton[role="primary"]:hover  { background-color: #9178FF; border-color: #9178FF; }
QPushButton[role="primary"]:pressed{ background-color: #6B4FE5; }
QPushButton[role="primary"]:disabled {
    background-color: #3A3068; border-color: #3A3068; color: #888;
}

QPushButton[role="danger"] {
    background-color: #EF4444; color: white; border: 1px solid #EF4444;
}
QPushButton[role="danger"]:hover { background-color: #F87171; border-color: #F87171; }
QPushButton[role="danger"]:disabled {
    background-color: #6B2A2A; border-color: #6B2A2A; color: #888;
}

QPushButton[role="ghost"] { background-color: transparent; border: 1px solid #2F3340; }
QPushButton[role="ghost"]:hover { background-color: #252932; }
QPushButton[role="ghost"]:disabled { background-color: transparent; border-color: #252932; }

QDoubleSpinBox, QComboBox, QLineEdit {
    background-color: #252932;
    color: #E8EAED;
    border: 1px solid #2F3340;
    border-radius: 8px;
    padding: 7px 12px;
    selection-background-color: #7B61FF;
}
QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid #7B61FF; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: #252932; color: #E8EAED;
    border: 1px solid #2F3340;
    selection-background-color: #7B61FF;
    padding: 4px; outline: 0;
}

QProgressBar {
    background-color: #1A1D24;
    border: 1px solid #252932;
    border-radius: 6px;
    text-align: center;
    color: #E8EAED;
    height: 14px;
}
QProgressBar::chunk {
    background-color: #7B61FF;
    border-radius: 5px;
}
QProgressBar#Indeterminate { text-align: right; padding-right: 8px; color: #9DA0A8; }

QStatusBar {
    background-color: #0F1115;
    color: #9DA0A8;
    border-top: 1px solid #252932;
}
QStatusBar QLabel { color: #E8EAED; padding: 0 6px; }

QSplitter::handle { background-color: transparent; }

QToolTip {
    background-color: #1F2329; color: #E8EAED;
    border: 1px solid #2F3340;
    padding: 6px 10px;
    border-radius: 8px;
}

QScrollBar:vertical {
    background: transparent; width: 8px; margin: 4px;
}
QScrollBar::handle:vertical {
    background: #3F4350; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #5F6370; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; background: none;
}
"""


# ===========================================================================
# Helpers
# ===========================================================================

# Fixed phrases played when the user clicks "Preview selected voice". Each
# lang_code in LANG_CODES has a phrase in its own language.
PREVIEW_PHRASES = {
    "a": "Hello! This is a quick preview of my voice in American English.",
    "b": "Hello! This is a quick preview of my voice in British English.",
    "i": "Ciao! Questa è una breve anteprima della mia voce in Italiano.",
    "e": "¡Hola! Esta es una breve muestra de mi voz en español.",
    "f": "Bonjour ! Voici un court aperçu de ma voix en français.",
    "h": "Namaste! Yeh meri awaaz ka ek chhota preview hai.",
    "j": "こんにちは。これが日本語の私の声の短いプレビューです。",
    "z": "你好!这是我的中文声音的简短预览。",
    "p": "Olá! Esta é uma pequena amostra da minha voz em português.",
}


def _preview_phrase_for_lang(lang_code: str) -> str:
    return PREVIEW_PHRASES.get(lang_code, PREVIEW_PHRASES["a"])


def _default_output_dir() -> Path:
    """Return <Documents>/KokoroStudio (auto-create). Falls back gracefully."""
    try:
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    except Exception:
        docs = ""
    base = Path(docs) if docs else Path.home() / "Documents"
    folder = base / "KokoroStudio"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path.cwd()
    return folder


def _default_output_path(voice: str, fmt: str = "wav") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_voice = voice.replace("/", "_").replace("\\", "_")
    # `fmt` is canonical lowercase ('wav'|'mp3'|'flac'|'ogg'); today the
    # extension is just informational — the GUI uses it to pre-fill the
    # output filename field and to keep it consistent with the dropdown.
    if fmt not in OUTPUT_FORMATS:
        fmt = "wav"
    return str(_default_output_dir() / f"Kokoro_{safe_voice}_{ts}.{fmt}")


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{int(seconds * 1000)} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {s:05.2f}s"


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


# SSML-lite Help dialog content (Phase 2). Bound here
# rather than imported from kokoro_studio.ssml so the
# GUI keeps a single source of truth for user-facing
# documentation. Rendered cheaply on each click.
SSML_HELP_SAMPLE = """\
SSML-lite controls (Phase 2)

Type the literal markup into the editor. Markers
expand once the "Apply SSML" checkbox on the controls
panel is ON.

  <break time="1.5s"/>          Insert a 1.5-second silence.
  <break time="500ms"/>          Millisecond precision is accepted.

  <emphasis>word</emphasis>      Slows down the wrapped word
                                (effective rate: 0.85x of
                                base speed).

  <prosody rate="fast">...</prosody>
                                Speeds up the wrapped phrase.
  <prosody rate="0.8">...</prosody>
                                Numeric multipliers also work
                                (0.8 = 80% of base speed).

  Valid rate tokens:     x-slow (0.6), slow (0.8),
                         medium (1.0), fast (1.4),
                         x-fast (1.8).
  Numeric rate range:    0.5 .. 2.0  (clipped to safe band).

Notes:

  * SSML-lite and multi-speaker dialogue are mutually
    exclusive. When dialogue mode is on, SSML is silently
    ignored -- the chip turns amber to warn you.
  * The chip above the Generate button shows a
    one-line summary ("1 break + 2 emphasis + 1 prosody")
    that updates as you type.
  * Plain text without markers works as usual; toggling
    the checkbox on by accident has zero side-effects.
"""

# Short TTS samples (kept distinct from the long prose help-text docs
# so the Insert-sample button in the help dialogs drops a runnable
# script into the editor instead of documentation).
DIALOGUE_HELP_TTS_SAMPLE = (
    "[af_sky]: Hi traveller!\n"
    "[af_nicole]: Greetings, friend.\n"
    "[af_bella]: Let our tale begin.\n"
    "And this line uses the default voice again."
)

SSML_HELP_TTS_SAMPLE = (
    'Hello <break time="0.4s"/> I can pause, '
    '<emphasis>emphasise</emphasis>, and '
    '<prosody rate="fast">speak at speed</prosody>.'
)


# ===========================================================================
# Background synthesis worker (QThread)
# ===========================================================================

class SynthesisWorker(QThread):
    """Runs `generate_speech()` off the GUI thread.

    Signals (consumed on the GUI thread):
        progress(int  chunks_done, int  chunks_visible, float cumulative_seconds, float eta_seconds)
            Emitted after every chunk Kokoro produces. `cumulative_seconds`
            is the wall-clock-independent running total of audio seconds
            produced so far. `eta_seconds` is a best-effort estimate of
            how much longer the synthesis will run; `-1` until we have
            enough telemetry (≥0.5 s of synthesis + ≥2 chunks) to
            extrapolate the realtime rate stably. Caller should treat the
            estimate as a hint, not a contract.
        log(str)                    Any diagnostic line from the engine.
        finished_ok(str path, float duration_seconds, object audio_array)
            Final audio has been written to `path`.
        failed(str error_msg)       Engine raised; nothing was written.

    Set `request_stop()` (from any thread) to cancel cleanly: the engine's
    `stop_check` raises *before* writing the output file.
    """

    progress = Signal(int, int, float, float)
    # Emitted on every Kokoro chunk with the audio ndarray. Used by the
    # main window to push chunks into the streaming PCM ring buffer
    # (Phase 2 "Real-Time Streaming Playback"). Emitting the raw array
    # (rather than already-encoded bytes) keeps the worker's contract
    # simple and lets the consumer format-convert if needed. `object`
    # is the canonical PySide6 signal type for arbitrary Python data.
    chunk_ready = Signal(int, int, object)  # (segment_idx, chunk_idx, audio_chunk)
    # Fired ONCE per segment transition in multi-speaker mode (i.e.
    # the FIRST chunk of a new voice arrives). In single-speaker mode
    # this fires exactly once with seg_idx=0 at the first chunk. The
    # main window uses it to update the status bar with "Speaker
    # X/Y: <voice>" without having to poll on every chunk.
    segment_started = Signal(int)
    finished_ok = Signal(str, float, object)
    failed = Signal(str)

    # Empirical TTS speed used for ETA extrapolation when the engine
    # hasn't revealed total chunks upfront (Kokoro chunks lazily through
    # its SentencePiece tokenizer — we only know per-chunk counts
    # after-the-fact). 13 chars/sec ≈ 150 wpm, the typical English
    # narrator cadence. Tune `_EMPIRICAL_CHARS_PER_AUDIO_SEC` if your
    # workflow is heavily non-English or unusually slow/fast.
    _EMPIRICAL_CHARS_PER_AUDIO_SEC = 13.0
    # Minimum telemetry before we emit a non-trivial ETA. The first
    # chunk's wall-clock is dominated by Python startup overhead in the
    # worker, so the rate estimate from `cumulative_chunk_count == 0` is
    # wildly inflated.
    _ETA_MIN_WARMUP_S = 0.5
    _ETA_MIN_CHUNKS = 2

    def __init__(
        self,
        text: str,
        voice: str,
        speed: float,
        output_path: str,
        output_format: str,
        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        # Phase 2 - Voice Blending. Snapshot of the GUI's
        # `_loaded_blends` dict at click time, so the worker
        # thread doesn't re-read disk between requests. Voice
        # blends are frozen dataclasses, so a shallow dict copy
        # is thread-safe.
        blends: Optional[Mapping[str, "VoiceBlend"]] = None,
        parent: Optional[QObject] = None,
        # Phase 2 - SSML-lite Controls. Opt-in boolean
        # forwarded verbatim to engine.generate_speech;
        # defaults to False for backward compat with
        # Phase 1 callers/tests.
        apply_ssml: bool = False,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._voice = voice
        self._speed = speed
        self._output_path = output_path
        self._output_format = output_format
        # Optional dict mapping find->replace rules applied to the input
        # text before synthesis. None means: no pronunciation processing.
        # Mutable copy is owned by the worker — caller can mutate their
        # own dict freely while we're synthesising without a race.
        self._pronunciation_rules = (
            dict(pronunciation_rules) if pronunciation_rules else None
        )
        # Phase 2 — Multi-Speaker Dialogue Mode. When True the engine
        # parses `[voice_name]:` markers in `text` and synthesises each
        # segment with its own voice. `speaker_gap_s` is the silence
        # inserted between segments (default 0.25 s).
        self._multi_speaker = multi_speaker
        self._speaker_gap_s = speaker_gap_s
        # Phase 2 - Voice Blending. Shallow snapshot copy so the
        # worker doesn't share the GUI's dict reference (the user
        # could open the dict editor while we're synthesising).
        self._blends: Optional[dict] = (
            dict(blends) if blends else None
        )
        # Phase 2 - SSML-lite. Snapshot the bool at
        # start() time so a mid-run checkbox flip
        # can't silently switch the engine from
        # plain to SSML mode.
        self._apply_ssml = bool(apply_ssml)  # SSML-GUI-E2
        # Tracks the previous segment index in `_on_chunk` to detect
        # "speaker changed" transitions in the stream of chunks. The
        # engine emits multiple chunks per segment; we surface one
        # "now speaking voice X" event per actual transition.
        self._last_seg_idx: int = -1
        # Cumulative chunk counter across segments — engine's
        # chunk_idx resets per-segment so we maintain a global
        # counter that the status bar uses for ETA / progress.
        self._cumulative_chunk_count: int = 0
        self._stop_requested = False
        # Module-level on the worker so the chunk callback can mutate it.
        self._cumulative_samples = 0
        # Wall-clock (monotonic) at the first chunk; reset to None
        # between runs so a re-synthesis starts the ETA clock fresh.
        self._synth_start_time: Optional[float] = None

    def request_stop(self) -> None:
        self._stop_requested = True

    # ---- engine hooks --------------------------------------------------
    def _stop_check(self) -> bool:
        return self._stop_requested

    def _on_chunk(self, seg_idx: int, chunk_idx: int, audio_chunk: np.ndarray) -> None:
        self._cumulative_samples += len(audio_chunk)
        cum_seconds = self._cumulative_samples / SAMPLE_RATE

        # Capture monotonic wall-clock at the first chunk so the ETA
        # signal can extrapolate from `cumulative_audio / elapsed`
        # once we have enough telemetry.
        now = time.monotonic()
        if self._synth_start_time is None:
            self._synth_start_time = now
        elapsed_wallclock = now - self._synth_start_time

        # Best-effort ETA. Until we've seen 2 chunks AND at least half a
        # second of wall-clock, the first-chunk latency dominates the
        # rate estimate, so we emit `-1` (“no estimate yet”).
        eta_seconds = -1.0
        if (elapsed_wallclock >= self._ETA_MIN_WARMUP_S
                and (self._cumulative_chunk_count + 1) >= self._ETA_MIN_CHUNKS):
            rate = cum_seconds / elapsed_wallclock  # s_audio per s_wall
            if rate > 0.0:
                est_total_audio = (
                    len(self._text) / self._EMPIRICAL_CHARS_PER_AUDIO_SEC
                )
                remaining_audio = max(0.0, est_total_audio - cum_seconds)
                eta_seconds = remaining_audio / rate

        # Broadcast progress (status bar / progress bar).
        # Broadcast progress + raw chunk.
        #   * `progress` keeps the (chunks_done, chunks_visible) layout
        #     so the existing chunk-based ETA logic in
        #     `_on_synthesis_progress` keeps working unchanged.
        #   * `chunk_ready` carries BOTH (seg_idx, chunk_idx) so the
        #     streaming consumer can route byte deltas AND the GUI
        #     status bar can render "Speaker X/Y: <voice>" once it
        #     sees seg_idx flip.
        # We emit progress BEFORE chunk_ready so the status bar updates
        # a tick before the audio hits the ring buffer.
        # Cumulative chunk counter so the status bar shows
        # monotonically-growing "chunk N" instead of resetting
        # to 1 every speaker transition.
        self._cumulative_chunk_count += 1
        self.progress.emit(
            self._cumulative_chunk_count,
            self._cumulative_chunk_count,
            cum_seconds,
            eta_seconds,
        )
        # Kept the local chunk_idx on chunk_ready so downstream
        # consumers can correlate per-segment if needed.
        _unused_local_chunk_idx = chunk_idx  # noqa: F841
        # Detect speaker transition in the stream of chunks: the
        # engine emits many chunks per segment, so we surface
        # `segment_started` only on the first chunk of each new
        # segment (or once at startup in single-speaker mode).
        if seg_idx != self._last_seg_idx:
            self._last_seg_idx = seg_idx
            self.segment_started.emit(seg_idx)
        self.chunk_ready.emit(seg_idx, chunk_idx, audio_chunk)

    # ---- main entry ----------------------------------------------------
    def run(self) -> None:  # noqa: D401 — Qt calls this on .start()
        self._cumulative_samples = 0
        self._cumulative_chunk_count = 0
        self._last_seg_idx = -1  # reset speaker-transition tracker
        # NOTE: the engine already mirrors useful diagnostics to sys.stderr,
        # so the worker intentionally stays quiet and just signals progress.
        try:
            audio = generate_speech(
                text=self._text,
                voice=self._voice,
                speed=self._speed,
                output_path=self._output_path,
                output_format=self._output_format,
                pronunciation_rules=self._pronunciation_rules,
                multi_speaker=self._multi_speaker,
                speaker_gap_s=self._speaker_gap_s,
                on_chunk=self._on_chunk,
                stop_check=self._stop_check,
                # Phase 2 - Voice Blending. Pass the snapshotted
                # blend registry to the engine so it can resolve
                # saved blend names to tensors per-segment.
                blends=self._blends,

                # Phase 2 - SSML-lite. Forward the
                # opt-in flag so the engine's
                # _generate_ssml_segments path takes
                # over when the editor has SSML
                # markup + the checkbox was on at
                # click time.
                apply_ssml=self._apply_ssml,  # SSML-GUI-E3
            )
            if self._stop_requested:
                # Engine raised but we caught gracefully above; belt + braces.
                self.failed.emit("Generation stopped by user (no file written).")
                return
            duration = len(audio) / SAMPLE_RATE
            self.finished_ok.emit(self._output_path, duration, audio)
        except ImportError as e:
            # The text from `e` already names the missing package (e.g.
            # "No module named 'lameenc'"). Surface it verbatim so the user
            # gets the exact missing module name, and only fall back to the
            # generic engine deps list when the error truly didn't tell us.
            msg = str(e).strip() or "Unknown import."
            missing = getattr(e, "name", "") or ""
            if "lameenc" in missing or "lameenc" in msg.lower():
                install_hint = "pip install lameenc"
            else:
                install_hint = "pip install kokoro soundfile numpy"
            self.failed.emit(
                f"Missing dependency: {msg}\n\n"
                f"Run:  {install_hint}"
            )
        except RuntimeError as e:
            if "cancelled" in str(e).lower():
                self.failed.emit("Generation cancelled.")
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001 — surface anything from the engine
            self.failed.emit(f"{type(e).__name__}: {e}")


# ===========================================================================
# Drag-and-drop aware editor
# ===========================================================================

class DocumentDropEditor(QPlainTextEdit):
    """`QPlainTextEdit` that intercepts dropped files.

    Default `QPlainTextEdit.dropEvent` only handles in-app text drags.
    We override both `dragEnterEvent` and `dropEvent` so that files
    dragged from Windows Explorer (or any other file source) whose
    extension matches our supported document set are accepted. A
    `fileDropped(str)` signal then bubbles the absolute path back to
    the main window, which routes it through `document_loader`.

    Non-matching drops (e.g. dragging a `.docx`) fall through to the
    parent's default behaviour, so the editor remains a drop target
    for plain text.
    """

    # `Signal` is stubbed to a returning-None lambda when PySide6 is
    # missing; when PySide6 IS present it's the real Qt signal class.
    fileDropped = Signal(str)
    # Emitted when the user drops 2+ supported files at once. The main
    # window turns this into a status-bar hint telling the user to
    # drop one file at a time.
    multiDropRejected = Signal(int)

    _SUPPORTED_DROP_EXTS = (".txt", ".pdf", ".epub")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    # ---- drag-and-drop overrides ----------------------------------
    def dragEnterEvent(self, event) -> None:
        # Accept ONLY when the payload is exactly one supported file.
        # Multi-file drops deliberately fall through to refusal so the
        # user gets a clear "no-drop" cursor instead of silently loading
        # only the first file.
        if self._supported_file_count(event) == 1:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        # Qt only fires dragMoveEvent after a successful dragEnter.
        # Mirror the same accept logic to keep the cursor in "+" mode.
        if self._supported_file_count(event) == 1:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        # Count of supported files in the payload. We only honour
        # exactly-one drops; for 0 we let the parent text-drop handle it
        # (or reject), for >=2 we refuse entirely.
        supported = self._supported_file_url(event)
        if supported is None:
            # Fall back to the default text-drop behaviour so the
            # editor still works as a plain text drop target.
            super().dropEvent(event)
            return
        if isinstance(supported, list):
            # Multiple supported files in the payload — reject explicitly
            # so the dropping application knows the drop succeeded
            # elsewhere (it didn't). We don't pop a modal QMessageBox
            # here (dropEvent runs inside native drag code; mods can
            # confuse some shells). The main window listens to
            # `multiDropRejected` and shows a status-bar hint instead.
            self.multiDropRejected.emit(len(supported))
            event.ignore()
            return
        self.fileDropped.emit(supported)
        event.acceptProposedAction()

    # ---- private helpers ------------------------------------------
    def _supported_file_count(self, event) -> int:
        """Count supported-document URLs in the drag payload."""
        if not event.mimeData().hasUrls():
            return 0
        n = 0
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            ext = Path(url.toLocalFile()).suffix.lower()
            if ext in self._SUPPORTED_DROP_EXTS:
                n += 1
        return n

    def _supported_file_url(self, event):
        """Return:
              None         — no supported docs in the payload
              <str>        — exactly one supported local path
              list[str]    — two or more supported local paths
        """
        if not event.mimeData().hasUrls():
            return None
        found = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            local = url.toLocalFile()
            if Path(local).suffix.lower() in self._SUPPORTED_DROP_EXTS:
                found.append(local)
        if not found:
            return None
        if len(found) == 1:
            return found[0]
        return found


# ===========================================================================
# Settings / Info dialog
# ===========================================================================

# Dark QSS scoped to the SettingsDialog only — applied via
# `dialog.setStyleSheet(SETTINGS_QSS)` so the rest of the app stays on
# the existing main-window theme. We do NOT append to the global `QSS`
# string because tab styling is opinionated and we'd rather have it
# isolated for future tweaks.
SETTINGS_QSS = """
QDialog {
    background-color: #0F1115;
}

QTabWidget::pane {
    border: 1px solid #252932;
    background-color: #1A1D24;
    border-radius: 0px;
    top: 0px;
}
QTabBar {
    background-color: transparent;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background-color: transparent;
    color: #9DA0A8;
    padding: 9px 18px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #1A1D24;
    color: #E8EAED;
    border-bottom: 2px solid #7B61FF;
}
QTabBar::tab:hover:!selected {
    color: #E8EAED;
}

QLabel#SettingsH1 {
    color: #FFFFFF;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
}
QLabel#SettingsBlock {
    color: #E8EAED;
    font-size: 12px;
    line-height: 1.6;
}
QLabel#AddrLabel {
    color: #6B7280;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
}

QTableWidget {
    background-color: #1F2329;
    color: #E8EAED;
    border: 1px solid #252932;
    border-radius: 8px;
    gridline-color: #252932;
}
QHeaderView::section {
    background-color: #1A1D24;
    color: #6B7280;
    border: none;
    border-bottom: 1px solid #252932;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 1.2px;
}

QLineEdit#AddressReadOnly {
    background-color: #252932;
    color: #E8EAED;
    border: 1px solid #2F3340;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #7B61FF;
}
"""


class SettingsDialog(QDialog):
    """Application-info dialog: About, Shortcuts, Support, License.

    Four tabs keep each concern isolated:
        About       \u2014 app name / version / creator link / engine attribution
        Shortcuts   \u2014 keyboard shortcut reference (mirrors tooltips)
        Support     \u2014 copy-to-clipboard BTC / ETH addresses
        License     \u2014 short summary of the source-available license

    Crypto addresses live as class constants so a single grep
    (`SettingsDialog._DONATE_`) surfaces them and any drift against
    DONATIONS.md is easy to spot. They are rendered read-only in
    monospace with a `Copy` button next to each so the user never has
    to triple-click-and-drag a 42-char bech32 / 0x string.

    Version display:
        Hardcoded to "0.1.0" rather than read from `kokoro_studio.__version__`
        because `__init__.py` defines that attribute AFTER its submodule
        imports \u2014 importing it at gui.py module-load time would trigger a
        circular-import `ImportError`. Update in two places if you bump
        the version: this constant AND `kokoro_studio/__init__.py`.
    """

    # Donations. Must match DONATIONS.md (kept in sync as part of every
    # release where either the BTC or the ETH address rotates).
    _DONATE_BTC = "bc1qcqycagy7p0tf4vc682ygdq522jee0cterllcv6"
    _DONATE_ETH = "0x0a6415FcBf54A46C4b21851493a0B387e8c23c94"

    # GitHub creator handle. Built into the URL at display time so we
    # don't need to update two strings if the handle ever changes.
    _CREATOR_HANDLE = "MattiaAlessi"

    _VERSION_DISPLAY = "0.1.0"  # see class docstring for sync note

    _SHORTCUTS = (
        ("Ctrl+G",  "Generate audio from editor text"),
        ("Ctrl+P",  "Preview the selected voice"),
        ("Ctrl+O",  "Open a .txt / .pdf / .epub document"),
        ("Ctrl+S",  "Save editor text as a .txt file"),
        ("Ctrl+Z",  "Undo (in the editor)"),
        ("Ctrl+Y",  "Redo (in the editor) \u2014 Cmd+Shift+Z on macOS"),
        ("Space",   "Play / Pause last generated audio"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kokoro Studio \u00b7 Settings & Info")
        self.resize(680, 520)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(SETTINGS_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tabs = QTabWidget(self)
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_about_tab(), "About")
        tabs.addTab(self._build_shortcuts_tab(), "Shortcuts")
        tabs.addTab(self._build_donate_tab(), "Support / Donate")
        tabs.addTab(self._build_license_tab(), "License")
        root.addWidget(tabs, 1)

        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)
        close_btn.setText("Close")
        close_btn.setProperty("role", "primary")
        bbox.accepted.connect(self.accept)
        root.addWidget(bbox)

    # ====================================================== About tab
    def _build_about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        title = QLabel("\U0001F399  Kokoro Studio")  # \U0001F399 studio mic
        title.setObjectName("SettingsH1")
        layout.addWidget(title)

        subtitle = QLabel(
            f"v{self._VERSION_DISPLAY}  \u00b7  Local neural text-to-speech"
        )
        subtitle.setObjectName("AddrLabel")
        layout.addWidget(subtitle)

        layout.addSpacing(6)

        creator_url = f"https://github.com/{self._CREATOR_HANDLE}"
        info = QLabel(
            "A free, offline, private desktop GUI for the "
            "<a href='https://huggingface.co/hexgrad/Kokoro-82M'>Kokoro-82M"
            "</a> neural TTS model \u2014 29 built-in voices, multi-format "
            "export (WAV / MP3 / FLAC / OGG), a pronunciation dictionary, "
            "<b>multi-speaker dialogue mode</b>, <b>SSML-lite controls</b>, and a growing set of audiobook / batch features.<br><br>"
            f"<b>Created by:</b> "
            f"<a href='{creator_url}'>{self._CREATOR_HANDLE}</a> on GitHub."
            "<br><br>"
            "<b>Engine:</b> Kokoro-82M by hexgrad &amp; the Kokoro "
            "contributors."
        )
        info.setObjectName("SettingsBlock")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        info.setOpenExternalLinks(True)
        info.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        layout.addWidget(info)

        layout.addStretch(1)

        footer = QLabel(
            "Built with PySide6 \u00b7 kokoro \u00b7 soundfile \u00b7 lameenc "
            "\u00b7 pypdf \u00b7 ebooklib \u00b7 beautifulsoup4"
        )
        footer.setObjectName("AddrLabel")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        return page

    # ==================================================== Shortcuts tab
    def _build_shortcuts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        intro = QLabel(
            "Available keyboard shortcuts. Open / Save / Undo / Redo use "
            "<code>QKeySequence.StandardKey</code> so they automatically "
            "bind to <b>Cmd</b> + O / S / Z on macOS."
        )
        intro.setObjectName("SettingsBlock")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        table = QTableWidget(0, 2, page)
        table.setHorizontalHeaderLabels(["Shortcut", "Action"])
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )

        for shortcut, action in self._SHORTCUTS:
            r = table.rowCount()
            table.insertRow(r)
            s_item = QTableWidgetItem(shortcut)
            mono = QFont("Consolas")
            mono.setStyleHint(QFont.Monospace)
            s_item.setFont(mono)
            s_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, 0, s_item)
            table.setItem(r, 1, QTableWidgetItem(action))
        table.resizeRowsToContents()

        layout.addWidget(table, 1)

        layout.addSpacing(4)
        hint = QLabel(
            "<b>Note:</b> Space only intercepts typing in the editor while "
            "an audio file is loaded. Otherwise Space inserts a regular "
            "space character."
        )
        hint.setObjectName("SettingsBlock")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        return page

    # ===================================================== Donate tab
    def _build_donate_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        intro = QLabel(
            "Kokoro Studio is free, open-source, and developed in someone's "
            "spare time. If it's useful to you, a donation is appreciated "
            "but never required. <b>Always double-check the address</b> "
            "against a trusted source before sending any funds."
        )
        intro.setObjectName("SettingsBlock")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addSpacing(6)

        layout.addWidget(self._build_address_row(
            page, "Bitcoin (BTC)", self._DONATE_BTC,
        ))
        layout.addWidget(self._build_address_row(
            page, "Ethereum (ETH)", self._DONATE_ETH,
        ))

        layout.addStretch(1)
        return page

    def _build_address_row(
        self, parent: QWidget, label_text: str, address: str,
    ) -> QWidget:
        """One label + monospace-read-only QLineEdit + Copy-button row.

        The `addr=address` default-arg capture below is the standard Python
        idiom to dodge lambda late-binding when constructing handlers in a
        loop / factory function.
        """
        row = QWidget(parent)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)

        lbl = QLabel(label_text)
        lbl.setObjectName("AddrLabel")
        lbl.setMinimumWidth(110)
        hl.addWidget(lbl)

        # Address field \u2014 read-only, monospace, cursor pinned at the start
        # so the network prefix (`bc1...` / `0x...`) is always visible.
        edit = QLineEdit(address)
        edit.setObjectName("AddressReadOnly")
        edit.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        edit.setFont(mono)
        edit.setCursorPosition(0)
        hl.addWidget(edit, 1)

        copy_btn = QPushButton("Copy")
        copy_btn.setProperty("role", "ghost")
        copy_btn.setFixedWidth(78)
        copy_btn.clicked.connect(
            lambda _checked=False, addr=address, btn=copy_btn:
                self._copy_and_flash(addr, btn)
        )
        hl.addWidget(copy_btn)

        return row

    # ===================================================== License tab
    def _build_license_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        title = QLabel("License")
        title.setObjectName("SettingsH1")
        layout.addWidget(title)

        body = QLabel(
            "Released under the <b>Kokoro Studio Source-Available License "
            "v1.0</b>.<br><br>"
            "Permits personal, educational, and commercial use, "
            "modifications, and redistribution \u2014 provided the original "
            "copyright notice and donation info are preserved in any "
            "redistribution.<br><br>"
            "The full text lives in the <code>LICENSE</code> file at the "
            "project root. See also <code>DONATIONS.md</code> for the "
            "donation channels list (kept in sync with the BTC and ETH "
            "addresses on the previous tab)."
        )
        body.setObjectName("SettingsBlock")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        layout.addWidget(body)

        layout.addStretch(1)
        return page

    # ================================================= Slot: copy + flash
    def _copy_and_flash(self, address: str, button: QPushButton) -> None:
        """Copy `address` to the system clipboard, then briefly re-label
        the source button to give visible feedback that the click was
        registered.

        1.4 s is the practical lower bound for "I just clicked this and
        am probably going to glance at the button" \u2014 long enough to
        register, short enough not to feel sticky if the user clicks
        Copy multiple times in quick succession.
        """
        QApplication.clipboard().setText(address)
        original = button.text()
        button.setText("Copied!")
        button.setEnabled(False)
        QTimer.singleShot(
            1400,
            lambda b=button, txt=original: self._restore_copy_btn(b, txt),
        )

    @staticmethod
    def _restore_copy_btn(button: QPushButton, original_text: str) -> None:
        button.setText(original_text)
        button.setEnabled(True)


# ===========================================================================
# Main window
# ===========================================================================

class KokoroStudioMain(QMainWindow):

    _SPEED_TICK = 100  # spinbox value = slider_value / _SPEED_TICK

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kokoro Studio")
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)

        self._worker: Optional[SynthesisWorker] = None
        self._last_audio_path: Optional[str] = None
        self._current_voice: str = DEFAULT_VOICE

        # Pronunciation dictionary state. Loaded from the JSON file in
        # `_load_pron_dict()` which is called after the UI is built so
        # the count label can be repopulated synchronously.
        self._pron_rules: dict = {}
        self._pron_dict_path = _default_output_dir() / "pronunciation.json"

        # Audio playback (file-based; used when streaming is OFF or as
        # the post-synthesis re-play path for streamed runs).
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        # In PySide6/Qt6, volume lives on QAudioOutput (QMediaPlayer.setVolume
        # was removed in Qt 6).
        self._audio_out.setVolume(0.9)

        # Real-time streaming playback (Phase 2). The default is ON
        # because streaming is explicitly the "ElevenLabs-feel"
        # headline feature in PLAN.md ("User hears audio within ~200ms
        # of clicking Generate"). We probe the platform audio back-end
        # once at startup; if it returns isNull(), the checkbox is
        # disabled and we silently fall back to file-based playback.
        #
        # IMPORTANT: `_audio_sink` and `_streaming_device` MUST stay
        # as long-lived Python references on the main window. PySide6
        # does NOT take ownership of the QIODevice passed to
        # `QAudioSink.start()`. If the only Python reference to
        # either object is GC'd mid-playback, the C++ audio thread
        # segfaults the next time it calls `readData`. We saw this
        # exact failure mode in early debugging — keep these attrs.
        # Streaming playback backend (Phase 2 - Real-Time Playback).
        # We migrated from PySide6 QAudioSink (which proved silent
        # on the user's Windows audio endpoint despite v1's Int16
        # PCM fix) to sounddevice.OutputStream. PortAudio / WASAPI
        # is more reliable and accepts float32 PCM directly. v1's
        # `QAudioSink.error()` polling races are gone; we now
        # check `_sd_stream.active` (PortAudio's own flag).
        self._sd_stream: Optional[object] = None
        self._ring_buffer: Optional[PcmRingBuffer] = None
        # Volume carry-over for sounddevice: cached at start_time
        # so the PortAudio callback never reads QAudioOutput off
        # the GUI thread (avoids any cross-thread Qt ambiguity).
        self._stream_volume: float = 0.9
        self._stream_available: bool = default_audio_output_is_available()
        # `last_stream_disabled_reason` is a short string shown in the
        # stream checkbox tooltip when streaming is unavailable — kept
        # as a member so we don't recompute class-level message keys
        # on every tooltip refresh.
        self._stream_disabled_reason: str = (
            "" if self._stream_available
            else "streaming unavailable: no local audio output device"
        )

        # Phase 2 — Multi-Speaker Dialogue Mode (Phase 2 next-up).
        # `self._dialogue_chip` is the inline label that shows a
        # live "🎭 N speakers detected: voice1, voice2, …" hint as
        # soon as the user types the first `[voice]:` marker. It's
        # hidden when no markers are present so single-speaker
        # scripts don't clutter the controls panel.
        self._dialogue_chip = None  # type: ignore[assignment]
        # `_dialogue_chip_row` wraps the chip + help button in a
        # single QWidget so they can be hidden together by
        # `_refresh_dialogue_chip`. Set to None here; the actual
        # widget is built by `_build_controls_panel` after this
        # __init__ returns. The `getattr` defensive read in
        # `_refresh_dialogue_chip` covers the pre-build window.
        self._dialogue_chip_row = None  # type: ignore[assignment]
        self._dialogue_help_btn = None  # type: ignore[assignment]

        # Phase 2 - SSML-lite Controls. Parity with
        # the dialogue placeholders above: built in
        # _build_controls_panel, wired in
        # _wire_signals. None values safely defer any
        # pre-build textChanged events.
        self._ssml_chip = None  # type: ignore[assignment]  # SSML-GUI-E5
        self._ssml_chip_row = None  # type: ignore[assignment]
        self._ssml_help_btn = None  # type: ignore[assignment]
        self._ssml_checkbox = None  # type: ignore[assignment]
        # Discoverability banner: persistent QLabel above the editor.
        # Hidden once the user has typed more than ~30 characters.
        self._discoverability_banner = None  # type: ignore[assignment]

        # Phase 2 - Voice Blending. Built in `_build_voice_panel`
        # and wired in `_wire_signals`. Pre-declared here so any
        # pre-build reads return None cleanly (parity with _dialogue_*).
        self._blend_frame = None  # type: ignore[assignment]
        self._blend_voice_a_combo = None  # type: ignore[assignment]
        self._blend_voice_b_combo = None  # type: ignore[assignment]
        self._blend_alpha_slider = None  # type: ignore[assignment]
        self._blend_alpha_spin = None  # type: ignore[assignment]
        self._blend_name_edit = None  # type: ignore[assignment]
        self._blend_save_btn = None  # type: ignore[assignment]
        self._blend_preview_btn = None  # type: ignore[assignment]
        # Loaded blend presets dict, kept in sync with
        # Documents/KokoroStudio/voice_blends.json.
        self._loaded_blends: dict = {}
        self._blend_dict_path = _default_output_dir() / "voice_blends.json"
        # Suppresses the alpha_slider <-> alpha_spin feedback loop.
        self._suppress_blend_alpha_sync = False
        # Set by `_on_preview_blend_clicked` while a preview is
        # synthesising on the GUI thread. The SynthesisWorker
        # check (`_worker.isRunning()`) does NOT cover this case
        # because the preview is synchronous `generate_speech` —
        # a Generate click during preview would otherwise launch
        # a second `pipeline(...)` on the same KPipeline.
        self._preview_in_progress = False
        # Populated in `_on_generate_clicked` from `parse_dialogue`;
        # the SynthesisWorker reads it through the multi_speaker flag,
        # but the main window keeps a copy so `_on_segment_started`
        # can resolve the voice name for a given segment index without
        # re-parsing the editor text.
        self._current_segments: list = []

        # Build (creates every widget, including _voice_list and _voice_readout).
        self._build_ui()
        self._wire_signals()
        # QAction-based keyboard shortcuts (Ctrl+G, Ctrl+P, Ctrl+O, Ctrl+S,
        # Ctrl+Z, Ctrl+Y, Space). Must run after `_wire_signals` so the
        # actions can hook the existing slots; must run before
        # `_update_button_states` so QAction enabled state mirrors buttons.
        self._wire_shortcuts()
        # Populate the voice list *after* every widget exists. With no
        # language filter in the GUI we always pass None so all 29 English
        # presets are surfaced in a single flat list.
        self._repopulate_voice_list(None)
        self._refresh_output_path()
        self._load_pron_dict()
        # Phase 2 - Voice Blending. Load blends so they're
        # available to the FIRST `_repopulate_voice_list` call
        # below; otherwise blends loaded from disk on first run
        # would never render in the voice list (the panel was
        # built before this hook ran).
        self._load_blends()
        # Rebuild the voice list now that the blend registry is
        # populated; without this, saved blends stay invisible
        # until the user saves a new one (which itself triggers
        # a repopulate via `_save_blend`).
        self._repopulate_voice_list(None)
        self._update_button_states()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("Central")
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(14)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(10)
        splitter.addWidget(self._build_voice_panel())
        splitter.addWidget(self._build_editor_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 820])
        root.addWidget(splitter, 1)

        root.addWidget(self._build_controls_panel())
        root.addWidget(self._build_status_bar())

        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        # Title block
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("🎙  Kokoro Studio")
        title.setObjectName("H1")
        subtitle = QLabel(
            "Local, free, fast neural text-to-speech · powered by Kokoro‑82M"
        )
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        h.addLayout(title_box)
        h.addStretch(1)

        # Badges (right side)
        badges = QHBoxLayout()
        badges.setSpacing(8)
        for text, bg in [
            ("OFFLINE", "#22C55E"),
            ("24 kHz", "#7B61FF"),
            (f"{len(VOICES)} VOICES", "#3F4350"),
            (f"{len(LANG_CODES)} LANGUAGES", "#3F4350"),
        ]:
            lbl = QLabel(text)
            lbl.setObjectName("Badge")
            lbl.setStyleSheet(
                f"background-color: {bg}; color: #FFFFFF; "
                f"font-weight: 600; font-size: 10px; letter-spacing: 1.2px;"
                f"padding: 5px 10px; border-radius: 6px;"
            )
            badges.addWidget(lbl)
        h.addLayout(badges)

        # Settings / info button (gear icon). Opens the modal
        # `SettingsDialog` (about / shortcuts / donations / license).
        # Kept small + round by an inline override since the global QSS
        # padding (9px/16px) is too big for a 34x34 icon button.
        self._settings_btn = QPushButton("\u2699")
        self._settings_btn.setProperty("role", "ghost")
        self._settings_btn.setToolTip(
            "Settings & info  \u00b7  shortcuts, donations, about"
        )
        self._settings_btn.setFixedSize(34, 34)
        self._settings_btn.setStyleSheet(
            "font-size: 18px; padding: 0; border-radius: 17px;"
        )
        h.addWidget(self._settings_btn)

        return header

    def _build_voice_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Section title (filter dropdown removed per user request — flat list).
        title = QLabel("VOICE LIBRARY")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        # Voice list (populated by __init__ so voice_readout is in scope).
        self._voice_list = QListWidget()
        self._voice_list.setSelectionMode(QListWidget.SingleSelection)
        self._voice_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        layout.addWidget(self._voice_list, 1)

        # Preview button
        self._preview_btn = QPushButton("▶  Preview selected voice")
        self._preview_btn.setProperty("role", "ghost")
        layout.addWidget(self._preview_btn)

        # ---- BLEND EDITOR (Phase 2 - Voice Blending) --------
        # Inline frame for creating / previewing custom voice
        # blends. Voice A / Voice B dropdowns + alpha slider +
        # name field + Save / Preview buttons. Saved blends
        # appear in `_voice_list` (above) with a "BLEND" badge.
        self._blend_frame = QFrame()
        self._blend_frame.setObjectName("Panel")
        bl = QVBoxLayout(self._blend_frame)
        bl.setContentsMargins(0, 8, 0, 0)
        bl.setSpacing(8)

        bl_title = QLabel("🎛  CREATE BLEND")
        bl_title.setObjectName("SectionTitle")
        bl.addWidget(bl_title)

        # Voice A + Voice B row
        ab_row = QHBoxLayout()
        ab_row.setSpacing(8)
        self._blend_voice_a_combo = QComboBox()
        self._blend_voice_b_combo = QComboBox()
        for _v in list_voices():
            self._blend_voice_a_combo.addItem(_v, _v)
            self._blend_voice_b_combo.addItem(_v, _v)
        # Sensible defaults: af_bella + af_sarah so dragging the
        # alpha slider produces an obvious timbre shift out of
        # the box.
        self._blend_voice_a_combo.setCurrentText("af_bella")
        self._blend_voice_b_combo.setCurrentText("af_sarah")
        a_box = QVBoxLayout()
        a_lbl = QLabel("A")
        a_lbl.setObjectName("AddrLabel")
        a_box.addWidget(a_lbl)
        a_box.addWidget(self._blend_voice_a_combo)
        b_box = QVBoxLayout()
        b_lbl = QLabel("B")
        b_lbl.setObjectName("AddrLabel")
        b_box.addWidget(b_lbl)
        b_box.addWidget(self._blend_voice_b_combo)
        ab_row.addLayout(a_box, 1)
        ab_row.addLayout(b_box, 1)
        bl.addLayout(ab_row)

        # Alpha slider + spinbox (kept aligned with the speed-control pattern).
        alpha_row = QHBoxLayout()
        alpha_row.setSpacing(8)
        self._blend_alpha_slider = QSlider(Qt.Horizontal)
        self._blend_alpha_slider.setRange(0, 100)  # 0..1 mapped below
        self._blend_alpha_slider.setValue(50)
        self._blend_alpha_spin = QDoubleSpinBox()
        self._blend_alpha_spin.setDecimals(2)
        self._blend_alpha_spin.setSingleStep(0.05)
        self._blend_alpha_spin.setRange(0.0, 1.0)
        self._blend_alpha_spin.setValue(0.50)
        self._blend_alpha_spin.setMinimumWidth(72)
        alpha_row.addWidget(self._blend_alpha_slider, 1)
        alpha_row.addWidget(self._blend_alpha_spin)
        bl.addLayout(alpha_row)

        # Name field + Save button + Preview button
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        name_label = QLabel("Name:")
        name_label.setObjectName("AddrLabel")
        self._blend_name_edit = QLineEdit()
        self._blend_name_edit.setPlaceholderText("my_custom_voice")
        self._blend_name_edit.setToolTip(
            "Identifier (a-z, 0-9, _) - saved as a reusable preset.\n"
            "Tip: leave empty before clicking Save to auto-generate\n"
            "  from the current Voice A + Voice B + alpha."
        )
        action_row.addWidget(name_label)
        action_row.addWidget(self._blend_name_edit, 1)
        self._blend_preview_btn = QPushButton("▶  Preview blend")
        self._blend_preview_btn.setProperty("role", "ghost")
        self._blend_preview_btn.setToolTip(
            "Generate a short sample with the CURRENTLY-EDITED\n"
            " blend (alpha / Voice A / Voice B), WITHOUT saving\n"
            " - lets you hear a tweak before committing it."
        )
        action_row.addWidget(self._blend_preview_btn)
        self._blend_save_btn = QPushButton("💾  Save blend")
        self._blend_save_btn.setProperty("role", "primary")
        action_row.addWidget(self._blend_save_btn)
        bl.addLayout(action_row)

        # Count label (mirrors the pronunciation "0 rules" pattern).
        self._blend_count_label = QLabel("0 blends saved")
        self._blend_count_label.setObjectName("Counter")
        bl.addWidget(self._blend_count_label)

        layout.addWidget(self._blend_frame)

        return panel

    def _build_editor_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        title = QLabel("TEXT")
        title.setObjectName("SectionTitle")
        header_row.addWidget(title)

        # Open… button — sits next to the section title so the import
        # action is contextual to the editor pane. Style: smaller than
        # primary action buttons (padding/font-size shrunk) to keep
        # visual hierarchy correct.
        self._open_doc_btn = QPushButton("\U0001F4C2  Open…")
        self._open_doc_btn.setProperty("role", "ghost")
        self._open_doc_btn.setToolTip(
            "Open a TXT, PDF, or EPUB file.\n"
            "Tip: you can also drag a file straight onto the editor."
        )
        self._open_doc_btn.setStyleSheet(
            "padding: 4px 10px; font-size: 11px;"
        )
        header_row.addWidget(self._open_doc_btn)

        header_row.addStretch(1)
        self._counter_label = QLabel("0 chars  ·  0 words")
        self._counter_label.setObjectName("Counter")
        header_row.addWidget(self._counter_label)
        layout.addLayout(header_row)

        # Discoverability banner (Phase 2 power features).
        self._discoverability_banner = QLabel(
            '<html>💡 Try <b>SSML-lite controls</b> (<code>&lt;break&gt;</code>, <code>&lt;emphasis&gt;</code>, <code>&lt;prosody&gt;</code>) &mdash; tick <i>Apply SSML</i> on the right.<br>&nbsp;&nbsp;&nbsp;&nbsp;Or start a line with <code>[voice_name]:</code> for <b>Multi-Speaker Dialogue</b>.</html>'
        )
        self._discoverability_banner.setObjectName("DiscoverabilityBanner")
        self._discoverability_banner.setStyleSheet(
            "QLabel#DiscoverabilityBanner {"
            "color: #4338ca;"
            "background-color: rgba(99,102,241,0.08);"
            "border: 1px solid rgba(99,102,241,0.25);"
            "border-radius: 6px;"
            "padding: 6px 10px;"
            "font-size: 11px;"
            "}"
        )
        # PySide6 >= 6.2: scoped enums.  Older 6.0/6.1: only the bare
        # name `Qt.TextSelectableByMouse` exists.  Fall back gracefully.
        _ts_flag = getattr(
            getattr(Qt, "TextInteractionFlag", Qt),
            "TextSelectableByMouse",
            Qt.TextSelectableByMouse,
        )
        self._discoverability_banner.setTextInteractionFlags(_ts_flag)
        # Explicitly declare the QLabel's text format as RichText so the
        # banner does not silently degrade to plain text if a future
        # edit removes the <html>...</html> prefix from BANNER_HTML.
        self._discoverability_banner.setTextFormat(Qt.RichText)
        layout.addWidget(self._discoverability_banner)

        # `DocumentDropEditor` is a tiny QPlainTextEdit subclass that
        # intercepts dragged file paths. We can't receive drops on a
        # raw `QPlainTextEdit` because Qt's default drag handler only
        # accepts in-app text drags.
        self._editor = DocumentDropEditor()
        self._editor.setPlaceholderText(
            "Type or paste your text here.\n\n"
            "Tip: long inputs are split automatically by Kokoro's tokenizer —\n"
            "you can paste entire chapters without performance concerns.\n\n"
            "Or drop a .txt / .pdf / .epub file here, or click \u201cOpen\u2026\u201d."
        )
        f = QFont()
        f.setPointSize(11)
        self._editor.setFont(f)
        layout.addWidget(self._editor, 1)

        return panel

    def _build_controls_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # ---- Row 1: voice readout | speed | output path ----
        row1 = QHBoxLayout()
        row1.setSpacing(14)

        # Selected voice readout
        voice_box = QVBoxLayout()
        voice_box.setSpacing(2)
        voice_lbl = QLabel("SELECTED VOICE")
        voice_lbl.setObjectName("SectionTitle")
        self._voice_readout = QLabel(DEFAULT_VOICE)
        self._voice_readout.setObjectName("VoiceReadout")
        voice_box.addWidget(voice_lbl)
        voice_box.addWidget(self._voice_readout)
        voice_widget = QWidget()
        voice_widget.setLayout(voice_box)
        voice_widget.setMinimumWidth(220)
        voice_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row1.addWidget(voice_widget)

        # Speed (spin + slider)
        speed_box = QVBoxLayout()
        speed_box.setSpacing(4)
        speed_lbl = QLabel("SPEED")
        speed_lbl.setObjectName("SectionTitle")
        speed_row = QHBoxLayout()
        speed_row.setSpacing(8)
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setDecimals(2)
        self._speed_spin.setSingleStep(0.05)
        self._speed_spin.setRange(SPEED_MIN, SPEED_MAX)
        self._speed_spin.setValue(1.0)
        self._speed_spin.setMinimumWidth(82)
        self._speed_spin.setSuffix("x")
        speed_row.addWidget(self._speed_spin)
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(int(SPEED_MIN * self._SPEED_TICK),
                                    int(SPEED_MAX * self._SPEED_TICK))
        self._speed_slider.setValue(int(1.0 * self._SPEED_TICK))
        speed_row.addWidget(self._speed_slider, 1)
        speed_box.addWidget(speed_lbl)
        speed_box.addLayout(speed_row)
        row1.addLayout(speed_box, 1)

        # Output path
        out_box = QVBoxLayout()
        out_box.setSpacing(4)
        out_lbl = QLabel("OUTPUT FILE")
        out_lbl.setObjectName("SectionTitle")
        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        # Format dropdown — sits to the LEFT of the path field so it mirrors
        # the natural reading order "save this format to this path". Order
        # of items in OUTPUT_FORMATS ('wav', 'mp3', 'flac', 'ogg') is
        # intentional: WAV is the default & also the most portable across
        # playback pipelines.
        self._format_combo = QComboBox()
        self._format_combo.addItems([f.upper() for f in OUTPUT_FORMATS])
        self._format_combo.setToolTip(
            "Output audio format.\n"
            "  WAV  – uncompressed, largest files\n"
            "  FLAC – lossless compressed (~50% smaller)\n"
            "  MP3  – lossy, very compatible (requires lameenc)\n"
            "  OGG  – lossy Vorbis, smaller than MP3 at same quality"
        )
        self._format_combo.setMinimumWidth(86)
        # Render in monospace so vertical jitter from variable-width typefaces
        # doesn't reset the row height every time the user toggles a format.
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)
        self._format_combo.setFont(mono_font)
        out_row.addWidget(self._format_combo)
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText(
            "Path to save the generated audio…"
        )
        out_row.addWidget(self._output_edit, 1)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setProperty("role", "ghost")
        out_row.addWidget(self._browse_btn)
        out_box.addWidget(out_lbl)
        out_box.addLayout(out_row)
        row1.addLayout(out_box, 1)

        layout.addLayout(row1)

        # ---- Dialogue-mode chip (Phase 2) ---------------
        # Inline hint that pops in whenever the editor text contains
        # parseable `[voice_name]:` markers. Tooltip doubles as a
        # syntax cheatsheet so users learn what triggers it.
        chip_row_inner = QHBoxLayout()
        chip_row_inner.setSpacing(8)
        self._dialogue_chip = QLabel("")
        self._dialogue_chip.setObjectName("DialogueChip")
        self._dialogue_chip.setStyleSheet(
            "color: #9178FF; background-color: rgba(123,97,255,0.10);"
            " border: 1px solid rgba(123,97,255,0.35);"
            " border-radius: 6px; padding: 5px 10px;"
            " font-size: 11px; font-weight: 600;"
        )
        self._dialogue_chip.setToolTip(
            "Multi-speaker dialogue mode is ON.\n\n"
            "Type a [voice_name]: marker at the start of a line"
            " to switch voices mid-script:\n"
            "  [af_heart]: Hello!\n"
            "  [am_adam]: Hi there.\n\n"
            "Lines without markers keep the previous voice."
            " Lines before the first marker use the"
            " dropdown's currently-selected voice."
        )
        chip_row_inner.addWidget(self._dialogue_chip, 1)
        # Small ? button next to the chip pops a modal with
        # example scripts.
        self._dialogue_help_btn = QPushButton("?")
        self._dialogue_help_btn.setProperty("role", "ghost")
        self._dialogue_help_btn.setFixedSize(28, 26)
        self._dialogue_help_btn.setToolTip(
            "Show dialogue syntax examples"
        )
        self._dialogue_help_btn.clicked.connect(
            self._on_dialogue_help_clicked
        )
        chip_row_inner.addWidget(self._dialogue_help_btn)
        # Wrap in an outer QWidget so we can hide the entire row
        # (chip + button) when no markers are detected.
        self._dialogue_chip_row = QWidget()
        self._dialogue_chip_row.setLayout(chip_row_inner)
        self._dialogue_chip_row.setVisible(False)
        layout.addWidget(self._dialogue_chip_row)

        # ---- SSML-lite status chip (Phase 2) ---------------
        # Inline hint that pops in whenever (a) the SSML
        # Apply checkbox is on AND (b) the editor text
        # contains at least one SSML-lite tag. Hidden
        # otherwise so the controls row stays compact
        # for plain-text scripts.
        ssml_chip_row_inner = QHBoxLayout()  # SSML-GUI-E7
        ssml_chip_row_inner.setSpacing(8)
        self._ssml_chip = QLabel("")
        self._ssml_chip.setObjectName("SSMLChip")
        # Default emerald-on-dark style; the refresh
        # slot swaps to amber when SSML collides with
        # multi-speaker dialogue (engine silently drops
        # SSML in that case).
        self._ssml_chip.setStyleSheet(
            "color: #10B981; background-color: rgba(16,185,129,0.10);"
            " border: 1px solid rgba(16,185,129,0.35);"
            " border-radius: 6px; padding: 5px 10px;"
            " font-size: 11px; font-weight: 600;"
        )
        self._ssml_chip.setToolTip(
            "SSML-lite markers detected in the editor.\n"
            "\n"
            "Click ? on the right for the full syntax reference."
        )
        ssml_chip_row_inner.addWidget(self._ssml_chip, 1)
        self._ssml_help_btn = QPushButton("?")
        self._ssml_help_btn.setProperty("role", "ghost")
        self._ssml_help_btn.setFixedSize(28, 26)
        self._ssml_help_btn.setToolTip(
            "Show SSML-lite syntax examples"
        )
        self._ssml_help_btn.clicked.connect(
            self._on_ssml_help_clicked
        )
        ssml_chip_row_inner.addWidget(self._ssml_help_btn)
        self._ssml_chip_row = QWidget()
        self._ssml_chip_row.setLayout(ssml_chip_row_inner)
        self._ssml_chip_row.setVisible(False)
        layout.addWidget(self._ssml_chip_row)
        # ---- Row 2: action buttons ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        # Pronunciation toggle + edit — sits at the START of the
        # action row so it's near "what gets synthesised" (Generate),
        # not "what's already been saved" (Open Folder). The count
        # label is intentionally small (uses Counter QSS) so it
        # stays out of the way after the user is done with it.
        self._pron_checkbox = QCheckBox("Apply rules")
        self._pron_checkbox.setChecked(True)
        self._pron_checkbox.setToolTip(
            "When enabled, every Generate / Preview run rewrites the "
            "input text via the pronunciation dictionary before synthesis."
        )
        row2.addWidget(self._pron_checkbox)

        self._pron_edit_btn = QPushButton("📖  Dict…")
        self._pron_edit_btn.setProperty("role", "ghost")
        self._pron_edit_btn.setToolTip(
            "Edit the pronunciation dictionary.\n"
            f"Stored at: {_default_output_dir() / 'pronunciation.json'}"
        )
        row2.addWidget(self._pron_edit_btn)

        self._pron_count_label = QLabel("0 rules")
        self._pron_count_label.setObjectName("Counter")
        row2.addSpacing(12)
        row2.addWidget(self._pron_count_label)

        # SSML-lite opt-in checkbox (Phase 2).
        # Default OFF so the classic plain-text path
        # stays the baseline; users flip it on when
        # they want <break>/<emphasis>/<prosody> tags
        # to take effect.
        self._ssml_checkbox = QCheckBox("Apply SSML")  # SSML-GUI-E6
        self._ssml_checkbox.setChecked(False)
        self._ssml_checkbox.setToolTip(
            "When enabled, the editor text is routed "
            "through the SSML-lite parser before synthesis.\n"
            "\n"
            "Supported tags (see ? button next to the chip):\n"
            "  <break time=\"Xs\"/>  insert X seconds of silence\n"
            "  <emphasis>w</emphasis> slow down word w\n"
            "  <prosody rate=\"fast\">speeds up wrapped text</prosody>"
        )
        row2.addSpacing(12)
        row2.addWidget(self._ssml_checkbox)
        # Tiny '?' ghost button sat next to Apply SSML so users can
        # open the SSML-lite help dialog without hunting through menus.
        self._ssml_action_help_btn = QPushButton("?")
        self._ssml_action_help_btn.setProperty("role", "ghost")
        self._ssml_action_help_btn.setFixedSize(28, 26)
        self._ssml_action_help_btn.setToolTip("Open SSML-lite help")
        self._ssml_action_help_btn.clicked.connect(self._on_ssml_help_clicked)
        row2.addWidget(self._ssml_action_help_btn)

        # Streaming playback toggle (Phase 2). Default ON — this is the
        # headline feature. Disabled when the platform reports no audio
        # back-end (headless CI / RDP / Linux container without a sound
        # server). Tooltip doubles as a one-line explanation AND as the
        # place users see the unavailability reason.
        self._stream_checkbox = QCheckBox("▶ Stream")
        # Honest default: only checked when streaming is actually
        # available on this platform. With 
        # the checkbox is unchecked + disabled and synthesis falls
        # back to file-based playback transparently.
        self._stream_checkbox.setChecked(self._stream_available)
        self._stream_checkbox.setToolTip(
            "Hear audio in real time as Kokoro generates it. "
            "Disable to use the standard play-after-synthesis flow.\n"
            f"{self._stream_disabled_reason}".rstrip()
        )
        self._stream_checkbox.setEnabled(self._stream_available)
        row2.addSpacing(8)
        row2.addWidget(self._stream_checkbox)

        self._play_btn = QPushButton("▶  Play last")
        self._play_btn.setProperty("role", "ghost")
        self._play_btn.setEnabled(False)
        row2.addWidget(self._play_btn)

        self._stop_audio_btn = QPushButton("■  Stop audio")
        self._stop_audio_btn.setProperty("role", "ghost")
        self._stop_audio_btn.setEnabled(False)
        row2.addWidget(self._stop_audio_btn)

        row2.addStretch(1)

        self._open_folder_btn = QPushButton("📂  Open output folder")
        self._open_folder_btn.setProperty("role", "ghost")
        row2.addWidget(self._open_folder_btn)

        self._stop_btn = QPushButton("■  Stop generation")
        self._stop_btn.setProperty("role", "danger")
        self._stop_btn.setVisible(False)
        row2.addWidget(self._stop_btn)

        self._generate_btn = QPushButton("▶  Generate")
        self._generate_btn.setProperty("role", "primary")
        row2.addWidget(self._generate_btn)

        layout.addLayout(row2)

        return panel

    def _build_status_bar(self) -> QStatusBar:
        sb = QStatusBar(self)
        sb.setSizeGripEnabled(False)
        self._status_label = QLabel("Ready.")
        self._status_label.setStyleSheet("font-weight: 600;")
        sb.addWidget(self._status_label, 1)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setMaximumWidth(240)
        self._progress.setFixedHeight(14)
        self._progress.setVisible(False)
        self._progress.setObjectName("Indeterminate")
        sb.addPermanentWidget(self._progress)
        return sb

    # ----------------------------------------------------------- Signals
    def _wire_signals(self) -> None:
        # Editor behavior
        self._editor.textChanged.connect(self._on_text_changed)

        # SSML-lite chip refresh on every keystroke
        # (Phase 2). _refresh_ssml_chip itself
        # short-circuits on detect_ssml(text) so this
        # stays sub-millisecond for plain-text scripts.
        self._editor.textChanged.connect(  # SSML-GUI-E10
            lambda: self._refresh_ssml_chip(
                self._editor.toPlainText()
            )
        )
        # Discoverability banner auto-hide: once the user has typed
        # more than ~30 characters we assume they got the hint. The
        # isVisible() guard short-circuits so post-hide keystrokes
        # are cheap no-ops (no toPlainText() string copy).
        if self._discoverability_banner is not None:
            _banner = self._discoverability_banner
            _ed = self._editor
            # SingleShotConnection: the auto-hide connector only needs to
            # fire ONCE (after the threshold is first crossed).  Using a
            # defensive getattr for cross-version PySide6 compat mirrors
            # the strategy used in the banner setTextInteractionFlags call.
            # Bare form is portable across all PySide6 6.0+ (re-export of the scoped enum).
            _single_shot = Qt.SingleShotConnection
            self._editor.textChanged.connect(
                lambda _b=_banner, _e=_ed: (
                    _b.setVisible(False)
                    if (
                        _b.isVisible()
                        and len(_e.toPlainText()) > 80
                    )
                    else None
                ),
                _single_shot,
            )
        # Drag-and-drop: the editor's `fileDropped` signal bubbles the
        # absolute path of the dropped file; main window decides whether
        # to overwrite / append.
        self._editor.fileDropped.connect(self._load_document_into_editor)
        # Multi-file drops: editor emits `multiDropRejected(count)` so we
        # can surface a status-bar hint instead of silently dropping.
        self._editor.multiDropRejected.connect(self._on_multi_drop_rejected)
        # Toolbar button to open the file picker.
        self._open_doc_btn.clicked.connect(self._on_open_document_clicked)

        # Pronunciation controls.
        self._pron_checkbox.toggled.connect(self._on_pron_toggle)
        self._pron_edit_btn.clicked.connect(self._on_edit_pronunciation_clicked)

        # SSML-lite checkbox (Phase 2). Toggling
        # immediately re-evaluates the chip so users
        # see the chip appear or vanish the same tick
        # they flip the checkbox.
        self._ssml_checkbox.toggled.connect(  # SSML-GUI-E11
            lambda _checked: self._refresh_ssml_chip(
                self._editor.toPlainText()
            )
        )

        # Streaming toggle: when flipped off mid-run, mirrors no behaviour
        # change because the sink is already provisioned/teardown-managed
        # by the synthesis lifecycle. The slot exists so the user gets
        # a tiny status-bar echo of the current setting.
        self._stream_checkbox.toggled.connect(self._on_stream_toggle)

        # Voice list (filter dropdown removed — only voice selection matters).
        self._voice_list.currentItemChanged.connect(self._on_voice_changed)


        # Voice Blending (Phase 2). Alpha slider / spin sync MUST
        # be guarded against valueChanged feedback loop (slider
        # spinner triggers spin, spin triggers slider).
        if self._blend_alpha_slider is not None:
            self._blend_alpha_slider.valueChanged.connect(
                self._on_alpha_slider_changed
            )
        if self._blend_alpha_spin is not None:
            self._blend_alpha_spin.valueChanged.connect(
                self._on_alpha_spin_changed
            )
        # Voice A / Voice B dropdown auto-update the placeholder
        # for the Name field (only when empty).
        if self._blend_voice_a_combo is not None:
            self._blend_voice_a_combo.currentIndexChanged.connect(
                self._on_blend_voice_selection_changed
            )
            self._blend_voice_b_combo.currentIndexChanged.connect(
                self._on_blend_voice_selection_changed
            )
        # Save / Preview buttons + name-field editing-finished
        # trigger the auto-name refresh on commit.
        if self._blend_save_btn is not None:
            self._blend_save_btn.clicked.connect(
                self._on_save_blend_clicked
            )
        if self._blend_preview_btn is not None:
            self._blend_preview_btn.clicked.connect(
                self._on_preview_blend_clicked
            )
        if self._blend_name_edit is not None:
            self._blend_name_edit.editingFinished.connect(
                self._refresh_voice_readout
            )

        # Speed (avoid feedback loops between spin and slider)
        self._speed_spin.valueChanged.connect(self._on_speed_spin_changed)
        self._speed_slider.valueChanged.connect(self._on_speed_slider_changed)

        # Output path
        self._output_edit.editingFinished.connect(self._refresh_output_path_validity)
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)

        # Action buttons
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._play_btn.clicked.connect(self._on_play_clicked)
        self._stop_audio_btn.clicked.connect(self._on_stop_audio_clicked)
        self._open_folder_btn.clicked.connect(self._on_open_folder_clicked)

        # Settings / info dialog (gear button)
        self._settings_btn.clicked.connect(self._on_settings_clicked)

        # Media player
        self._player.playbackStateChanged.connect(self._on_playback_state)

    # --------------------------------------------------------- Shortcuts
    def _wire_shortcuts(self) -> None:
        """Wire keyboard shortcuts as window-level QActions.

        Implementation choices (see PLAN.md research notes on
        QAction vs QShortcut):

          * **QAction, not QShortcut** — QActions auto-sync with future
            menus / toolbars / tooltips, support `QKeySequence.StandardKey`
            for cross-platform shortcuts (Cmd on macOS, Ctrl on Win/Linux),
            and integrate with our QSS-driven dark theme.
          * **`Qt.WindowShortcut` context** so accelerators fire regardless
            of which child widget currently has focus.
          * **`QKeySequence.StandardKey`** for Open / Save / Undo / Redo
            so Mac users get Cmd+O / Cmd+S / Cmd+Z automatically. The
            app-specific Generate / Preview shortcuts use literal strings.
          * **Space toggles play/pause** of the last generated audio. This
            is implemented via `installEventFilter` on `_editor` instead
            of a `QAction("Space")` shortcut. A QAction with
            `Qt.WindowShortcut` would consume Space unconditionally and
            break "type a space" in the editor. The eventFilter only
            intercepts Space when there's already an audio file, so it
            transparently degrades to "Space inserts a space" otherwise.
        """
        # Ctrl+G — Generate
        self._gen_act = QAction("Generate", self)
        self._gen_act.setShortcut("Ctrl+G")
        self._gen_act.setShortcutContext(Qt.WindowShortcut)
        self._gen_act.setToolTip("Synthesise the editor text (Ctrl+G)")
        self._gen_act.triggered.connect(self._on_generate_clicked)
        self.addAction(self._gen_act)

        # Ctrl+P — Preview selected voice
        self._prev_act = QAction("Preview voice", self)
        self._prev_act.setShortcut("Ctrl+P")
        self._prev_act.setShortcutContext(Qt.WindowShortcut)
        self._prev_act.setToolTip("Play a short voice sample (Ctrl+P)")
        self._prev_act.triggered.connect(self._on_preview_clicked)
        self.addAction(self._prev_act)

        # StandardKey.Open → Ctrl+O / Cmd+O — Open document
        self._open_act = QAction("Open document…", self)
        self._open_act.setShortcut(QKeySequence.StandardKey.Open)
        self._open_act.setShortcutContext(Qt.WindowShortcut)
        self._open_act.triggered.connect(self._on_open_document_clicked)
        self.addAction(self._open_act)

        # StandardKey.Save → Ctrl+S / Cmd+S — Save editor text as .txt
        # (See `_on_save_text_clicked` for why we chose editor-text export
        # over audio "Save As" — Ctrl+G already handles audio writes.)
        self._save_act = QAction("Save text as…", self)
        self._save_act.setShortcut(QKeySequence.StandardKey.Save)
        self._save_act.setShortcutContext(Qt.WindowShortcut)
        self._save_act.setToolTip(
            "Save the current editor contents to a .txt file (Ctrl+S)."
        )
        self._save_act.triggered.connect(self._on_save_text_clicked)
        self.addAction(self._save_act)

        # StandardKey.Undo → Ctrl+Z / Cmd+Z — editor undo
        self._undo_act = QAction("Undo", self)
        self._undo_act.setShortcut(QKeySequence.StandardKey.Undo)
        self._undo_act.setShortcutContext(Qt.WindowShortcut)
        self._undo_act.triggered.connect(self._editor.undo)
        self.addAction(self._undo_act)
        # Keep enabled state synced with the editor's undo stack depth.
        self._editor.undoAvailable.connect(self._undo_act.setEnabled)

        # StandardKey.Redo → Ctrl+Y on Win, Cmd+Shift+Z on macOS
        self._redo_act = QAction("Redo", self)
        self._redo_act.setShortcut(QKeySequence.StandardKey.Redo)
        self._redo_act.setShortcutContext(Qt.WindowShortcut)
        self._redo_act.triggered.connect(self._editor.redo)
        self.addAction(self._redo_act)
        self._editor.redoAvailable.connect(self._redo_act.setEnabled)

        # Space → play/pause last audio (event-filter based; see below).
        self._editor.installEventFilter(self)

    # -------------------------------------- Event filter: Space in editor
    def eventFilter(self, obj, event) -> bool:
        """Route Space to play/pause *only* when there's audio ready.

        The window-level policy is: if the user pressed Space while the
        editor has focus AND there's a generated audio file ready to
        play, toggle play/pause. Otherwise fall through to the default
        edit behaviour (insert a space). This matches the convention of
        popular DAWs and media apps without breaking the editor's
        typing flow when no audio is loaded.
        """
        if (
            obj is self._editor
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
            and self._can_toggle_playback()
        ):
            self._toggle_playback()
            return True  # consumed — don't insert a space character
        return super().eventFilter(obj, event)

    # ----------------------- Helper / slot: play/pause toggle
    def _can_toggle_playback(self) -> bool:
        """True if a Space (or any other play/pause trigger) should fire."""
        # Don't intercept toggling while a fresh synthesis is in flight;
        # the user almost certainly meant Space-as-character, not "stop
        # my current generation so I can play the previous audio".
        if self._worker is not None and self._worker.isRunning():
            return False
        # If QAudioSink is still draining the stream (worker done, but
        # the buffer hasn't reached EOS yet, or hasn't transitioned to
        # IdleState), toggling QMediaPlayer would start a second audio
        # source on the same hardware — ugly. Refuse the toggle then.
        if self._ring_buffer is not None and not self._ring_buffer.is_eos():
            return False
        return bool(
            self._last_audio_path
            and Path(self._last_audio_path).exists()
        )

    def _toggle_playback(self) -> None:
        """Toggle the QMediaPlayer state (play / pause / restart from stop)."""
        if not self._can_toggle_playback():
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
        else:
            # StoppedState or EndedState — start fresh from the beginning.
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(self._last_audio_path))
            self._player.play()

    # --------------------------------------- Slot: save editor text as .txt
    def _on_save_text_clicked(self) -> None:
        """Save the editor contents to a plain `.txt` file (Ctrl+S).

        TTS scripts tend to be substantially longer than what users want
        to render in one go; saving the working draft to disk is a
        useful workflow step. We deliberately save plain text only —
        no metadata, no settings — so the file stays portable to any
        other editor or editor-of-record pipeline.

        Note: this complements (rather than duplicates) Ctrl+G:
          * Ctrl+G  → synthesise the text in the editor to an audio file.
          * Ctrl+S  → save the text in the editor to a `.txt` file.
        """
        text = self._editor.toPlainText()
        if not text.strip():
            QMessageBox.information(
                self, "Nothing to save", "The editor is empty."
            )
            return
        start_dir = str(_default_output_dir())
        default_name = "kokoro_script.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save text as",
            str(Path(start_dir) / default_name),
            "Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return  # user cancelled
        if not path.lower().endswith(".txt"):
            path += ".txt"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self._status_label.setText(
                f"Saved {len(text):,} chars  ·  {Path(path).name}"
            )
        except OSError as e:
            QMessageBox.critical(
                self, "Save failed", f"{type(e).__name__}: {e}"
            )

    # ----------------------------------------------------------- Voice list
    def _repopulate_voice_list(self, lang_code: Optional[str]) -> None:
        """(Re)build the voice list, applying the language filter."""
        voices = list_voices(lang=lang_code)
        self._voice_list.blockSignals(True)
        self._voice_list.clear()
        # Show a friendly placeholder when no voices are bundled for the
        # selected language (e.g. Japanese needs misaki[ja] + a voice pack).
        if not voices:
            # Differentiate the placeholder hint: espeak-ng languages can
            # still be spoken by any English voice (just not represented as
            # a separate voice), while Japanese/Mandarin genuinely need a
            # Kokoro voice pack to work at all.
            if lang_code in {"j", "z"}:
                msg = (
                    "No voices bundled for Japanese / Mandarin.\n\n"
                    "Install misaki[ja] or misaki[zh] (plus the matching "
                    "Kokoro voice pack) to enable these languages,\n"
                    "or pick an English voice and pass lang_code explicitly."
                )
            elif lang_code in {"e", "f", "h", "i", "p"}:
                msg = (
                    "No native voices for this language.\n\n"
                    "English voices (af_heart, am_adam …) still speak it via "
                    "espeak-ng.\nSwitch to 'All languages' to pick one."
                )
            else:
                msg = "No voices bundled for this language."
            placeholder = QListWidgetItem(msg)
            placeholder.setFlags(Qt.NoItemFlags)  # not selectable / non-interactive
            self._voice_list.addItem(placeholder)
        for voice_name in voices:
            info = get_voice_info(voice_name)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, voice_name)
            gender = "Female" if info["gender"] == "f" else "Male"
            rich = (
                f"<div style='font-weight:600; font-size:13px;'>"
                f"{voice_name}"
                f" &nbsp;<span style='color:#9178FF; font-weight:600; "
                f"font-size:10px; letter-spacing:1px;'>"
                f"GRADE {info['grade']}</span></div>"
                f"<div style='color:#9DA0A8; font-size:11px;'>"
                f"{info['lang_label']} · {gender}</div>"
                f"<div style='font-size:11px;'>{info['description']}</div>"
            )
            # QListWidgetItem.setText does NOT render rich text — embed a
            # QLabel with Qt.RichText so the styled spans actually apply.
            label = QLabel()
            label.setTextFormat(Qt.RichText)
            label.setText(rich)
            label.setWordWrap(True)
            label.setContentsMargins(0, 0, 0, 0)
            # Pin a sensible width BEFORE measuring the height, otherwise the
            # natural size hint is computed at width=0 and the row height
            # becomes wrong on resizes.
            row_width = max(self._voice_list.viewport().width() - 24, 220)
            label.setMinimumWidth(row_width)
            item.setSizeHint(QSize(row_width, label.sizeHint().height() + 8))
            label.setToolTip(
                f"<b>{voice_name}</b><br>"
                f"Language: {info['lang_label']} ({info['lang']})<br>"
                f"Gender: {gender}<br>"
                f"Grade: {info['grade']}"
            )
            self._voice_list.addItem(item)
            self._voice_list.setItemWidget(item, label)

        # Phase 2 - Voice Blending: append saved blends below
        # the built-in voices. Each blend item carries the same
        # UserRole payload (voice name = blend key) so the rest
        # of the GUI treats them as first-class voices. We tag
        # blend items with UserRole+1 and stash the composition
        # dict at UserRole+2 so future code can distinguish
        # them without parsing display text.
        for blend_name, blend in self._loaded_blends.items():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, blend_name)
            item.setData(Qt.UserRole + 1, True)
            item.setData(Qt.UserRole + 2, {
                "voice_a": blend.voice_a,
                "voice_b": blend.voice_b,
                "alpha": blend.alpha,
            })
            pct_a = int(round(blend.alpha * 100))
            pct_b = 100 - pct_a
            rich = (
                f"<div style='font-weight:600; font-size:13px;'>"
                f"🎛 {blend_name}"
                f" &nbsp;<span style='color:#9178FF; font-weight:600;"
                f" font-size:10px; letter-spacing:1px;'>BLEND</span>"
                f"</div>"
                f"<div style='color:#9DA0A8; font-size:11px;'>"
                f"{pct_a}% {blend.voice_a} + {pct_b}% {blend.voice_b}"
                f"</div>"
            )
            label = QLabel()
            label.setTextFormat(Qt.RichText)
            label.setText(rich)
            label.setWordWrap(True)
            label.setContentsMargins(0, 0, 0, 0)
            row_width = max(self._voice_list.viewport().width() - 24, 220)
            label.setMinimumWidth(row_width)
            item.setSizeHint(QSize(row_width, label.sizeHint().height() + 8))
            label.setToolTip(
                f"<b>{blend_name}</b> (custom blend)<br>"
                f"A: {blend.voice_a} ({pct_a}%)<br>"
                f"B: {blend.voice_b} ({pct_b}%)<br><br>"
                f"Stored at: Documents/KokoroStudio/voice_blends.json"
            )
            self._voice_list.addItem(item)
            self._voice_list.setItemWidget(item, label)

        # Try to keep the current voice selected; else pick the first available.
        keep_idx = -1
        for i in range(self._voice_list.count()):
            if self._voice_list.item(i).data(Qt.UserRole) == self._current_voice:
                keep_idx = i
                break
        voice_changed = False
        if keep_idx >= 0:
            self._voice_list.setCurrentRow(keep_idx)
        elif self._voice_list.count() > 0:
            self._voice_list.setCurrentRow(0)
            new_voice = self._voice_list.currentItem().data(Qt.UserRole)
            if new_voice != self._current_voice:
                self._current_voice = new_voice
                voice_changed = True
        else:
            self._current_voice = ""
            voice_changed = True
        self._voice_list.blockSignals(False)
        self._refresh_voice_readout()
        # If the filter forced a different voice, refresh both the output
        # filename and the button states so they stay in sync.
        if voice_changed:
            self._refresh_output_path()
            self._update_button_states()

    # ----------------- Slot: dialogue chip refresh (Phase 2)
    def _refresh_dialogue_chip(self, text: str) -> None:
        """Show / hide the inline multi-speaker chip row.

        Cheap regex pre-check (`detect_dialogue`) runs on every
        keystroke; the full parser only runs when at least one
        marker is present so the row stays hidden for
        single-speaker scripts (no GUI clutter).
"""
        try:
            from kokoro_studio.dialogue import (
                detect_dialogue, parse_dialogue, summarize_voices,
            )
        except ImportError:
            return  # dialogue module gone; skip silently
        # Use getattr defensively because textChanged can fire
        # before `_build_controls_panel` has set up the chip
        # widget (rare in practice but possible if a caller does
        # something like `setPlainText` from __init__).
        chip = getattr(self, "_dialogue_chip", None)
        row = getattr(self, "_dialogue_chip_row", None)
        if chip is None or row is None:
            return  # pre-build or mid-teardown window
        if not detect_dialogue(text):
            row.setVisible(False)
            return
        # Phase 2 - Voice Blending: blend names share the
        # dialogue-marker regex with built-ins so we widen
        # `known_voices` so user-defined blends don't trigger
        # fallback warnings during the multi-speaker parse.
        _known = set(VOICES.keys()) | set(self._loaded_blends.keys())
        _fallback = self._current_voice or DEFAULT_VOICE
        # Always fall back to a builtin so the per-segment
        # KPipeline calls don't need to handle a blend-as-default
        # edge case (blends are resolved lazily by the engine
        # per-segment anyway, so a saved blend in `_current_voice`
        # still works downstream via the tensor resolution path).
        if _fallback not in VOICES and _fallback in self._loaded_blends:
            _fallback = DEFAULT_VOICE
        segs, _ = parse_dialogue(
            text,
            default_voice=_fallback,
            known_voices=_known,
        )
        summary = summarize_voices(segs)
        if summary:
            chip.setText(
                f"\U0001F3AD {len(segs)} speaker turn(s): {summary}"
            )
            row.setVisible(True)
        else:
            row.setVisible(False)

    # ----------------- Slot: per-segment status updates

    # ----------------- Slot: SSML-lite chip refresh (Phase 2)
    def _refresh_ssml_chip(self, text: str) -> None:  # SSML-GUI-E8
        """Show / hide the inline SSML-lite chip row.

        Hidden when EITHER (a) the Apply SSML checkbox
        is OFF, OR (b) the text doesn't contain SSML-
        lite markup. When the multi-speaker dialogue
        chip is also visible, SSML is silently ignored
        by the engine; we surface this in chip text +
        amber colour so the user doesn't think their
        tags are doing something.
        """
        # getattr defends against textChanged firing
        # before the chip widget is built (parity with
        # _refresh_dialogue_chip).
        chip = getattr(self, "_ssml_chip", None)
        row = getattr(self, "_ssml_chip_row", None)
        cb = getattr(self, "_ssml_checkbox", None)
        if chip is None or row is None or cb is None:
            return  # pre-build or mid-teardown window
        if not cb.isChecked():
            row.setVisible(False)
            return
        try:
            from kokoro_studio.ssml import (
                detect_ssml, parse_ssml, summarize_ssml,
            )
        except ImportError:
            row.setVisible(False)
            return
        if not detect_ssml(text):
            row.setVisible(False)
            return
        segs = parse_ssml(text)
        summary = summarize_ssml(segs)
        if not summary:
            row.setVisible(False)
            return
        # If the multi-speaker dialogue chip is
        # currently visible, SSML is silently ignored
        # by the engine -- surface this in the chip
        # so the user doesn't think their tags are
        # taking effect.
        dialogue_row_visible = bool(
            getattr(self, "_dialogue_chip_row", None)
            and self._dialogue_chip_row.isVisible()
        )
        if dialogue_row_visible:
            chip.setStyleSheet(
                "color: #F59E0B; background-color: rgba(245,158,11,0.10);"
                " border: 1px solid rgba(245,158,11,0.35);"
                " border-radius: 6px; padding: 5px 10px;"
                " font-size: 11px; font-weight: 600;"
            )
            chip.setText(f"\u26A1 SSML: {summary} (ignored in dialogue mode)")
        else:
            chip.setStyleSheet(
                "color: #10B981; background-color: rgba(16,185,129,0.10);"
                " border: 1px solid rgba(16,185,129,0.35);"
                " border-radius: 6px; padding: 5px 10px;"
                " font-size: 11px; font-weight: 600;"
            )
            chip.setText(f"\u26A1 SSML: {summary}")
        row.setVisible(True)
    def _on_segment_started(self, seg_idx: int) -> None:
        """Update status bar with the active speaker on transitions.

        Connected to `SynthesisWorker.segment_started`. Resolves the
        voice name from `self._current_segments` so we don't
        re-parse the editor text on every chunk arrival. In
        single-speaker mode the segment list is empty and we
        leave the chunk-based progress to do its job.
"""
        if not self._current_segments:
            return
        if seg_idx >= len(self._current_segments):
            return
        voice = self._current_segments[seg_idx].voice
        total = len(self._current_segments)
        self._status_label.setText(
            f"Speaker {seg_idx + 1}/{total}: {voice} \u00b7"
            f" generating..."
        )

    # ----------------- Slot: dialogue help button (Phase 2)
    def _on_dialogue_help_clicked(self) -> None:
        """Popup a modal dialog with multi-speaker syntax examples.

        Triggered by the small `?` button next to the inline chip.
        Static content; cheap to construct on each click.
"""
        # Module-level constant avoids re-parsing the literal on
        # every click. Defined right above the class so any user
        # can edit it without hunting through nested quotes.
        dlg = QDialog(self)
        dlg.setWindowTitle("Multi-Speaker Dialogue Mode")
        dlg.resize(640, 480)
        dlg.setStyleSheet(SETTINGS_QSS)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        title = QLabel("\U0001F3AD  Multi-Speaker Dialogue Mode")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "Put a <code>[voice_name]:</code> marker at the start of a"
            " line to switch voices mid-script. Everything below the"
            " marker (until the next marker, or end of file) is"
            " spoken in that voice.<br><br>"
            "<b>Tips:</b>"
            "<ul>"
            "<li>Lines BEFORE the first marker use the dropdown's"
            " currently-selected voice.</li>"
            "<li>Lines without a marker stay on the previous voice"
            " \u2014 useful for multi-line turns.</li>"
            "<li>Unknown voice tokens fall back to the dropdown's"
            " default (with a warning).</li>"
            "<li>A short silence is inserted between segments so"
            " turns feel natural.</li>"
            "</ul>"
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setObjectName("SettingsBlock")
        intro.setOpenExternalLinks(True)
        root.addWidget(intro)

        sample = QPlainTextEdit(dlg)
        sample.setReadOnly(True)
        sample.setStyleSheet(
            "background-color: #1F2329; color: #E8EAED;"
            " border: 1px solid #252932; border-radius: 8px;"
            " padding: 10px;"
            " font-family: 'Consolas', 'Cascadia Code',"
            " 'JetBrains Mono', monospace;"
            " font-size: 12px;"
        )
        # Triple-quoted string dodges the adjacent-literal
        # concatenation pitfall that bit earlier scripts.
        sample.setPlainText(DIALOGUE_HELP_SAMPLE)
        sample.setMinimumHeight(180)
        root.addWidget(sample, 1)

        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)
        close_btn.setText("Got it")
        close_btn.setProperty("role", "primary")
        bbox.accepted.connect(dlg.accept)
        # Insert button: drops the runnable DIALOGUE_HELP_TTS_SAMPLE
        # into the editor without the user copy-pasting by hand.
        # ActionRole buttons don't auto-close.  Closure-based
        # insert+accept (QDialogButtonBox has no clickedButton() API).
        def _handle_dialogue_insert():
            # setPlainText MUST run before dlg.accept() or the
            # editor update is lost on modal event-loop return.
            self._editor.setPlainText(DIALOGUE_HELP_TTS_SAMPLE)
            dlg.accept()
        insert_btn = bbox.addButton(
            "Insert sample script",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        insert_btn.clicked.connect(_handle_dialogue_insert)
        root.addWidget(bbox)

        dlg.exec()

    # ----------------- Slot: SSML-lite help button (Phase 2)
    def _on_ssml_help_clicked(self) -> None:  # SSML-GUI-E9
        """Popup a modal dialog with SSML-lite tag examples.

        Triggered by the small ? button next to the
        inline chip. Mirrors
        _on_dialogue_help_clicked so the two feature
        entrypoints feel identical.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("SSML-lite Controls")
        dlg.resize(640, 480)
        dlg.setStyleSheet(SETTINGS_QSS)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        title = QLabel("\u26A1  SSML-lite Controls")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "Tag-style controls for inline pauses, "
            "emphasis, and rate override. Type the "
            "literal markup into the editor and tick "
            "<b>Apply SSML</b>"
            " on the controls panel.<br><br>"
            "<b>Notes:</b>"
            "<ul>"
            "<li>SSML-lite and multi-speaker dialogue are"
            " mutually exclusive. Dialogue mode wins"
            "the chip turns amber to warn you.</li>"
            "<li>Tags work inside sentences: <code>he said"
            " &lt;emphasis&gt;wait&lt;/emphasis&gt;!</code>"
            " is valid.</li>"
            "<li>No nesting: open and close each tag in"
            " the order they appear; unclosed tags are"
            " kept literal as text and surface a stderr"
            " warning.</li>"
            "</ul>"
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setObjectName("SettingsBlock")
        intro.setOpenExternalLinks(True)
        root.addWidget(intro)

        sample = QPlainTextEdit(dlg)
        sample.setReadOnly(True)
        sample.setStyleSheet(
            "background-color: #1F2329; color: #E8EAED;"
            " border: 1px solid #252932; border-radius: 8px;"
            " padding: 10px;"
            " font-family: 'Consolas', 'Cascadia Code',"
            " 'JetBrains Mono', monospace;"
            " font-size: 12px;"
        )
        sample.setPlainText(SSML_HELP_SAMPLE)
        sample.setMinimumHeight(180)
        root.addWidget(sample, 1)

        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)
        close_btn.setText("Got it")
        close_btn.setProperty("role", "primary")
        bbox.accepted.connect(dlg.accept)
        # Insert button: drops a runnable SSML-lite sample AND ticks
        # the 'Apply SSML' checkbox so the tags take effect.
        # Same closure-based insert+accept pattern as the dialogue handler.
        def _handle_ssml_insert():
            # setPlainText + setChecked MUST run before dlg.accept()
            # or the editor / checkbox updates are lost on return.
            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)
            self._ssml_checkbox.setChecked(True)
            dlg.accept()
        insert_btn = bbox.addButton(
            "Insert sample + enable SSML",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        insert_btn.clicked.connect(_handle_ssml_insert)
        root.addWidget(bbox)

        dlg.exec()

    def _refresh_voice_readout(self) -> None:
        """Update the SELECTED VOICE label with the current voice.

        Called from `_repopulate_voice_list` and `_on_voice_changed`
        so the readout always reflects `self._current_voice`. When
        the voice library is empty (e.g. user picked a non-English
        lang that has no bundled voices) we render a dash instead
        of the default 'af_heart' to make the empty state obvious.
"""
        if not self._current_voice:
            self._voice_readout.setText("—")
            return
        # Phase 2 - Voice Blending: when the active voice is a
        # saved blend we render its composition instead of the
        # built-in grade metadata (the engine resolves the name
        # to a tensor transparently during Generate).
        if self._current_voice in self._loaded_blends:
            _b = self._loaded_blends[self._current_voice]
            _pct_a = int(round(_b.alpha * 100))
            _pct_b = 100 - _pct_a
            self._voice_readout.setText(
                f"🎛 {self._current_voice}"
                f"  ·  {_pct_a}% {_b.voice_a} + {_pct_b}% {_b.voice_b}"
            )
            return
        info = get_voice_info(self._current_voice)
        self._voice_readout.setText(
            f"{self._current_voice}  ·  Grade {info['grade']}"
        )

    # ----- Voice list helpers (pre-existing) -----
    def _on_voice_changed(self, current: Optional[QListWidgetItem],
                          _previous: Optional[QListWidgetItem]) -> None:
        if current is None:
            return
        voice = current.data(Qt.UserRole)
        if not voice or voice == self._current_voice:
            # Avoid re-triggering when we re-populate with the same voice.
            self._refresh_voice_readout()
            return
        self._current_voice = voice
        self._refresh_voice_readout()
        self._refresh_output_path()
        self._update_button_states()

    # (language filter slot removed — flat list now)

    # ------------------------------------------------------- Slot: editor
    def _on_text_changed(self) -> None:
        text = self._editor.toPlainText()
        chars = len(text)
        words = len(text.split()) if text.strip() else 0
        self._counter_label.setText(f"{chars:,} chars  ·  {words:,} words")
        self._update_button_states()
        # Multi-speaker dialogue detection. Cheap regex-based check
        # runs on every keystroke; the full parser only runs when
        # the detector finds at least one marker (otherwise the
        # chip stays hidden).
        self._refresh_dialogue_chip(text)

    # ---------------------------------------- Slot: pronunciation
    def _load_pron_dict(self) -> None:
        """Read the JSON dictionary from disk into `self._pron_rules`.

        Silently falls back to an empty dict on any failure (missing
        file, malformed JSON, schema mismatch) and reflects the count
        in `_pron_count_label` so the user can see when the dict is
        loaded vs. when it's empty.
        """
        # Lazy import — `pronunciation` is a pure-Python module we ship
        # but don't want a hard startup dep on. Mirrors `document_loader`
        # and `lameenc` patterns.
        try:
            from kokoro_studio.pronunciation import load_dictionary
            self._pron_rules = load_dictionary(self._pron_dict_path)
        except ImportError:
            # `pronunciation.py` is part of the repo, so a missing import
            # would mean a deployment bug. We don't fail-at-startup;
            # we leave the dict empty so the rest of the app still works.
            self._pron_rules = {}
        self._refresh_pron_count_label()

    def _save_pron_dict(self) -> bool:
        """Persist `self._pron_rules` to JSON. Returns True on success.

        Errors are surfaced via QMessageBox so a read-only filesystem
        or schema-mismatch doesn't silently lose the user's edits.
        """
        try:
            from kokoro_studio.pronunciation import save_dictionary
            save_dictionary(self._pron_dict_path, self._pron_rules)
        except ImportError:
            QMessageBox.warning(
                self, "Pronunciation dict unavailable",
                "`pronunciation.py` was not found next to the GUI. "
                "Rules are kept in memory only and lost on exit.",
            )
            return False
        except OSError as e:
            QMessageBox.critical(
                self, "Could not save dictionary",
                f"{type(e).__name__}: {e}\n\n"
                f"Path: {self._pron_dict_path}",
            )
            return False
        self._refresh_pron_count_label()
        return True

    def _refresh_pron_count_label(self) -> None:
        n = len(self._pron_rules)
        suffix = "" if n == 1 else "s"
        # Cheap label; warning level to match the dimmed counter style
        # in the editor pane (no separate CSS needed).
        self._pron_count_label.setText(f"{n} rule{suffix}")

    def _on_pron_toggle(self, _checked: bool) -> None:
        # No persistence of the enable-flag — re-enabled on next launch,
        # matching how existing per-session flags are handled. UI state
        # is self-consistent because the speed/format combos work the
        # same way.
        n = "ON" if _checked else "OFF"
        # Tiny status-bar echo so the user gets immediate feedback.
        # Don't announce via QMessageBox — that's noisy for a toggle.
        prev = self._status_label.text()
        self._status_label.setText(
            f"Pronunciation rules: {n}  ·  {len(self._pron_rules)} loaded"
        )

    def _on_edit_pronunciation_clicked(self) -> None:
        """Open a modal dialog to edit the pronunciation dictionary.

        Behaviour:
          * Populate the table with `self._pron_rules`.
          * Add Row inserts an empty row at the end.
          * Remove Selected deletes the currently-selected rows.
          * Save: re-collect rows into a dict (skip blank Find cells),
            persist via `_save_pron_dict`, close with accept().
          * Cancel / close: reject without persisting (in-memory edits
            are discarded).
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Pronunciation Dictionary")
        dialog.resize(520, 420)

        root = QVBoxLayout(dialog)

        # Descriptive header above the table.
        intro = QLabel(
            "Map each whole-word \"find\" to a \"replace\" string.\n"
            "Case-sensitive. Longest rules win. Empty replacement = delete.\n"
            f"Path: {self._pron_dict_path}"
        )
        intro.setWordWrap(True)
        intro.setObjectName("Subtitle")
        intro.setStyleSheet("font-size: 11px; margin-bottom: 4px;")
        root.addWidget(intro)

        table = QTableWidget(0, 2, dialog)
        table.setHorizontalHeaderLabels(["Find (whole word)", "Replace"])
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        table.verticalHeader().setVisible(False)

        # Populate the table from the in-memory dict. Order matches the
        # dict's insertion order (CPython 3.7+ guaranteed).
        for key, val in self._pron_rules.items():
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(key))
            table.setItem(r, 1, QTableWidgetItem(val))

        root.addWidget(table, 1)

        # Button row.
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add row")
        add_btn.setProperty("role", "ghost")
        del_btn = QPushButton("− Remove selected")
        del_btn.setProperty("role", "ghost")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(QLabel(f"{len(self._pron_rules)} rules currently"))
        root.addLayout(btn_row)

        # Standard OK / Cancel button box.
        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = bbox.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setProperty("role", "primary")
        save_btn.setText("Save")
        bbox.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        root.addWidget(bbox)

        # ---- wiring ---------------------------------------------
        def on_add() -> None:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(""))
            table.setItem(r, 1, QTableWidgetItem(""))
            table.editItem(table.item(r, 0))

        def on_remove() -> None:
            rows = sorted({idx.row() for idx in table.selectedIndexes()},
                          reverse=True)
            for r in rows:
                table.removeRow(r)

        add_btn.clicked.connect(on_add)
        del_btn.clicked.connect(on_remove)

        def on_save() -> None:
            new_rules: dict = {}
            duplicates_seen = set()
            for r in range(table.rowCount()):
                fk_item = table.item(r, 0)
                rv_item = table.item(r, 1)
                fk = fk_item.text().strip() if fk_item else ""
                if not fk:
                    # Treat blank Find as an in-progress row rather than
                    # a real rule — silently skip.
                    continue
                if fk in new_rules:
                    duplicates_seen.add(fk)
                new_rules[fk] = rv_item.text() if rv_item else ""
            if duplicates_seen:
                QMessageBox.warning(
                    self, "Duplicate find-keys",
                    "These `find` keys appear more than once and the last "
                    "one wins:\n  · " + "\n  · ".join(sorted(duplicates_seen)),
                )
            self._pron_rules = new_rules
            if self._save_pron_dict():
                dialog.accept()
            # else: keep dialog open so the user can fix file perms etc.

        bbox.accepted.connect(on_save)
        bbox.rejected.connect(dialog.reject)

        dialog.exec()

    # ---------------------------------------- Slot: document import
    def _on_open_document_clicked(self) -> None:
        """Show a file-picker dialog and import the chosen document."""
        start_dir = str(_default_output_dir())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Document",
            start_dir,
            "Documents (*.txt *.pdf *.epub);;All files (*.*)",
        )
        if path:
            self._load_document_into_editor(path)

    def _on_multi_drop_rejected(self, count: int) -> None:
        """Status-bar feedback when a multi-file drop is refused.

        We use a status message instead of a modal dialog because
        dropEvent runs inside native drag code; the user already moved
        on, so a quick flash-and-go note is friendlier than a blocking
        QMessageBox.
        """
        if count <= 1:
            return
        noun = "file" if count == 2 else "files"
        self._status_label.setText(
            f"Drop one document at a time  ·  got {count} {noun}"
        )

    def _load_document_into_editor(self, path: str) -> None:
        """Load TXT/PDF/EPUB `path` via `document_loader.load_document`
        and dump the result into the editor.

        Behaviour:
            * If the editor already has text, ask for confirmation
              before replacing (drops and open-button alike).
            * Soft-cap to ~200 000 characters so a 1000-page PDF doesn't
              freeze the UI thread; warn via QMessageBox.
            * On any failure (missing lib, encrypted file, malformed
              EPUB) surface the underlying exception via QMessageBox and
              leave the editor untouched.
        """
        # ---- confirmation gate ------------------------------------
        current_text = self._editor.toPlainText().strip()
        if current_text:
            ans = QMessageBox.question(
                self,
                "Replace editor text?",
                "The editor already contains text.\n\n"
                "Replace it with the contents of:\n"
                f"  {Path(path).name}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                self._status_label.setText("Open cancelled.")
                return

        # ---- parse + insert ---------------------------------------
        # Disabled state: block the Generate button during the import so
        # users don't synthesize a half-loaded document. The import is
        # fast (small-to-medium books take < 1s), so we don't promote
        # this to a full QThread worker.
        prev_running = self._worker is not None and self._worker.isRunning()
        if not prev_running:
            self._update_button_states()  # refresh Generate enable state
        # NOTE: deliberately NOT calling QApplication.processEvents() to
        # repaint the status label here. It's a recursion landmine \u2014
        # another drop event could re-enter the import flow. The label
        # repaints on the next event-loop tick, which is fine for a
        # sub-second import.
        self._status_label.setText(
            f"Loading document  \u00b7  {Path(path).name}\u2026"
        )

        try:
            # Local import keeps the kokoro_gui module-level surface
            # small AND lets us surface a clean install hint if the user
            # hasn't installed pypdf / ebooklib / bs4 yet.
            from kokoro_studio.document_loader import load_document
            doc = load_document(path)
        except FileNotFoundError as e:
            self._status_label.setText("Open failed.")
            QMessageBox.critical(self, "Document not found", str(e))
            return
        except ValueError as e:
            # Unsupported extension. Should not normally happen \u2014 the
            # file picker + drop handler both filter by ext \u2014 but kept
            # as a safety net for programmatic callers.
            self._status_label.setText("Open failed.")
            QMessageBox.critical(self, "Unsupported document", str(e))
            return
        except ImportError as e:
            self._status_label.setText("Open failed (missing library).")
            QMessageBox.critical(
                self,
                "Missing dependency",
                f"Document import requires extra packages:\n\n"
                f"    pip install pypdf ebooklib beautifulsoup4\n\n"
                f"Underlying error: {e}",
            )
            return
        except Exception as e:  # noqa: BLE001 \u2014 surface any parse failure
            self._status_label.setText("Open failed.")
            QMessageBox.critical(
                self,
                "Could not load document",
                f"{type(e).__name__}: {e}",
            )
            return

        text = doc.full_text
        if not text:
            self._status_label.setText("Document is empty.")
            QMessageBox.information(
                self,
                "Empty document",
                f"No readable text was found in:\n  {Path(path).name}\n\n"
                "Scanned PDFs (image-only) need OCR \u2014 not supported here.",
            )
            return

        # ---- soft cap: avoid GUI freeze on huge PDFs --------------
        char_limit = 200_000
        if len(text) > char_limit:
            truncated = text[:char_limit] + (
                "\n\n\u2026 [truncated \u2014 switching to "
                f"{len(text) - char_limit:,} chars skipped]"
            )
            text = truncated
            QMessageBox.information(
                self,
                "Document truncated",
                f"Only the first ~{char_limit // 1000}k characters "
                f"({len(text):,}) were loaded into the editor out of "
                f"the document's full ~{len(doc.full_text):,} characters.\n\n"
                "For whole-book synthesis in chunks, wait for Phase 4 "
                "(Audiobook Chapter Builder) \u2014 it will handle full "
                "books via the batch pipeline, not the editor.",
            )

        # ---- final UI update --------------------------------------
        self._editor.setPlainText(text)
        # setPlainText fires textChanged which already updates the
        # counter + button states; we still set the status label
        # explicitly because the message is more specific.
        n_chars = len(self._editor.toPlainText())
        self._status_label.setText(
            f"Loaded {n_chars:,} chars  \u00b7  {doc.title}  \u00b7  "
            f"{len(doc.chapters)} chapter(s)  \u00b7  "
            f"{Path(path).name}"
        )

    # -------------------------------------------------------- Slot: speed
    def _on_speed_spin_changed(self, value: float) -> None:
        slider_value = int(round(value * self._SPEED_TICK))
        if slider_value != self._speed_slider.value():
            self._speed_slider.blockSignals(True)
            self._speed_slider.setValue(slider_value)
            self._speed_slider.blockSignals(False)

    def _on_speed_slider_changed(self, value: int) -> None:
        new_speed = value / self._SPEED_TICK
        if abs(new_speed - self._speed_spin.value()) > 1e-4:
            self._speed_spin.blockSignals(True)
            self._speed_spin.setValue(new_speed)
            self._speed_spin.blockSignals(False)

    # ----------------------------------------------------- Slot: output path
    def _refresh_output_path(self) -> None:
        # Always pre-populate with a sensible default; user can override.
        path = self._default_path_for_current()
        self._output_edit.setText(path)

    def _default_path_for_current(self) -> str:
        """Return the output path to use right now.

        If the user has typed a path, return it verbatim. Otherwise build a
        fresh default filename that honours the currently-selected format.
        """
        path = self._output_edit.text().strip()
        if path:
            return path
        return _default_output_path(
            self._current_voice or DEFAULT_VOICE,
            self._current_output_format(),
        )

    def _current_output_format(self) -> str:
        """Canonical lowercase name (one of OUTPUT_FORMATS) of the dropdown.

        Falls back to 'wav' if the dropdown somehow has no current selection
        (e.g. items cleared during a re-render) — keeps downstream callers
        (path formatting, save_audio, _default_output_path) safe regardless
        of combobox state.
        """
        text = self._format_combo.currentText().lower()
        return text if text in OUTPUT_FORMATS else "wav"

    def _refresh_output_path_validity(self) -> None:
        path = self._output_edit.text().strip()
        if not path:
            self._refresh_output_path()
            return
        fmt = self._current_output_format()
        if not path.lower().endswith(f".{fmt}"):
            self._output_edit.setText(path + f".{fmt}")
            return

    def _on_format_changed(self, _idx: int = 0) -> None:
        """React to the user picking a new output format.

        Strategy: keep whatever path the user already typed but rewrite
        only the file extension. If the path is empty (i.e. was using the
        auto-generated default), fall back to a fresh default name so the
        timestamp gets refreshed too — otherwise re-using the same name
        from seconds ago would silently overwrite the previous render.
        """
        fmt = self._current_output_format()
        path = self._output_edit.text().strip()
        if not path:
            self._refresh_output_path()
            return
        new_path = str(Path(path).with_suffix(f".{fmt}"))
        if new_path != path:
            # blockSignals keeps editingFinished from re-entering
            # _refresh_output_path_validity in a loop.
            self._output_edit.blockSignals(True)
            self._output_edit.setText(new_path)
            self._output_edit.blockSignals(False)

    def _on_browse_clicked(self) -> None:
        start_dir = str(_default_output_dir())
        fmt = self._current_output_format()
        default_name = Path(self._default_path_for_current()).name
        # Keep the dialog's default filename in sync with the dropdown, even
        # if the user has a typed path whose extension got out-of-sync.
        if not default_name.lower().endswith(f".{fmt}"):
            default_name = Path(default_name).stem + f".{fmt}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {fmt.upper()} as",
            str(Path(start_dir) / default_name),
            f"{fmt.upper()} audio (*.{fmt});;All files (*.*)",
        )
        if path:
            if not path.lower().endswith(f".{fmt}"):
                path += f".{fmt}"
            self._output_edit.setText(path)
            ext = Path(path).suffix.lower().lstrip(".")
            # If the user picked a different extension than the dropdown
            # implies (e.g. typed 'foo.mp3' with the dropdown on WAV), snap
            # the dropdown to the chosen format so subsequent operations
            # stay consistent with the actual file on disk.
            if ext in OUTPUT_FORMATS and ext != fmt:
                idx = OUTPUT_FORMATS.index(ext)
                if self._format_combo.currentIndex() != idx:
                    self._format_combo.blockSignals(True)
                    self._format_combo.setCurrentIndex(idx)
                    self._format_combo.blockSignals(False)

    # ----------------------------------------------------- Slot: synthesis
    def _on_generate_clicked(self) -> None:
        text = self._editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No text", "Please type or paste some text first.")
            return
        fmt = self._current_output_format()
        out_path = self._output_edit.text().strip() \
            or _default_output_path(self._current_voice or DEFAULT_VOICE, fmt)

        # ---- Multi-Speaker Dialogue pre-parse (Phase 2) ------
        # We parse BEFORE handing off so we can warn about
        # unknown voices and populate the segment lookup table
        # for the status bar during synthesis. `detect_dialogue`
        # is a cheap regex precheck so we don't recompute the
        # full parser when the editor has no markers.
        from kokoro_studio.dialogue import (
            detect_dialogue, parse_dialogue, summarize_voices,
        )
        self._current_segments = []
        use_multi = False
        if detect_dialogue(text):
            segs, warnings = parse_dialogue(
                self._editor.toPlainText(),
                default_voice=self._current_voice or DEFAULT_VOICE,
                known_voices=set(VOICES.keys()),
            )
            self._current_segments = segs
            if warnings:
                # Engine has documented fallback behaviour, so the
                # dialog defaults to Yes — aborting on a typo would
                # feel hostile.
                warn_text = "\n  \u2022 ".join(warnings)
                ans = QMessageBox.question(
                    self,
                    "Unknown voices in dialogue mode",
                    f"{len(warnings)} marker(s) use voice names"
                    f" not in the bundled catalog:\n\n"
                    f"  \u2022 {warn_text}\n\n"
                    f"They will fall back to the currently-selected"
                    f" voice '{self._current_voice or DEFAULT_VOICE}'.\n\n"
                    "Continue?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if ans != QMessageBox.Yes:
                    self._status_label.setText(
                        "Generation cancelled (dialogue warnings)."
                    )
                    return
            # Engage multi-speaker mode whenever markers are present.
            # Engine handles single-segment scripts transparently
            # so we don't need a final guard. (Note: the v1 review's
            # "any voice diversity" gate was removed — markers are
            # an explicit user signal, so routing through the
            # multi-speaker engine is the right default.)
            use_multi = True
        if use_multi:
            self._status_label.setText(
                f"Multi-speaker dialogue: {len(self._current_segments)}"
                f" turn(s) \u00b7 {summarize_voices(self._current_segments)}"
            )

        # Phase 2 - Voice Blending: snapshot the loaded blends
        # so the worker thread doesn't re-read disk between clicks.
        self._start_synthesis(
            text=text,
            voice=self._current_voice or DEFAULT_VOICE,
            speed=self._speed_spin.value(),
            output_path=out_path,
            output_format=fmt,
            auto_play=True,
            label="Generate",
            pronunciation_rules=(
                self._pron_rules if self._pron_checkbox.isChecked() else None
            ),
            multi_speaker=use_multi,
            blends=dict(self._loaded_blends) if self._loaded_blends else None,
        )

    def _on_preview_clicked(self) -> None:
        if not self._current_voice:
            return
        info = get_voice_info(self._current_voice)
        phrase = _preview_phrase_for_lang(info["lang"])
        # Previews always stay as uncompressed WAV — they are short, need
        # to play instantly, and we want them to round-trip through a
        # lameenc-free code path for maximum portability across installs.
        preview_path = (_default_output_dir() /
                        f"_preview_{self._current_voice}.wav")
        self._start_synthesis(
            text=phrase,
            voice=self._current_voice,
            speed=1.0,
            output_path=str(preview_path),
            output_format="wav",
            auto_play=True,
            label="Preview",
            # Previews also honour the user's pronunciation toggle.
            # The phrase is short so wild substring substitution is
            # unlikely to misfire, but consistency with Generate
            # makes the toggle feel honest.
            pronunciation_rules=(
                self._pron_rules if self._pron_checkbox.isChecked() else None
            ),
        )

    def _on_stop_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._status_label.setText("Stopping…")
            self._stop_btn.setEnabled(False)
            # Tear down streaming BEFORE requesting the worker to stop.
            # If we did it the other way around, the audio thread could
            # still hit readData() with a half-cleared ring buffer; this
            # order keeps both sides well-defined.
            self._stop_streaming_sink()
            self._worker.request_stop()

    def _start_synthesis(
        self,
        text: str,
        voice: str,
        speed: float,
        output_path: str,
        output_format: str,
        auto_play: bool,
        label: str,
        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        # Phase 2 - Voice Blending. Snapshotted blend registry
        # forwarded to the SynthesisWorker; if None, the engine
        # auto-loads from <Documents>/KokoroStudio/voice_blends.json.
        blends: Optional[Mapping[str, "VoiceBlend"]] = None,
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # already running; ignore
        # Provision the streaming sink BEFORE creating the worker so that
        # any early chunks arriving via chunk_ready() have somewhere to
        # route through. Falls back to file-based playback if streaming
        # is off or the platform reports no audio output device.
        self._start_streaming_sink()
        # Show indeterminate progress & disable editing controls.
        self._status_label.setText(
            f"{label}: {voice} → {Path(output_path).name}  "
            f"(speed {speed:.2f}×, {len(text):,} chars, "
            f"format {output_format.upper()})"
        )
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self._generate_btn.setEnabled(False)
        self._preview_btn.setEnabled(False)
        self._stop_btn.setVisible(True)
        self._stop_btn.setEnabled(True)
        self._editor.setReadOnly(True)
        self._speed_spin.setEnabled(False)
        self._speed_slider.setEnabled(False)
        self._browse_btn.setEnabled(False)
        self._format_combo.setEnabled(False)
        self._pron_edit_btn.setEnabled(False)
        self._pron_checkbox.setEnabled(False)
        # Streaming toggle stays reachable so a power user can switch
        # mid-run; its state is informational because the sink is
        # already provisioned (the slot is documented below).
        self._output_edit.setReadOnly(True)

        self._worker = SynthesisWorker(
            text=text,
            voice=voice,
            speed=speed,
            output_path=output_path,
            output_format=output_format,
            pronunciation_rules=pronunciation_rules,
            multi_speaker=multi_speaker,
            speaker_gap_s=speaker_gap_s,
            # Phase 2 - Voice Blending. Forward the GUI's
            # blend snapshot to the worker so saved blend
            # names resolve to tensors at run time.
            blends=blends,

            # Phase 2 - SSML-lite. Snapshot the
            # checkbox state at click time so a
            # mid-run flip can't trigger the
            # half-parsed-execution footgun.
            apply_ssml=self._ssml_checkbox.isChecked(),  # SSML-GUI-E12
        )
        self._worker.chunk_ready.connect(self._on_streaming_chunk)
        # Multi-speaker dialogue: fires once per voice transition
        # so the status bar can show "Speaker X/Y: <voice>." In
        # single-speaker mode fires exactly once at startup.
        self._worker.segment_started.connect(self._on_segment_started)
        # Capture auto_play in a lambda closure (default arg avoids late-binding).
        self._worker.finished_ok.connect(
            lambda path, dur, audio, ap=auto_play:
                self._on_synthesis_done(path, dur, ap, audio)
        )
        self._worker.failed.connect(self._on_synthesis_failed)
        self._worker.finished.connect(self._on_synthesis_thread_finished)
        self._worker.start()

    def _on_synthesis_progress(self, chunks_done: int,
                               _chunks_visible: int,
                               cumulative_seconds: float,
                               eta_seconds: float) -> None:
        # Total chunks unknown upfront (the engine emits lazily through
        # Kokoro's SentencePiece tokenizer). Show running counter + a
        # best-effort ETA. `_format_duration` already does the right
        # thing for "X.XX s" / "1m 30.50s" output; ETA `-1` = no signal.
        eta_str = ""
        if eta_seconds > 0.0:
            eta_str = f"  ·  ~{_format_duration(eta_seconds)} remaining"
        self._status_label.setText(
            f"Generating  ·  chunk {chunks_done}  ·  "
            f"{_format_duration(cumulative_seconds)} of audio so far{eta_str}"
        )

    def _on_synthesis_done(self, path: str, duration_s: float,
                           auto_play: bool, _audio: np.ndarray) -> None:
        self._last_audio_path = path
        size_bytes = 0
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            pass
        self._status_label.setText(
            f"Done  ·  {_format_duration(duration_s)}  ·  "
            f"{_format_bytes(size_bytes)}  ·  {Path(path).name}"
        )
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setVisible(False)
        if auto_play:
            # Decide between streaming-drain vs. QMediaPlayer fallback
            # using PortAudio's own `active` flag. This is more
            # reliable than the synchronous QAudioSink.error() poll
            # we tried in v1 (which Qt6 sets asynchronously):
            # `active` flips False the instant the callback raises
            # `sd.CallbackStop`, i.e. on natural EOS drain OR a
            # sounddevice-side failure. `getattr(..., False)`
            # handles the case where sounddevice was never imported
            # (`_sd_stream` is None in that case, so we fall through
            # cleanly to the proven file-based path).
            sd_active = bool(getattr(self._sd_stream, "active", False))
            streaming_ok = self._ring_buffer is not None and sd_active
            if streaming_ok:
                # Streaming path: don't kick QMediaPlayer — two
                # simultaneous output devices would clash on the audio
                # hardware. Mark EOS on the ring buffer and let
                # QAudioSink drain naturally into IdleState, then
                # _on_streaming_sink_state() does the cleanup. The
                # saved file is in `self._last_audio_path` and the
                # user can re-play it after playback finishes.
                self._ring_buffer.mark_eos()
            else:
                # File-based fallback. Covers three cases:
                #  1. streaming was never enabled (legacy path);
                #  2. streaming WAS enabled but the sink errored
                #     (Windows format-negotiation failure, locked
                #     device, backend refused the format, etc.);
                #  3. odd safety-net state (ring buffer present but
                #     sink is None — should not normally happen).
                self._stop_streaming_sink()
                self._player.stop()
                self._player.setSource(QUrl.fromLocalFile(path))
                self._player.play()

    def _on_synthesis_failed(self, error_msg: str) -> None:
        self._status_label.setText("Failed.")
        self._progress.setVisible(False)
        # CRITICAL: tear the streaming sink down here too — the engine
        # raised BEFORE mark_eos was called, so the sink would keep
        # playing silence indefinitely otherwise. Reset clears any
        # in-flight chunks that survived the failure.
        self._stop_streaming_sink()
        QMessageBox.critical(self, "Synthesis failed", error_msg)

    def _on_synthesis_thread_finished(self) -> None:
        # Disengage worker; restore UI to idle state. NOTE: the streaming
        # sink (if any) is intentionally NOT torn down here — it may
        # still be draining its buffer. Cleanup happens in
        # _on_streaming_sink_state when QAudioSink transitions to
        # IdleState after EOS. Worst case (e.g. close event during
        # drain), closeEvent() forces a hard stop.
        self._worker = None
        self._progress.setRange(0, 0)
        self._editor.setReadOnly(False)
        self._output_edit.setReadOnly(False)
        self._browse_btn.setEnabled(True)
        self._stop_btn.setVisible(False)
        self._update_button_states()

    # ----------------------------------------------------- Slot: playback
    def _on_play_clicked(self) -> None:
        if not self._last_audio_path:
            return
        # If the user clicks "Play last" while a streaming sink is
        # still active (rare race window between finished_ok and the
        # IdleState transition), stop the sink first so we don't have
        # both devices talking at once.
        self._stop_streaming_sink()
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(self._last_audio_path))
        self._player.play()

    # ================================================== Streaming playback
    def _start_streaming_sink(self) -> None:
        """Provision sounddevice.OutputStream for streaming playback.

        Why sounddevice instead of QAudioSink:
          * PySide6's QAudioSink was silently no-op'ing on the
            user's Windows audio endpoint despite v1's Int16 PCM
            negotiation (file save works, Listen-to-last works,
            but real-time streaming was silent). Without
            diagnostics on the user's hardware we cannot pinpoint
            the root cause; sounddevice bypasses the entire
            QtMultimedia streaming stack on the assumption that
            PortAudio (via WASAPI on Windows) is more reliable.
          * sounddevice accepts float32 PCM directly, so we drop
            the v1 Int16 downconversion and keep Kokoro's
            full-range output untouched.
          * PortAudio owns its C audio thread; we get gapless
            playback without the QAudioSink GC / stateChanged
            races we kept tripping over.

        Failure modes (all silenced, fall back to file-based):
          - streaming checkbox is unchecked;
          - the platform reports no audio output device;
          - sounddevice isn't importable (lazy import).

        Health-check used by `_on_synthesis_done`:
          `self._sd_stream.active` (PortAudio's flag flips False
          the moment the callback raises `sd.CallbackStop`, i.e.
          on natural EOS drain via the empty-buffer + eos branch).
        """
        if not (self._stream_checkbox.isChecked() and self._stream_available):
            return
        # `sd` is bound at module scope via the lazy import near
        # the top of this file (mirrors the PySide6 pattern).
        # `_HAS_SOUNDDEVICE` is False when sounddevice isn't
        # installed (rare; sounddevice is in requirements.txt).
        if not _HAS_SOUNDDEVICE:
            return
        # Defensive: a previous run leaked a stream (close-event
        # path skipped). Drop it first so we don't end up with
        # two PortAudio streams competing.
        if self._sd_stream is not None:
            self._stop_streaming_sink()
        self._ring_buffer = PcmRingBuffer()
        # Cache the user-chosen volume so the PortAudio callback
        # never has to read self._audio_out (a Qt object) on its
        # background thread. The volume is locked for the
        # synthesis run; mid-run volume changes are a future
        # feature (would need a Qt-signal-driven refresh here).
        self._stream_volume = float(self._audio_out.volume())
        try:
            self._sd_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype='float32',
                # ~46 ms per callback at 24 kHz mono is a good
                # latency/safety trade-off: small enough to react
                # quickly to per-chunk arrivals, large enough that
                # transient producer jitter won't underrun.
                blocksize=1024,
                callback=self._sd_stream_callback,
            )
            self._sd_stream.start()
        except Exception:
            # sd.OutputStream ctor / start can fail if the host's
            # default device is busy or pulled. Reset state so
            # `_on_synthesis_done`'s fallback to QMediaPlayer
            # kicks in cleanly.
            self._sd_stream = None
            self._ring_buffer = None
            return

    def _sd_stream_callback(self, outdata, frames, time_info, status) -> None:
        """PortAudio callback that drains PcmRingBuffer.

        Runs on PortAudio's background thread (NOT the GUI thread).
        Must be fast, exception-safe, and self-contained: any
        exception here can hang the OS audio subsystem, so we
        propagate only `sd.CallbackStop` and swallow everything
        else. We deliberately do not touch Qt widgets from here
        (PySide6 widgets are not thread-safe); instead a
        print-to-stderr breadcrumb is emitted for diagnostic
        underruns (see below).

        Underrun contract:
          - buffer empty + EOS NOT set: silent (PortAudio will
            call us again as soon as the producer pushes more);
          - buffer empty + EOS SET: raise sd.CallbackStop so
            `_sd_stream.active` flips False (read by
            `_on_synthesis_done`'s fallback decision).
        """
        try:
            if status:
                # PortAudio surfaces underflow / overflow via the
                # status struct. Print to stderr as a breadcrumb
                # for the user debugging audio issues from
                # console output alone. We deliberately do NOT
                # call self._status_label.setText here: PySide6
                # widgets are not thread-safe from a PortAudio
                # callback and a UI access violation here can
                # hang the OS audio subsystem.
                try:
                    print(f"[Kokoro] audio underrun/overflow: {status}", file=sys.stderr)
                except Exception:
                    pass
            # `frames` = number of samples PortAudio requested
            # this call. Float32 mono = 4 bytes per sample.
            num_bytes = frames * 4
            chunk = (
                self._ring_buffer.pop(num_bytes)
                if self._ring_buffer is not None
                else b""
            )
            if not chunk:
                if self._ring_buffer is not None and self._ring_buffer.is_eos():
                    raise sd.CallbackStop
                outdata.fill(0)
                return
            # Apply the same volume knob the file-based path uses.
            # sounddevice has no .setVolume() so we scale the
            # float32 samples in-place. self._audio_out.volume()
            # is a pure accessor (no Qt work) -> safe from
            # callback thread.
            arr = np.frombuffer(chunk, dtype=np.float32) * self._stream_volume
            n = min(len(arr), frames)
            outdata[:n, 0] = arr[:n]
            if n < frames:
                # Partial pull - pad remainder with silence. Can
                # happen at EOS or just before the next chunk
                # arrives.
                outdata[n:, 0] = 0
        except sd.CallbackStop:
            raise
        except Exception:
            # Catastrophic failure inside the audio thread:
            # silence and keep going. Never crash PortAudio from
            # a callback.
            try:
                outdata.fill(0)
            except Exception:
                pass

    def _on_streaming_chunk(self, _seg_idx: int, _chunk_idx: int, chunk: np.ndarray) -> None:
        """Route an incoming Kokoro chunk into the streaming ring buffer.

        Slot fires on the GUI thread (Qt signal-slot connection delivers
        cross-thread safely by default). The push itself is also
        thread-safe, so even if a future change re-routes this through
        a direct call, no race is introduced.
        """
        if self._ring_buffer is None:
            return
        # Push Kokoro's raw float32 bytes straight into the ring
        # buffer. sounddevice (PortAudio) consumes float32 PCM
        # natively on every supported backend (WASAPI / CoreAudio /
        # PulseAudio / PipeWire), so we keep full dynamic range and
        # drop the v1 Int16 downconversion path entirely.
        # `np.asarray` is defensive against mis-typed callers; the
        # `.tobytes()` representation is little-endian IEEE-754 on
        # x86/ARM, which is exactly what sounddevice reads.
        pcm = np.asarray(chunk, dtype=np.float32).reshape(-1)
        self._ring_buffer.push(pcm.tobytes())

    def _on_streaming_sink_state(self, state) -> None:
        """Legacy QAudioSink stateChanged hook - now a no-op shim.

        Kept as an empty method (rather than deleted) so any stray
        connect call or external reference doesn't crash.
        sounddevice doesn't fire Qt-style stateChanged signals;
        cleanup after a streaming run is handled by
        `_stop_streaming_sink` on the GUI thread instead.
        """
        return


    def _stop_streaming_sink(self) -> None:
        """Hard-stop the sounddevice stream (drops in-flight audio).

        Used by the Stop button (Stop -> worker interrupt) and by
        `closeEvent` (window shutdown during a streaming run).
        sounddevice's `stop()` aborts the PortAudio stream without
        draining; `close()` releases the underlying WASAPI handle.
        We reset the ring buffer so stale audio does not bleed
        into a subsequent run.
        """
        if self._sd_stream is not None:
            try:
                self._sd_stream.stop()
            except Exception:
                pass
            try:
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None
        if self._ring_buffer is not None:
            self._ring_buffer.reset()

    def _on_stream_toggle(self, checked: bool) -> None:
        """Echo the new streaming toggle state in the status bar.

        The checkbox is informational from the next synthesis
        forward (provisioning happens at `_start_synthesis` time, not
        here), so we just confirm the choice with a status-bar note
        matching the pattern used for the Pronunciation toggle.
        """
        if not self._stream_available:
            self._status_label.setText(
                "Streaming unavailable on this system "
                "(no audio output device).  "
                "Falling back to file-based playback."
            )
            return
        state = "ON" if checked else "OFF"
        mode = "real-time streaming" if checked else "play-after-synthesis"
        self._status_label.setText(
            f"Streaming playback: {state}  ·  next run will use {mode}"
        )

    def _on_stop_audio_clicked(self) -> None:
        self._player.stop()

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlayingState
        self._stop_audio_btn.setEnabled(playing)
        self._play_btn.setEnabled(
            not playing
            and self._last_audio_path is not None
            and Path(self._last_audio_path).exists()
        )

    def _on_open_folder_clicked(self) -> None:
        folder = _default_output_dir()
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:  # noqa: BLE001 — UX, surface to user
            QMessageBox.warning(self, "Could not open folder", str(e))

    # ------------------------------------------------ Slot: settings & info
    def _on_settings_clicked(self) -> None:
        """Open the modal SettingsDialog (about / shortcuts / donate / license).

        Each click creates a fresh dialog so it stays in sync with the
        editor text and any state that might change between opens.
        Closed dialogs are GC'd by Qt once the slot returns because
        there's no parent-side reference left to them.
        """
        SettingsDialog(self).exec()

    # ------------------------------------------------------ State helpers
    def _update_button_states(self) -> None:
        running = self._worker is not None and self._worker.isRunning()
        text_ok = bool(self._editor.toPlainText().strip())
        has_audio = (
            self._last_audio_path is not None
            and Path(self._last_audio_path).exists()
        )
        self._generate_btn.setEnabled(text_ok and not running)
        self._preview_btn.setEnabled(bool(self._current_voice) and not running)
        self._play_btn.setEnabled(has_audio and not running)
        self._open_folder_btn.setEnabled(True)
        self._speed_spin.setEnabled(not running)
        self._speed_slider.setEnabled(not running)
        self._format_combo.setEnabled(not running)
        # `_pron_edit_btn` and `_pron_checkbox` were disabled during
        # synthesis in `_start_synthesis`, but if the worker hasn't
        # been started (e.g. user opens the dict while text is empty),
        # they should still be reachable. The synthesis-disabled flip
        # above remains the authoritative state during a run.
        self._pron_edit_btn.setEnabled(not running)
        self._pron_checkbox.setEnabled(not running)
        # Streaming checkbox stays reachable during synthesis
        # (changing it mid-run only affects the NEXT run), but
        # greys out when the platform has no audio output device.
        self._stream_checkbox.setEnabled(self._stream_available)
        # Mirror button enable state to the QAction shortcuts so keyboard
        # users get the same greyed-out affordances as mouse users. We
        # don't touch Undo/Redo here — those are driven by
        # `_editor.undoAvailable` / `redoAvailable` (wired in
        # `_wire_shortcuts`) which already keeps them in sync.
        if hasattr(self, "_gen_act"):
            self._gen_act.setEnabled(text_ok and not running)
            self._prev_act.setEnabled(bool(self._current_voice) and not running)
            self._save_act.setEnabled(text_ok and not running)

    # === Voice Blending helpers (Phase 2) ===
    def _load_blends(self) -> None:
        """Read voice_blends.json into self._loaded_blends.

        Mirrors `_load_pron_dict`. Silently recovers from a
        missing or malformed file.
        """
        try:
            from kokoro_studio.blending import load_blends as _ld
            self._loaded_blends = _ld(self._blend_dict_path)
        except ImportError:
            self._loaded_blends = {}
        self._refresh_blend_count_label()

    def _save_blend(self, name: str, blend) -> bool:
        """Persist a single blend to disk + memory.

        Returns True on success. False on user-visible validation
        failure (the slot surfaces a QMessageBox).
        """
        try:
            from kokoro_studio.blending import (
                save_blends as _sv, is_valid_blend_name as _vn,
            )
        except ImportError:
            QMessageBox.warning(
                self, "Voice blending unavailable",
                "`blending.py` was not found. The blend was not saved.",
            )
            return False
        if not _vn(name):
            QMessageBox.warning(
                self, "Invalid blend name",
                "Blend names must match `[A-Za-z_][A-Za-z0-9_]*`.\n"
                f"You provided: {name!r}",
            )
            return False
        if name in VOICES:
            QMessageBox.warning(
                self, "Name reserved",
                f"{name!r} is the name of a built-in voice.\n"
                "Choose a different name (built-ins are immutable).",
            )
            return False
        _new_dict = dict(self._loaded_blends)
        if name in _new_dict:
            _ans = QMessageBox.question(
                self, "Overwrite blend?",
                f"A blend named {name!r} already exists.\n\n"
                "Replace it with the current panel settings?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if _ans != QMessageBox.Yes:
                return False
        _new_dict[name] = blend
        try:
            _sv(self._blend_dict_path, _new_dict, reserved_names=VOICES)
        except (OSError, ValueError) as e:
            QMessageBox.critical(
                self, "Could not save blend",
                f"{type(e).__name__}: {e}\n\nPath: {self._blend_dict_path}",
            )
            return False
        self._loaded_blends = _new_dict
        self._refresh_blend_count_label()
        self._repopulate_voice_list(None)
        # Auto-select the just-saved blend so the output filename
        # and readout reflect it immediately (no extra click).
        for _i in range(self._voice_list.count()):
            if self._voice_list.item(_i).data(Qt.UserRole) == name:
                self._voice_list.setCurrentRow(_i)
                break
        return True

    def _refresh_blend_count_label(self) -> None:
        _n = len(self._loaded_blends)
        _sfx = "" if _n == 1 else "s"
        _lbl = getattr(self, "_blend_count_label", None)
        if _lbl is not None:
            _lbl.setText(f"{_n} blend{_sfx} saved")

    def _default_blend_name(self) -> str:
        """Auto-generate a blend name from the panel state.

        e.g. af_bella + af_sarah, alpha 0.7 -> "bella_sarah_70".
        """
        _va = (
            self._blend_voice_a_combo.currentText()
            if self._blend_voice_a_combo else "af_heart"
        )
        _vb = (
            self._blend_voice_b_combo.currentText()
            if self._blend_voice_b_combo else "af_heart"
        )
        _alpha = (
            self._blend_alpha_spin.value()
            if self._blend_alpha_spin else 0.5
        )
        _short_a = _va.split("_", 1)[1] if "_" in _va else _va
        _short_b = _vb.split("_", 1)[1] if "_" in _vb else _vb
        if _short_a == _short_b:
            return f"{_short_a}_shift{int(round(_alpha*100))}"
        return f"{_short_a}_{_short_b}_{int(round(_alpha*100))}"

    def _on_alpha_slider_changed(self, v: int) -> None:
        if self._suppress_blend_alpha_sync or self._blend_alpha_spin is None:
            return
        self._suppress_blend_alpha_sync = True
        try:
            self._blend_alpha_spin.setValue(v / 100.0)
        finally:
            self._suppress_blend_alpha_sync = False

    def _on_alpha_spin_changed(self, v: float) -> None:
        if self._suppress_blend_alpha_sync or self._blend_alpha_slider is None:
            return
        self._suppress_blend_alpha_sync = True
        try:
            # setSliderPosition avoids the loop-back emit.
            self._blend_alpha_slider.setSliderPosition(int(round(v * 100)))
        finally:
            self._suppress_blend_alpha_sync = False

    def _on_blend_voice_selection_changed(self, _idx: int) -> None:
        """If the Name field is empty, pre-fill the auto-generated
        name from the new voice pair + alpha so users see a useful
        placeholder as they fiddle with the dropdowns.
        """
        if (self._blend_name_edit is not None
                and not self._blend_name_edit.text().strip()):
            self._blend_name_edit.setPlaceholderText(self._default_blend_name())

    def _on_save_blend_clicked(self) -> None:
        from kokoro_studio.blending import VoiceBlend
        _name = (self._blend_name_edit.text().strip()
                 if self._blend_name_edit else "")
        if not _name:
            _name = self._default_blend_name()
        _va = (self._blend_voice_a_combo.currentText()
               if self._blend_voice_a_combo else "af_bella")
        _vb = (self._blend_voice_b_combo.currentText()
               if self._blend_voice_b_combo else "af_sarah")
        _alpha = round(self._blend_alpha_spin.value(), 4) \
            if self._blend_alpha_spin is not None else 0.5
        try:
            _blend = VoiceBlend(voice_a=_va, voice_b=_vb, alpha=_alpha)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid blend", str(e))
            return
        if self._save_blend(_name, _blend):
            self._status_label.setText(
                f"Saved blend {_name!r}  ·  "
                f"{int(round(_alpha*100))}% {_va} + "
                f"{int(round((1.0-_alpha)*100))}% {_vb}"
            )

    def _on_preview_blend_clicked(self) -> None:
        """Ad-hoc preview of the panel's CURRENTLY-EDITED blend.

        Uses `voice_blend=(a, b, alpha)` so the user can hear a
        tweak before saving it as a preset. Synthesis runs on
        the GUI thread (short phrase, ~1-2 s); a re-entrancy
        flag prevents a Generate click from racing against the
        synchronous `generate_speech` call.
        """
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Busy",
                "A generation is already running. Stop it first "
                "to preview a new blend.",
            )
            return
        if self._preview_in_progress:
            return  # silently drop the second click
        from kokoro_studio.blending import VoiceBlend
        _va = (self._blend_voice_a_combo.currentText()
               if self._blend_voice_a_combo else "af_bella")
        _vb = (self._blend_voice_b_combo.currentText()
               if self._blend_voice_b_combo else "af_sarah")
        _alpha = round(self._blend_alpha_spin.value(), 4) \
            if self._blend_alpha_spin is not None else 0.5
        try:
            _blend = VoiceBlend(voice_a=_va, voice_b=_vb, alpha=_alpha)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid blend", str(e))
            return
        _phrase = (
            "Hello! This is a quick preview of my voice as a blend."
        )
        _out_path = _default_output_path(
            f"blend_{int(round(_alpha*100))}_{_va}_{_vb}", "wav",
        )
        self._preview_in_progress = True
        try:
            _audio = generate_speech(
                text=_phrase, voice_blend=_blend,
                output_path=_out_path, speed=1.0,
            )
        except Exception as e:
            self._preview_in_progress = False
            QMessageBox.critical(
                self, "Blend preview failed",
                f"{type(e).__name__}: {e}",
            )
            return
        finally:
            self._preview_in_progress = False
        self._last_audio_path = _out_path
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(_out_path))
        self._player.play()
        self._play_btn.setEnabled(True)
        self._status_label.setText(
            f"Blend preview  ·  {int(round(_alpha*100))}% {_va} + "
            f"{int(round((1.0-_alpha)*100))}% {_vb}  ·  "
            f"{len(_audio)/SAMPLE_RATE:.2f}s"
        )

    # ------------------------------------------------------- Window close
    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            ans = QMessageBox.question(
                self,
                "Generation in progress",
                "A synthesis is still running. Stop it and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return
            self._worker.request_stop()
            if not self._worker.wait(3000):
                # The engine only checks `stop_check` between Kokoro chunks,
                # so if we're stuck inside a single forward pass we have to
                # fall back to `terminate()`. It's marked dangerous in Qt but
                # acceptable here because we're exiting the whole app.
                print(
                    "[KokoroStudio] worker did not stop within 3s; forcing "
                    "QThread termination.",
                    file=sys.stderr,
                )
                self._worker.terminate()
                self._worker.wait(1000)
        # Hard-stop the streaming sink before tearing down the window.
        # Qt audio thread may be mid-readData() right now; stop() first
        # so it gets a clean shutdown signal before refs go away.
        self._stop_streaming_sink()
        try:
            self._player.stop()
        except Exception:
            pass
        super().closeEvent(event)


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> int:
    if not _HAS_PYSIDE6:
        sys.stderr.write(
            "\nKokoro Studio requires PySide6.\n\n"
            "    pip install PySide6\n\n"
            f"Import error: {_PYSIDE_IMPORT_ERR}\n"
        )
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("Kokoro Studio")
    app.setOrganizationName("Kokoro Studio")
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)


    window = KokoroStudioMain()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
# [SSML-GUI-HOOKS-APPLIED-v2-LINE-ANCHORED]
