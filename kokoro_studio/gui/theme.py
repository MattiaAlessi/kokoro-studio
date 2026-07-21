# -*- coding: utf-8 -*-
"""Shared theme, QSS, and helper constants for the Kokoro Studio GUI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kokoro_studio.engine import DEFAULT_VOICE, OUTPUT_FORMATS

# When running headless (no PySide6), the module should still import cleanly.
try:
    from PySide6.QtCore import QStandardPaths
    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False


# ===========================================================================
# Theme constants
# ===========================================================================

THEME_DARK = "dark"
THEME_LIGHT = "light"

_THEME_NAMES = {THEME_DARK: "Dark", THEME_LIGHT: "Light"}

def theme_display_name(mode: str) -> str:
    return _THEME_NAMES.get(mode, "Dark")


# ===========================================================================
# Dark theme QSS
# ===========================================================================

QSS_DARK = """
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
# Light theme QSS
# ===========================================================================

QSS_LIGHT = """
* { font-family: 'Segoe UI', 'Inter', system-ui, sans-serif; }

QMainWindow, QWidget {
    background-color: #F2F2F7;
    color: #1C1C1E;
}

QFrame#Panel {
    background-color: #FFFFFF;
    border: 1px solid #D1D1D6;
    border-radius: 12px;
}

QLabel#H1 {
    color: #000000;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
}
QLabel#Subtitle {
    color: #8E8E93;
    font-size: 11px;
}
QLabel#SectionTitle {
    color: #8E8E93;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.5px;
}
QLabel#Counter {
    color: #8E8E93;
    font-size: 11px;
}
QLabel#VoiceReadout {
    color: #1C1C1E;
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
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 10px;
    padding: 14px;
    selection-background-color: #7B61FF;
    selection-color: white;
    font-family: 'Consolas', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 12px;
}
QPlainTextEdit:focus { border: 1px solid #7B61FF; }

QListWidget {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 10px;
    padding: 6px;
    outline: 0;
}
QListWidget::item {
    border-radius: 8px;
    padding: 10px 12px;
    margin: 3px 1px;
}
QListWidget::item:hover { background-color: #F2F2F7; }
QListWidget::item:selected { background-color: #7B61FF; color: #FFFFFF; }
QListWidget::item QLabel { background-color: transparent; color: #1C1C1E; }
QListWidget::item:selected QLabel { color: #FFFFFF; }

QPushButton {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 500;
}
QPushButton:hover { background-color: #F2F2F7; border-color: #C7C7CC; }
QPushButton:pressed { background-color: #E5E5EA; }
QPushButton:disabled { color: #C7C7CC; border-color: #E5E5EA; background-color: #F2F2F7; }

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
    background-color: #C4B8FF; border-color: #C4B8FF; color: #888;
}

QPushButton[role="danger"] {
    background-color: #FF3B30; color: white; border: 1px solid #FF3B30;
}
QPushButton[role="danger"]:hover { background-color: #FF6259; border-color: #FF6259; }
QPushButton[role="danger"]:disabled {
    background-color: #FFB3B0; border-color: #FFB3B0; color: #888;
}

QPushButton[role="ghost"] { background-color: transparent; border: 1px solid #D1D1D6; }
QPushButton[role="ghost"]:hover { background-color: #F2F2F7; }
QPushButton[role="ghost"]:disabled { background-color: transparent; border-color: #E5E5EA; }

QDoubleSpinBox, QComboBox, QLineEdit {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 8px;
    padding: 7px 12px;
    selection-background-color: #7B61FF;
}
QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid #7B61FF; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: #FFFFFF; color: #1C1C1E;
    border: 1px solid #D1D1D6;
    selection-background-color: #7B61FF;
    padding: 4px; outline: 0;
}

QProgressBar {
    background-color: #E5E5EA;
    border: 1px solid #D1D1D6;
    border-radius: 6px;
    text-align: center;
    color: #1C1C1E;
    height: 14px;
}
QProgressBar::chunk {
    background-color: #7B61FF;
    border-radius: 5px;
}
QProgressBar#Indeterminate { text-align: right; padding-right: 8px; color: #8E8E93; }

QStatusBar {
    background-color: #FFFFFF;
    color: #8E8E93;
    border-top: 1px solid #D1D1D6;
}
QStatusBar QLabel { color: #1C1C1E; padding: 0 6px; }

QSplitter::handle { background-color: transparent; }

QToolTip {
    background-color: #FFFFFF; color: #1C1C1E;
    border: 1px solid #D1D1D6;
    padding: 6px 10px;
    border-radius: 8px;
}

QScrollBar:vertical {
    background: transparent; width: 8px; margin: 4px;
}
QScrollBar::handle:vertical {
    background: #C7C7CC; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #AEAEB2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; background: none;
}
"""


# ===========================================================================
# Dialog QSS — dark
# ===========================================================================

SETTINGS_QSS_DARK = """
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


# ===========================================================================
# Dialog QSS — light
# ===========================================================================

SETTINGS_QSS_LIGHT = """
QDialog {
    background-color: #F2F2F7;
}

QTabWidget::pane {
    border: 1px solid #D1D1D6;
    background-color: #FFFFFF;
    border-radius: 0px;
    top: 0px;
}
QTabBar {
    background-color: transparent;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background-color: transparent;
    color: #8E8E93;
    padding: 9px 18px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border-bottom: 2px solid #7B61FF;
}
QTabBar::tab:hover:!selected {
    color: #1C1C1E;
}

QLabel#SettingsH1 {
    color: #000000;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
}
QLabel#SettingsBlock {
    color: #1C1C1E;
    font-size: 12px;
    line-height: 1.6;
}
QLabel#AddrLabel {
    color: #8E8E93;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
}

QTableWidget {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 8px;
    gridline-color: #E5E5EA;
}
QHeaderView::section {
    background-color: #F2F2F7;
    color: #8E8E93;
    border: none;
    border-bottom: 1px solid #D1D1D6;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 1.2px;
}

QLineEdit#AddressReadOnly {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #7B61FF;
}
"""


# ===========================================================================
# Convenience: pick the right QSS by theme mode
# ===========================================================================

def get_qss(mode: str) -> str:
    """Return the main application QSS for *mode* (dark or light)."""
    if mode == THEME_LIGHT:
        return QSS_LIGHT
    return QSS_DARK


def get_settings_qss(mode: str) -> str:
    """Return the settings-dialog QSS for *mode* (dark or light)."""
    if mode == THEME_LIGHT:
        return SETTINGS_QSS_LIGHT
    return SETTINGS_QSS_DARK


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


def preview_phrase_for_lang(lang_code: str) -> str:
    return PREVIEW_PHRASES.get(lang_code, PREVIEW_PHRASES["a"])


def default_output_dir() -> Path:
    """Return <Documents>/KokoroStudio (auto-create). Falls back gracefully."""
    if _HAS_PYSIDE6:
        try:
            docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        except Exception:
            docs = ""
    else:
        docs = ""
    base = Path(docs) if docs else Path.home() / "Documents"
    folder = base / "KokoroStudio"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path.cwd()
    return folder


def default_output_path(voice: str, fmt: str = "wav") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_voice = voice.replace("/", "_").replace("\\\\", "_")
    if fmt not in OUTPUT_FORMATS:
        fmt = "wav"
    return str(default_output_dir() / f"Kokoro_{safe_voice}_{ts}.{fmt}")


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{int(seconds * 1000)} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {s:05.2f}s"


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


# SSML-lite Help dialog content (Phase 2).
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
