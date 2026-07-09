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
        QEvent, QObject, QSize, QStandardPaths, Qt, QThread, QTimer,
        QUrl, Signal,
    )
    from PySide6.QtGui import QAction, QFont, QKeySequence
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
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
    # QAction / QKeySequence / QEvent / QTabWidget / QTimer are referenced
    # only inside methods that never run when PySide6 is missing (main()
    # gates on _HAS_PYSIDE6 before constructing KokoroStudioMain). We
    # expose harmless stubs so editor auto-complete and type-checkers flag
    # the names properly.
    QAction = object           # type: ignore[assignment,misc]
    QKeySequence = object      # type: ignore[assignment,misc]
    QEvent = object            # type: ignore[assignment,misc]
    QTabWidget = object        # type: ignore[assignment,misc]
    QTimer = object            # type: ignore[assignment,misc]  

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
    # worker, so the rate estimate from `idx == 0` is wildly inflated.
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
        parent: Optional[QObject] = None,
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

    def _on_chunk(self, idx: int, audio_chunk: np.ndarray) -> None:
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
                and (idx + 1) >= self._ETA_MIN_CHUNKS):
            rate = cum_seconds / elapsed_wallclock  # s_audio per s_wall
            if rate > 0.0:
                est_total_audio = (
                    len(self._text) / self._EMPIRICAL_CHARS_PER_AUDIO_SEC
                )
                remaining_audio = max(0.0, est_total_audio - cum_seconds)
                eta_seconds = remaining_audio / rate

        # chunks_done = idx + 1; the engine doesn't know total upfront,
        # so `chunks_visible` mirrors "n" — the progress bar stays
        # indeterminate.
        self.progress.emit(idx + 1, idx + 1, cum_seconds, eta_seconds)

    # ---- main entry ----------------------------------------------------
    def run(self) -> None:  # noqa: D401 — Qt calls this on .start()
        self._cumulative_samples = 0
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
                on_chunk=self._on_chunk,
                stop_check=self._stop_check,
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
            "and a growing set of audiobook / batch features.<br><br>"
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

        # Audio playback
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        # In PySide6/Qt6, volume lives on QAudioOutput (QMediaPlayer.setVolume
        # was removed in Qt 6).
        self._audio_out.setVolume(0.9)

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

        # Voice list (filter dropdown removed — only voice selection matters).
        self._voice_list.currentItemChanged.connect(self._on_voice_changed)

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

    def _refresh_voice_readout(self) -> None:
        if not self._current_voice:
            self._voice_readout.setText("—")
            return
        info = get_voice_info(self._current_voice)
        self._voice_readout.setText(
            f"{self._current_voice}  ·  Grade {info['grade']}"
        )

    # ---------------------------------------------------- Slot: voice/langs
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
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # already running; ignore
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
        self._output_edit.setReadOnly(True)

        self._worker = SynthesisWorker(
            text=text,
            voice=voice,
            speed=speed,
            output_path=output_path,
            output_format=output_format,
            pronunciation_rules=pronunciation_rules,
            parent=self,
        )
        self._worker.progress.connect(self._on_synthesis_progress)
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
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()

    def _on_synthesis_failed(self, error_msg: str) -> None:
        self._status_label.setText("Failed.")
        self._progress.setVisible(False)
        QMessageBox.critical(self, "Synthesis failed", error_msg)

    def _on_synthesis_thread_finished(self) -> None:
        # Disengage worker; restore UI to idle state.
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
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(self._last_audio_path))
        self._player.play()

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
        # Mirror button enable state to the QAction shortcuts so keyboard
        # users get the same greyed-out affordances as mouse users. We
        # don't touch Undo/Redo here — those are driven by
        # `_editor.undoAvailable` / `redoAvailable` (wired in
        # `_wire_shortcuts`) which already keeps them in sync.
        if hasattr(self, "_gen_act"):
            self._gen_act.setEnabled(text_ok and not running)
            self._prev_act.setEnabled(bool(self._current_voice) and not running)
            self._save_act.setEnabled(text_ok and not running)

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
