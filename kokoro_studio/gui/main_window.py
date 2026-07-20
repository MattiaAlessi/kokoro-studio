# -*- coding: utf-8 -*-
"""Primary application window for Kokoro Studio."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSlider,
    QSplitter, QStatusBar, QToolBar, QVBoxLayout, QWidget,
)

from kokoro_studio.engine import (
    DEFAULT_VOICE, LANG_CODES, OUTPUT_FORMATS, SAMPLE_RATE, SPEED_MAX,
    SPEED_MIN, VOICES, generate_speech, get_voice_info, list_voices,
)
from kokoro_studio.history import GenerationHistory
from kokoro_studio.streaming import (
    PcmRingBuffer, default_audio_output_is_available,
)
from kokoro_studio.gui.dialogs import (
    BatchQueueDialog, BlendVoiceDialog, DialogueHelpDialog, HistoryDialog,
    ProfilesDialog, PronunciationDialog, SettingsDialog, SSMLHelpDialog,
)
from kokoro_studio.gui.editor import DocumentDropEditor
from kokoro_studio.gui.theme import (
    QSS, default_output_dir, default_output_path, format_bytes, format_duration,
    preview_phrase_for_lang,
)
from kokoro_studio.profiles import (
    CharacterProfile, load_profiles, save_profiles,
)
from kokoro_studio.gui.workers import SynthesisWorker

# Lazy import sounddevice for streaming playback
try:
    import sounddevice as sd  # type: ignore[import-not-found]
    _HAS_SOUNDDEVICE = True
except ImportError:
    sd = None  # type: ignore[assignment]
    _HAS_SOUNDDEVICE = False


class KokoroStudioMain(QMainWindow):

    _SPEED_TICK = 100

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kokoro Studio")
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)

        self._worker: Optional[SynthesisWorker] = None
        self._last_audio_path: Optional[str] = None
        self._current_voice: str = DEFAULT_VOICE

        # Pronunciation dictionary state
        self._pron_rules: dict = {}
        self._pron_dict_path = default_output_dir() / "pronunciation.json"

        # Audio playback
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._audio_out.setVolume(0.9)

        # Streaming playback state
        self._sd_stream: Optional[object] = None
        self._ring_buffer: Optional[PcmRingBuffer] = None
        self._stream_volume: float = 0.9
        self._stream_available: bool = default_audio_output_is_available()
        self._stream_disabled_reason: str = (
            "" if self._stream_available
            else "streaming unavailable: no local audio output device"
        )

        # Dialogue / SSML chip placeholders
        self._dialogue_chip: Optional[QLabel] = None
        self._dialogue_chip_row: Optional[QWidget] = None
        self._ssml_chip: Optional[QLabel] = None
        self._ssml_chip_row: Optional[QWidget] = None
        self._ssml_checkbox: Optional[QCheckBox] = None
        self._discoverability_banner: Optional[QLabel] = None

        # Character profiles state
        self._profiles: dict[str, CharacterProfile] = {}
        self._profiles_path = default_output_dir() / "profiles.json"
        self._current_profile_name: Optional[str] = None

        # Blending state
        self._loaded_blends: dict = {}
        self._blend_dict_path = default_output_dir() / "voice_blends.json"

        # History state
        self._history = GenerationHistory(str(default_output_dir() / "history.db"))
        self._current_segments: list = []

        self._build_ui()
        self._wire_signals()
        self._wire_shortcuts()

        self._load_pron_dict()
        self._load_blends()
        self._load_profiles()
        self._repopulate_voice_list(None)
        self._refresh_profiles_combo()
        self._refresh_output_path()
        self._update_button_states()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("Central")
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(14)

        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())

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

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("🎙  Kokoro Studio")
        title.setObjectName("H1")
        subtitle = QLabel("Local, free, fast neural text-to-speech · powered by Kokoro‑82M")
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        h.addLayout(title_box)
        h.addStretch(1)

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

        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setProperty("role", "ghost")
        self._settings_btn.setToolTip("Settings & info")
        self._settings_btn.setFixedSize(34, 34)
        self._settings_btn.setStyleSheet("font-size: 18px; padding: 0; border-radius: 17px;")
        h.addWidget(self._settings_btn)

        return header

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Panel")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        def make_btn(text: str, slot) -> QPushButton:
            btn = QPushButton(text)
            btn.setProperty("role", "ghost")
            btn.clicked.connect(slot)
            return btn

        self._batch_btn = make_btn("📦 Batch", self._on_batch_clicked)
        self._history_btn = make_btn("🕒 History", self._on_history_clicked)
        self._blend_btn = make_btn("🎛 Blending", self._on_blending_clicked)
        self._pron_btn = make_btn("📖 Dictionary", self._on_pronunciation_clicked)
        self._ssml_help_btn = make_btn("⚡ SSML Help", self._on_ssml_help_clicked)
        self._dialogue_help_btn = make_btn("🎭 Dialogue Help", self._on_dialogue_help_clicked)

        layout.addWidget(self._history_btn)
        layout.addWidget(self._batch_btn)
        layout.addWidget(self._blend_btn)
        layout.addWidget(self._pron_btn)
        layout.addWidget(self._ssml_help_btn)
        layout.addWidget(self._dialogue_help_btn)
        layout.addStretch(1)
        return bar

    def _build_voice_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("VOICE LIBRARY")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self._voice_list = QListWidget()
        self._voice_list.setSelectionMode(QListWidget.SingleSelection)
        self._voice_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        layout.addWidget(self._voice_list, 1)

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

        self._open_doc_btn = QPushButton("📂  Open…")
        self._open_doc_btn.setProperty("role", "ghost")
        self._open_doc_btn.setToolTip("Open a TXT, PDF, or EPUB file. You can also drag a file onto the editor.")
        self._open_doc_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        header_row.addWidget(self._open_doc_btn)
        header_row.addStretch(1)

        self._counter_label = QLabel("0 chars  ·  0 words")
        self._counter_label.setObjectName("Counter")
        header_row.addWidget(self._counter_label)
        layout.addLayout(header_row)

        self._discoverability_banner = QLabel(
            '<html>💡 Try <b>SSML-lite controls</b> (<code>&lt;break&gt;</code>, <code>&lt;emphasis&gt;</code>, '
            '<code>&lt;prosody&gt;</code>) — tick <i>Apply SSML</i> below.<br>'
            '&nbsp;&nbsp;&nbsp;&nbsp;Or start a line with <code>[voice_name]:</code> for <b>Multi-Speaker Dialogue</b>.</html>'
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
        self._discoverability_banner.setTextFormat(Qt.RichText)
        layout.addWidget(self._discoverability_banner)

        self._editor = DocumentDropEditor()
        self._editor.setPlaceholderText(
            "Type or paste your text here.\n\n"
            "Tip: long inputs are split automatically by Kokoro's tokenizer —\n"
            "you can paste entire chapters without performance concerns.\n\n"
            "Or drop a .txt / .pdf / .epub file here, or click Open."
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

        # Row 1: profile | voice readout | speed | output path
        row1 = QHBoxLayout()
        row1.setSpacing(14)

        profile_box = QVBoxLayout()
        profile_box.setSpacing(2)
        profile_lbl = QLabel("CHARACTER PROFILE")
        profile_lbl.setObjectName("SectionTitle")
        profile_select_row = QHBoxLayout()
        profile_select_row.setSpacing(4)
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(150)
        self._profile_combo.setToolTip("Select a character profile to set voice & speed")
        profile_select_row.addWidget(self._profile_combo, 1)
        self._profiles_btn = QPushButton("🎭")
        self._profiles_btn.setProperty("role", "ghost")
        self._profiles_btn.setFixedSize(32, 32)
        self._profiles_btn.setToolTip("Manage character profiles")
        self._profiles_btn.clicked.connect(self._on_profiles_clicked)
        profile_select_row.addWidget(self._profiles_btn)
        profile_box.addWidget(profile_lbl)
        profile_box.addLayout(profile_select_row)
        profile_widget = QWidget()
        profile_widget.setLayout(profile_box)
        profile_widget.setMaximumWidth(260)
        row1.addWidget(profile_widget)

        voice_box = QVBoxLayout()
        voice_box.setSpacing(2)
        voice_lbl = QLabel("VOICE")
        voice_lbl.setObjectName("SectionTitle")
        self._voice_readout = QLabel(DEFAULT_VOICE)
        self._voice_readout.setObjectName("VoiceReadout")
        voice_box.addWidget(voice_lbl)
        voice_box.addWidget(self._voice_readout)
        voice_widget = QWidget()
        voice_widget.setLayout(voice_box)
        voice_widget.setMinimumWidth(180)
        row1.addWidget(voice_widget)

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
        self._speed_slider.setRange(int(SPEED_MIN * self._SPEED_TICK), int(SPEED_MAX * self._SPEED_TICK))
        self._speed_slider.setValue(int(1.0 * self._SPEED_TICK))
        speed_row.addWidget(self._speed_slider, 1)
        speed_box.addWidget(speed_lbl)
        speed_box.addLayout(speed_row)
        row1.addLayout(speed_box, 1)

        out_box = QVBoxLayout()
        out_box.setSpacing(4)
        out_lbl = QLabel("OUTPUT FILE")
        out_lbl.setObjectName("SectionTitle")
        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        self._format_combo = QComboBox()
        self._format_combo.addItems([f.upper() for f in OUTPUT_FORMATS])
        self._format_combo.setMinimumWidth(86)
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)
        self._format_combo.setFont(mono_font)
        out_row.addWidget(self._format_combo)
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("Path to save the generated audio…")
        out_row.addWidget(self._output_edit, 1)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setProperty("role", "ghost")
        out_row.addWidget(self._browse_btn)
        out_box.addWidget(out_lbl)
        out_box.addLayout(out_row)
        row1.addLayout(out_box, 1)

        layout.addLayout(row1)

        # Dialogue chip
        chip_row_inner = QHBoxLayout()
        chip_row_inner.setSpacing(8)
        self._dialogue_chip = QLabel("")
        self._dialogue_chip.setStyleSheet(
            "color: #9178FF; background-color: rgba(123,97,255,0.10);"
            " border: 1px solid rgba(123,97,255,0.35);"
            " border-radius: 6px; padding: 5px 10px;"
            " font-size: 11px; font-weight: 600;"
        )
        chip_row_inner.addWidget(self._dialogue_chip, 1)
        self._dialogue_chip_row = QWidget()
        self._dialogue_chip_row.setLayout(chip_row_inner)
        self._dialogue_chip_row.setVisible(False)
        layout.addWidget(self._dialogue_chip_row)

        # SSML chip
        ssml_chip_row_inner = QHBoxLayout()
        ssml_chip_row_inner.setSpacing(8)
        self._ssml_chip = QLabel("")
        self._ssml_chip.setStyleSheet(
            "color: #10B981; background-color: rgba(16,185,129,0.10);"
            " border: 1px solid rgba(16,185,129,0.35);"
            " border-radius: 6px; padding: 5px 10px;"
            " font-size: 11px; font-weight: 600;"
        )
        ssml_chip_row_inner.addWidget(self._ssml_chip, 1)
        self._ssml_chip_row = QWidget()
        self._ssml_chip_row.setLayout(ssml_chip_row_inner)
        self._ssml_chip_row.setVisible(False)
        layout.addWidget(self._ssml_chip_row)

        # Row 2: action buttons
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self._pron_checkbox = QCheckBox("Apply rules")
        self._pron_checkbox.setChecked(True)
        row2.addWidget(self._pron_checkbox)

        self._pron_count_label = QLabel("0 rules")
        self._pron_count_label.setObjectName("Counter")
        row2.addSpacing(12)
        row2.addWidget(self._pron_count_label)

        self._ssml_checkbox = QCheckBox("Apply SSML")
        self._ssml_checkbox.setChecked(False)
        row2.addSpacing(12)
        row2.addWidget(self._ssml_checkbox)

        self._stream_checkbox = QCheckBox("▶ Stream")
        self._stream_checkbox.setChecked(self._stream_available)
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
        self._progress.setRange(0, 0)
        self._progress.setMaximumWidth(240)
        self._progress.setFixedHeight(14)
        self._progress.setVisible(False)
        self._progress.setObjectName("Indeterminate")
        sb.addPermanentWidget(self._progress)
        return sb

    # ----------------------------------------------------------- Signals
    def _wire_signals(self) -> None:
        self._editor.textChanged.connect(self._on_text_changed)
        self._editor.textChanged.connect(lambda: self._refresh_ssml_chip(self._editor.toPlainText()))
        if self._discoverability_banner is not None:
            _banner = self._discoverability_banner
            _ed = self._editor
            _single_shot = Qt.SingleShotConnection
            self._editor.textChanged.connect(
                lambda _b=_banner, _e=_ed: (
                    _b.setVisible(False)
                    if (_b.isVisible() and len(_e.toPlainText()) > 80)
                    else None
                ),
                _single_shot,
            )
        self._editor.fileDropped.connect(self._load_document_into_editor)
        self._editor.multiDropRejected.connect(self._on_multi_drop_rejected)
        self._open_doc_btn.clicked.connect(self._on_open_document_clicked)

        self._pron_checkbox.toggled.connect(self._on_pron_toggle)
        self._ssml_checkbox.toggled.connect(lambda _checked: self._refresh_ssml_chip(self._editor.toPlainText()))
        self._stream_checkbox.toggled.connect(self._on_stream_toggle)

        self._voice_list.currentItemChanged.connect(self._on_voice_changed)
        self._speed_spin.valueChanged.connect(self._on_speed_spin_changed)
        self._speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)

        self._output_edit.editingFinished.connect(self._refresh_output_path_validity)
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)

        self._generate_btn.clicked.connect(self._on_generate_clicked)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._play_btn.clicked.connect(self._on_play_clicked)
        self._stop_audio_btn.clicked.connect(self._on_stop_audio_clicked)
        self._open_folder_btn.clicked.connect(self._on_open_folder_clicked)

        self._settings_btn.clicked.connect(self._on_settings_clicked)

        self._player.playbackStateChanged.connect(self._on_playback_state)

    def _wire_shortcuts(self) -> None:
        self._gen_act = QAction("Generate", self)
        self._gen_act.setShortcut("Ctrl+G")
        self._gen_act.setShortcutContext(Qt.WindowShortcut)
        self._gen_act.triggered.connect(self._on_generate_clicked)
        self.addAction(self._gen_act)

        self._prev_act = QAction("Preview voice", self)
        self._prev_act.setShortcut("Ctrl+P")
        self._prev_act.setShortcutContext(Qt.WindowShortcut)
        self._prev_act.triggered.connect(self._on_preview_clicked)
        self.addAction(self._prev_act)

        self._open_act = QAction("Open document…", self)
        self._open_act.setShortcut(QKeySequence.StandardKey.Open)
        self._open_act.setShortcutContext(Qt.WindowShortcut)
        self._open_act.triggered.connect(self._on_open_document_clicked)
        self.addAction(self._open_act)

        self._save_act = QAction("Save text…", self)
        self._save_act.setShortcut(QKeySequence.StandardKey.Save)
        self._save_act.setShortcutContext(Qt.WindowShortcut)
        self._save_act.triggered.connect(self._on_save_text_clicked)
        self.addAction(self._save_act)

        self._editor.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._editor and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key_Space:
                if self._can_toggle_playback():
                    self._toggle_playback()
                    return True
        return super().eventFilter(watched, event)

    # --------------------------------------------------------- Feature windows
    def _on_settings_clicked(self) -> None:
        SettingsDialog(self).exec()

    def _on_history_clicked(self) -> None:
        dlg = HistoryDialog(self._history, self)
        dlg.load_text_requested.connect(self._editor.setPlainText)
        dlg.play_requested.connect(self._play_file)
        dlg.exec()

    def _on_batch_clicked(self) -> None:
        dlg = BatchQueueDialog(
            editor_text=self._editor.toPlainText(),
            current_voice=self._current_voice or DEFAULT_VOICE,
            current_speed=self._speed_spin.value(),
            current_format=self._current_output_format(),
            pronunciation_rules=(
                self._pron_rules if self._pron_checkbox.isChecked() else None
            ),
            blends=dict(self._loaded_blends) if self._loaded_blends else None,
            parent=self,
        )
        dlg.exec()

    def _on_profiles_clicked(self) -> None:
        dlg = ProfilesDialog(
            profiles=self._profiles,
            profiles_path=self._profiles_path,
            current_voice=self._current_voice or DEFAULT_VOICE,
            current_speed=self._speed_spin.value(),
            parent=self,
        )
        dlg.profile_applied.connect(self._on_profile_applied)
        dlg.exec()

    def _on_blending_clicked(self) -> None:
        dlg = BlendVoiceDialog(self._loaded_blends, self._blend_dict_path, self)
        dlg.blend_saved.connect(self._on_blend_saved)
        dlg.exec()

    def _on_pronunciation_clicked(self) -> None:
        dlg = PronunciationDialog(self._pron_rules, self._pron_dict_path, self)
        dlg.rules_saved.connect(self._on_pron_rules_saved)
        dlg.exec()

    def _on_ssml_help_clicked(self) -> None:
        dlg = SSMLHelpDialog(self)
        dlg.insert_requested.connect(self._insert_ssml_sample)
        dlg.exec()

    def _on_dialogue_help_clicked(self) -> None:
        dlg = DialogueHelpDialog(self)
        dlg.insert_requested.connect(self._editor.setPlainText)
        dlg.exec()

    def _on_blend_saved(self, name: str, blend) -> None:
        self._repopulate_voice_list(None)
        # Select the saved blend
        for i in range(self._voice_list.count()):
            if self._voice_list.item(i).data(Qt.UserRole) == name:
                self._voice_list.setCurrentRow(i)
                break
        self._status_label.setText(f"Saved blend {name!r}")

    def _on_pron_rules_saved(self, rules: dict) -> None:
        self._pron_rules = rules
        self._refresh_pron_count_label()

    def _insert_ssml_sample(self, text: str) -> None:
        self._editor.setPlainText(text)
        self._ssml_checkbox.setChecked(True)

    # --------------------------------------------------------- Editor / text
    def _on_text_changed(self) -> None:
        text = self._editor.toPlainText()
        chars = len(text)
        words = len(text.split()) if text.strip() else 0
        self._counter_label.setText(f"{chars:,} chars  ·  {words:,} words")
        self._update_button_states()
        self._refresh_dialogue_chip(text)

    def _on_save_text_clicked(self) -> None:
        text = self._editor.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "Nothing to save", "The editor is empty.")
            return
        start_dir = str(default_output_dir())
        default_name = "kokoro_script.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save text as", str(Path(start_dir) / default_name),
            "Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self._status_label.setText(f"Saved {len(text):,} chars  ·  {Path(path).name}")
        except OSError as e:
            QMessageBox.critical(self, "Save failed", f"{type(e).__name__}: {e}")

    # --------------------------------------------------------- Voice list
    def _repopulate_voice_list(self, lang_code: Optional[str]) -> None:
        voices = list_voices(lang=lang_code)
        self._voice_list.blockSignals(True)
        self._voice_list.clear()
        if not voices:
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
            placeholder.setFlags(Qt.NoItemFlags)
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
            label = QLabel()
            label.setTextFormat(Qt.RichText)
            label.setText(rich)
            label.setWordWrap(True)
            label.setContentsMargins(0, 0, 0, 0)
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
            self._voice_list.addItem(item)
            self._voice_list.setItemWidget(item, label)

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
        if voice_changed:
            self._refresh_output_path()
            self._update_button_states()

    def _on_voice_changed(self, current: Optional[QListWidgetItem], _previous=None) -> None:
        if current is None:
            return
        voice = current.data(Qt.UserRole)
        if not voice or voice == self._current_voice:
            self._refresh_voice_readout()
            return
        self._current_voice = voice
        self._refresh_voice_readout()
        self._refresh_output_path()
        self._update_button_states()

    def _refresh_voice_readout(self) -> None:
        if not self._current_voice:
            self._voice_readout.setText("—")
            return
        if self._current_voice in self._loaded_blends:
            b = self._loaded_blends[self._current_voice]
            pct_a = int(round(b.alpha * 100))
            pct_b = 100 - pct_a
            self._voice_readout.setText(
                f"🎛 {self._current_voice}  ·  {pct_a}% {b.voice_a} + {pct_b}% {b.voice_b}"
            )
            return
        info = get_voice_info(self._current_voice)
        self._voice_readout.setText(f"{self._current_voice}  ·  Grade {info['grade']}")

    # --------------------------------------------------------- Dialogue / SSML chips
    def _refresh_dialogue_chip(self, text: str) -> None:
        try:
            from kokoro_studio.dialogue import detect_dialogue, parse_dialogue, summarize_voices
        except ImportError:
            return
        chip = self._dialogue_chip
        row = self._dialogue_chip_row
        if chip is None or row is None:
            return
        if not detect_dialogue(text):
            row.setVisible(False)
            return
        _known = set(VOICES.keys()) | set(self._loaded_blends.keys())
        _fallback = self._current_voice or DEFAULT_VOICE
        if _fallback not in VOICES and _fallback in self._loaded_blends:
            _fallback = DEFAULT_VOICE
        segs, _ = parse_dialogue(text, default_voice=_fallback, known_voices=_known)
        summary = summarize_voices(segs)
        if summary:
            chip.setText(f"🎭 {len(segs)} speaker turn(s): {summary}")
            row.setVisible(True)
        else:
            row.setVisible(False)

    def _refresh_ssml_chip(self, text: str) -> None:
        chip = self._ssml_chip
        row = self._ssml_chip_row
        cb = self._ssml_checkbox
        if chip is None or row is None or cb is None:
            return
        if not cb.isChecked():
            row.setVisible(False)
            return
        try:
            from kokoro_studio.ssml import detect_ssml, parse_ssml, summarize_ssml
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
        dialogue_row_visible = bool(
            self._dialogue_chip_row is not None and self._dialogue_chip_row.isVisible()
        )
        if dialogue_row_visible:
            chip.setStyleSheet(
                "color: #F59E0B; background-color: rgba(245,158,11,0.10);"
                " border: 1px solid rgba(245,158,11,0.35);"
                " border-radius: 6px; padding: 5px 10px;"
                " font-size: 11px; font-weight: 600;"
            )
            chip.setText(f"⚡ SSML: {summary} (ignored in dialogue mode)")
        else:
            chip.setStyleSheet(
                "color: #10B981; background-color: rgba(16,185,129,0.10);"
                " border: 1px solid rgba(16,185,129,0.35);"
                " border-radius: 6px; padding: 5px 10px;"
                " font-size: 11px; font-weight: 600;"
            )
            chip.setText(f"⚡ SSML: {summary}")
        row.setVisible(True)

    def _on_segment_started(self, seg_idx: int) -> None:
        if not self._current_segments or seg_idx >= len(self._current_segments):
            return
        voice = self._current_segments[seg_idx].voice
        total = len(self._current_segments)
        self._status_label.setText(f"Speaker {seg_idx + 1}/{total}: {voice} · generating...")

    # --------------------------------------------------------- Character Profiles
    def _load_profiles(self) -> None:
        try:
            self._profiles = load_profiles(self._profiles_path)
        except Exception:
            self._profiles = {}

    def _refresh_profiles_combo(self) -> None:
        sender = self.sender() if hasattr(self, 'sender') else None
        # Don't re-trigger while we rebuild
        self._profile_combo.blockSignals(True)
        current = self._profile_combo.currentText()
        self._profile_combo.clear()
        self._profile_combo.addItem("— No profile —", None)
        for name in sorted(self._profiles.keys()):
            self._profile_combo.addItem(name, name)
        # Restore selection if possible
        idx = self._profile_combo.findText(current)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        else:
            # Try the saved active profile name
            if self._current_profile_name:
                idx2 = self._profile_combo.findText(self._current_profile_name)
                if idx2 >= 0:
                    self._profile_combo.setCurrentIndex(idx2)
                else:
                    self._current_profile_name = None
                    self._profile_combo.setCurrentIndex(0)
            else:
                self._profile_combo.setCurrentIndex(0)
        self._profile_combo.blockSignals(False)

    def _on_profile_selected(self, idx: int) -> None:
        name = self._profile_combo.itemData(idx)
        if not name:
            self._current_profile_name = None
            return
        profile = self._profiles.get(name)
        if profile and profile.voice:
            self._current_profile_name = name
            self._current_voice = profile.voice
            self._speed_spin.blockSignals(True)
            self._speed_spin.setValue(profile.speed)
            self._speed_spin.blockSignals(False)
            # Sync speed slider
            slider_val = int(round(profile.speed * self._SPEED_TICK))
            self._speed_slider.blockSignals(True)
            self._speed_slider.setValue(slider_val)
            self._speed_slider.blockSignals(False)
            # Select the voice in the list without full rebuild
            self._select_voice_in_list(profile.voice)
            self._refresh_voice_readout()
            self._refresh_output_path()
            self._status_label.setText(
                f"Profile {name!r} applied  ·  {profile.voice}  ·  {profile.speed:.2f}x"
            )

    def _select_voice_in_list(self, voice: str) -> None:
        """Select the given voice in the voice list without a full rebuild."""
        for i in range(self._voice_list.count()):
            item = self._voice_list.item(i)
            if item and item.data(Qt.UserRole) == voice:
                self._voice_list.blockSignals(True)
                self._voice_list.setCurrentRow(i)
                self._voice_list.blockSignals(False)
                return
        # Voice not found in list (e.g. blend name) — fall back to full rebuild
        self._repopulate_voice_list(None)

    def _on_profile_applied(self, name: str, profile: object) -> None:
        """Called when the ProfilesDialog emits profile_applied."""
        self._load_profiles()  # Reload in case user saved a new one
        self._refresh_profiles_combo()
        # Try to select the applied profile in the combo
        for i in range(self._profile_combo.count()):
            if self._profile_combo.itemText(i) == name:
                self._profile_combo.setCurrentIndex(i)
                break

    # --------------------------------------------------------- Pronunciation
    def _load_pron_dict(self) -> None:
        try:
            from kokoro_studio.pronunciation import load_dictionary
            self._pron_rules = load_dictionary(self._pron_dict_path)
        except ImportError:
            self._pron_rules = {}
        self._refresh_pron_count_label()

    def _refresh_pron_count_label(self) -> None:
        n = len(self._pron_rules)
        suffix = "" if n == 1 else "s"
        self._pron_count_label.setText(f"{n} rule{suffix}")

    def _on_pron_toggle(self, _checked: bool) -> None:
        n = "ON" if _checked else "OFF"
        self._status_label.setText(f"Pronunciation rules: {n}  ·  {len(self._pron_rules)} loaded")

    # --------------------------------------------------------- Document import
    def _on_open_document_clicked(self) -> None:
        start_dir = str(default_output_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Document", start_dir,
            "Documents (*.txt *.pdf *.epub);;All files (*.*)",
        )
        if path:
            self._load_document_into_editor(path)

    def _on_multi_drop_rejected(self, count: int) -> None:
        if count <= 1:
            return
        noun = "file" if count == 2 else "files"
        self._status_label.setText(f"Drop one document at a time  ·  got {count} {noun}")

    def _load_document_into_editor(self, path: str) -> None:
        current_text = self._editor.toPlainText().strip()
        if current_text:
            ans = QMessageBox.question(
                self, "Replace editor text?",
                f"The editor already contains text. Replace it with {Path(path).name}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                self._status_label.setText("Open cancelled.")
                return
        self._status_label.setText(f"Loading document  ·  {Path(path).name}…")
        try:
            from kokoro_studio.document_loader import load_document
            doc = load_document(path)
        except Exception as e:
            self._status_label.setText("Open failed.")
            QMessageBox.critical(self, "Could not load document", f"{type(e).__name__}: {e}")
            return
        text = doc.full_text
        if not text:
            self._status_label.setText("Document is empty.")
            QMessageBox.information(self, "Empty document", "No readable text was found.")
            return
        char_limit = 200_000
        if len(text) > char_limit:
            text = text[:char_limit] + "\n\n… [truncated]"
            QMessageBox.information(self, "Document truncated", "Loaded first ~200k characters.")
        self._editor.setPlainText(text)
        self._status_label.setText(f"Loaded {len(text):,} chars  ·  {doc.title}")

    # --------------------------------------------------------- Speed / output
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

    def _refresh_output_path(self) -> None:
        path = self._default_path_for_current()
        self._output_edit.setText(path)

    def _default_path_for_current(self) -> str:
        path = self._output_edit.text().strip()
        if path:
            return path
        return default_output_path(
            self._current_voice or DEFAULT_VOICE,
            self._current_output_format(),
        )

    def _current_output_format(self) -> str:
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

    def _on_format_changed(self, _idx: int = 0) -> None:
        fmt = self._current_output_format()
        path = self._output_edit.text().strip()
        if not path:
            self._refresh_output_path()
            return
        new_path = str(Path(path).with_suffix(f".{fmt}"))
        if new_path != path:
            self._output_edit.blockSignals(True)
            self._output_edit.setText(new_path)
            self._output_edit.blockSignals(False)

    def _on_browse_clicked(self) -> None:
        start_dir = str(default_output_dir())
        fmt = self._current_output_format()
        default_name = Path(self._default_path_for_current()).name
        if not default_name.lower().endswith(f".{fmt}"):
            default_name = Path(default_name).stem + f".{fmt}"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {fmt.upper()} as", str(Path(start_dir) / default_name),
            f"{fmt.upper()} audio (*.{fmt});;All files (*.*)",
        )
        if path:
            if not path.lower().endswith(f".{fmt}"):
                path += f".{fmt}"
            self._output_edit.setText(path)
            ext = Path(path).suffix.lower().lstrip(".")
            if ext in OUTPUT_FORMATS and ext != fmt:
                idx = OUTPUT_FORMATS.index(ext)
                self._format_combo.blockSignals(True)
                self._format_combo.setCurrentIndex(idx)
                self._format_combo.blockSignals(False)

    # --------------------------------------------------------- Synthesis
    def _on_generate_clicked(self) -> None:
        text = self._editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No text", "Please type or paste some text first.")
            return
        fmt = self._current_output_format()
        out_path = self._output_edit.text().strip() or default_output_path(
            self._current_voice or DEFAULT_VOICE, fmt
        )

        from kokoro_studio.dialogue import detect_dialogue, parse_dialogue, summarize_voices
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
                warn_text = "\n  · ".join(warnings)
                ans = QMessageBox.question(
                    self, "Unknown voices in dialogue mode",
                    f"Unknown voice markers:\n\n  · {warn_text}\n\nContinue?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
                )
                if ans != QMessageBox.Yes:
                    self._status_label.setText("Generation cancelled (dialogue warnings).")
                    return
            use_multi = True
        if use_multi:
            self._status_label.setText(
                f"Multi-speaker dialogue: {len(self._current_segments)} turn(s) · "
                f"{summarize_voices(self._current_segments)}"
            )

        self._start_synthesis(
            text=text,
            voice=self._current_voice or DEFAULT_VOICE,
            speed=self._speed_spin.value(),
            output_path=out_path,
            output_format=fmt,
            auto_play=True,
            label="Generate",
            pronunciation_rules=(self._pron_rules if self._pron_checkbox.isChecked() else None),
            multi_speaker=use_multi,
            blends=dict(self._loaded_blends) if self._loaded_blends else None,
        )

    def _on_preview_clicked(self) -> None:
        if not self._current_voice:
            return
        info = get_voice_info(self._current_voice)
        phrase = preview_phrase_for_lang(info["lang"])
        preview_path = default_output_dir() / f"_preview_{self._current_voice}.wav"
        self._start_synthesis(
            text=phrase,
            voice=self._current_voice,
            speed=1.0,
            output_path=str(preview_path),
            output_format="wav",
            auto_play=True,
            label="Preview",
            pronunciation_rules=(self._pron_rules if self._pron_checkbox.isChecked() else None),
        )

    def _on_stop_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._status_label.setText("Stopping…")
            self._stop_btn.setEnabled(False)
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
        blends: Optional[dict] = None,
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._start_streaming_sink()
        self._status_label.setText(
            f"{label}: {voice} → {Path(output_path).name}  "
            f"(speed {speed:.2f}×, {len(text):,} chars, format {output_format.upper()})"
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
        self._output_edit.setReadOnly(True)
        self._set_feature_controls_enabled(False)

        self._last_generation_text = text
        self._last_generation_voice = voice
        self._last_generation_speed = speed

        self._worker = SynthesisWorker(
            text=text,
            voice=voice,
            speed=speed,
            output_path=output_path,
            output_format=output_format,
            pronunciation_rules=pronunciation_rules,
            multi_speaker=multi_speaker,
            speaker_gap_s=speaker_gap_s,
            blends=blends,
            apply_ssml=self._ssml_checkbox.isChecked(),
        )
        self._worker.progress.connect(self._on_synthesis_progress)
        self._worker.chunk_ready.connect(self._on_streaming_chunk)
        self._worker.segment_started.connect(self._on_segment_started)
        self._worker.finished_ok.connect(
            lambda path, dur, audio, ap=auto_play: self._on_synthesis_done(path, dur, ap, audio)
        )
        self._worker.failed.connect(self._on_synthesis_failed)
        self._worker.finished.connect(self._on_synthesis_thread_finished)
        self._worker.start()

    def _on_synthesis_progress(self, chunks_done: int, _chunks_visible: int,
                               cumulative_seconds: float, eta_seconds: float) -> None:
        eta_str = ""
        if eta_seconds > 0.0:
            eta_str = f"  ·  ~{format_duration(eta_seconds)} remaining"
        self._status_label.setText(
            f"Generating  ·  chunk {chunks_done}  ·  "
            f"{format_duration(cumulative_seconds)} of audio so far{eta_str}"
        )

    def _on_synthesis_done(self, path: str, duration_s: float, auto_play: bool, _audio: np.ndarray) -> None:
        self._last_audio_path = path
        try:
            text = getattr(self, "_last_generation_text", "")
            if text and text.strip():
                fmt = Path(path).suffix.lstrip(".").lower() or "wav"
                self._history.add_generation(
                    text=text,
                    voice=self._last_generation_voice,
                    speed=self._last_generation_speed,
                    duration_s=duration_s,
                    audio_path=path,
                    output_format=fmt,
                )
        except Exception:
            pass
        size_bytes = 0
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            pass
        self._status_label.setText(
            f"Done  ·  {format_duration(duration_s)}  ·  "
            f"{format_bytes(size_bytes)}  ·  {Path(path).name}"
        )
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setVisible(False)
        if auto_play:
            sd_active = bool(getattr(self._sd_stream, "active", False))
            streaming_ok = self._ring_buffer is not None and sd_active
            if streaming_ok:
                self._ring_buffer.mark_eos()
            else:
                self._stop_streaming_sink()
                self._player.stop()
                self._player.setSource(QUrl.fromLocalFile(path))
                self._player.play()

    def _on_synthesis_failed(self, error_msg: str) -> None:
        self._status_label.setText("Failed.")
        self._progress.setVisible(False)
        self._stop_streaming_sink()
        QMessageBox.critical(self, "Synthesis failed", error_msg)

    def _on_synthesis_thread_finished(self) -> None:
        self._worker = None
        self._progress.setRange(0, 0)
        self._editor.setReadOnly(False)
        self._output_edit.setReadOnly(False)
        self._browse_btn.setEnabled(True)
        self._stop_btn.setVisible(False)
        self._set_feature_controls_enabled(True)
        self._update_button_states()

    # --------------------------------------------------------- Playback
    def _on_play_clicked(self) -> None:
        if self._last_audio_path:
            self._play_file(self._last_audio_path)

    def _play_file(self, path: str) -> None:
        self._stop_streaming_sink()
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def _can_toggle_playback(self) -> bool:
        if self._worker is not None and self._worker.isRunning():
            return False
        if self._ring_buffer is not None and not self._ring_buffer.is_eos():
            return False
        return bool(self._last_audio_path and Path(self._last_audio_path).exists())

    def _toggle_playback(self) -> None:
        if not self._can_toggle_playback():
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
        else:
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
        folder = default_output_dir()
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            QMessageBox.warning(self, "Could not open folder", str(e))

    # --------------------------------------------------------- Streaming
    def _start_streaming_sink(self) -> None:
        if not (self._stream_checkbox.isChecked() and self._stream_available):
            return
        if not _HAS_SOUNDDEVICE:
            return
        if self._sd_stream is not None:
            self._stop_streaming_sink()
        self._ring_buffer = PcmRingBuffer()
        self._stream_volume = float(self._audio_out.volume())
        try:
            self._sd_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=1024,
                callback=self._sd_stream_callback,
            )
            self._sd_stream.start()
        except Exception:
            self._sd_stream = None
            self._ring_buffer = None

    def _sd_stream_callback(self, outdata, frames, time_info, status) -> None:
        try:
            if status:
                try:
                    print(f"[Kokoro] audio underrun/overflow: {status}", file=sys.stderr)
                except Exception:
                    pass
            num_bytes = frames * 4
            chunk = self._ring_buffer.pop(num_bytes) if self._ring_buffer is not None else b""
            if not chunk:
                if self._ring_buffer is not None and self._ring_buffer.is_eos():
                    raise sd.CallbackStop
                outdata.fill(0)
                return
            arr = np.frombuffer(chunk, dtype=np.float32) * self._stream_volume
            n = min(len(arr), frames)
            outdata[:n, 0] = arr[:n]
            if n < frames:
                outdata[n:, 0] = 0
        except sd.CallbackStop:
            raise
        except Exception:
            try:
                outdata.fill(0)
            except Exception:
                pass

    def _on_streaming_chunk(self, _seg_idx: int, _chunk_idx: int, chunk: np.ndarray) -> None:
        if self._ring_buffer is None:
            return
        pcm = np.asarray(chunk, dtype=np.float32).reshape(-1)
        self._ring_buffer.push(pcm.tobytes())

    def _stop_streaming_sink(self) -> None:
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
        if not self._stream_available:
            self._status_label.setText("Streaming unavailable on this system.")
            return
        state = "ON" if checked else "OFF"
        mode = "real-time streaming" if checked else "play-after-synthesis"
        self._status_label.setText(f"Streaming playback: {state}  ·  next run will use {mode}")

    # --------------------------------------------------------- Blending
    def _load_blends(self) -> None:
        try:
            from kokoro_studio.blending import load_blends as _ld
            self._loaded_blends = _ld(self._blend_dict_path)
        except ImportError:
            self._loaded_blends = {}

    # --------------------------------------------------------- State helpers
    def _set_feature_controls_enabled(self, enabled: bool) -> None:
        for btn in (
            self._history_btn, self._batch_btn, self._profiles_btn,
            self._blend_btn, self._pron_btn,
            self._ssml_help_btn, self._dialogue_help_btn, self._settings_btn,
            self._open_doc_btn,
        ):
            btn.setEnabled(enabled)
        self._voice_list.setEnabled(enabled)
        self._pron_checkbox.setEnabled(enabled)
        self._ssml_checkbox.setEnabled(enabled)

    def _update_button_states(self) -> None:
        running = self._worker is not None and self._worker.isRunning()
        text_ok = bool(self._editor.toPlainText().strip())
        has_audio = self._last_audio_path is not None and Path(self._last_audio_path).exists()
        self._generate_btn.setEnabled(text_ok and not running)
        self._preview_btn.setEnabled(bool(self._current_voice) and not running)
        self._play_btn.setEnabled(has_audio and not running)
        self._open_folder_btn.setEnabled(True)
        self._speed_spin.setEnabled(not running)
        self._speed_slider.setEnabled(not running)
        self._format_combo.setEnabled(not running)
        self._stream_checkbox.setEnabled(self._stream_available)
        if hasattr(self, "_gen_act"):
            self._gen_act.setEnabled(text_ok and not running)
            self._prev_act.setEnabled(bool(self._current_voice) and not running)
            self._save_act.setEnabled(text_ok and not running)

    # --------------------------------------------------------- Window close
    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            ans = QMessageBox.question(
                self, "Generation in progress",
                "A synthesis is still running. Stop it and exit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return
            self._worker.request_stop()
            if not self._worker.wait(3000):
                print("[KokoroStudio] worker did not stop within 3s; forcing termination.", file=sys.stderr)
                self._worker.terminate()
                self._worker.wait(1000)
        self._stop_streaming_sink()
        try:
            self._player.stop()
        except Exception:
            pass
        super().closeEvent(event)
