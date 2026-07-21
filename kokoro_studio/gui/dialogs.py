# -*- coding: utf-8 -*-
"""Feature windows (QDialog subclasses) for Kokoro Studio."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSlider, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from kokoro_studio.audio_processing import PostProcessingParams, default_processing_params
from kokoro_studio.blending import VoiceBlend
from kokoro_studio.engine import (
    DEFAULT_VOICE, OUTPUT_FORMATS, SAMPLE_RATE, VOICES, generate_speech,
    get_voice_info, list_voices,
)
from kokoro_studio.history import GenerationHistory, HistoryEntry
from kokoro_studio.gui.theme import (
    DIALOGUE_HELP_TTS_SAMPLE, SSML_HELP_SAMPLE, SSML_HELP_TTS_SAMPLE,
    get_settings_qss, default_output_dir, default_output_path, format_bytes,
    format_duration, preview_phrase_for_lang,
)

from PySide6.QtCore import QSettings


def _resolve_settings_qss() -> str:
    """Read the current theme mode from QSettings and return the matching dialog QSS."""
    _s = QSettings("Kokoro Studio", "Kokoro Studio")
    _mode = _s.value("theme", "dark", type=str)
    return get_settings_qss(_mode)


from kokoro_studio.audiobook import (
    AudiobookProject, ChapterInfo, _safe_filename,
    generate_audiobook,
)

from kokoro_studio.profiles import (
    BUILTIN_PROFILES, CharacterProfile, is_valid_profile_name,
    load_profiles, save_profiles,
)


# ---------------------------------------------------------------------------
# Settings / Info dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Application-info dialog: About, Shortcuts, Support, License."""

    _DONATE_BTC = "bc1qcqycagy7p0tf4vc682ygdq522jee0cterllcv6"
    _DONATE_ETH = "0x0a6415FcBf54A46C4b21851493a0B387e8c23c94"
    _CREATOR_HANDLE = "MattiaAlessi"
    _VERSION_DISPLAY = "0.1.0"

    _SHORTCUTS = (
        ("Ctrl+G", "Generate audio from editor text"),
        ("Ctrl+P", "Preview the selected voice"),
        ("Ctrl+O", "Open a .txt / .pdf / .epub document"),
        ("Ctrl+S", "Save editor text as a .txt file"),
        ("Ctrl+Z", "Undo (in the editor)"),
        ("Ctrl+Y", "Redo (in the editor) — Cmd+Shift+Z on macOS"),
        ("Space", "Play / Pause last generated audio"),
        ("Ctrl+Shift+N", "New project"),
        ("Ctrl+Shift+O", "Open project (.ksproj)"),
        ("Ctrl+Shift+S", "Save project (.ksproj)"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kokoro Studio · Settings & Info")
        self.resize(680, 520)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(_resolve_settings_qss())

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

    def _build_about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        title = QLabel("🎙  Kokoro Studio")
        title.setObjectName("SettingsH1")
        layout.addWidget(title)

        subtitle = QLabel(f"v{self._VERSION_DISPLAY}  ·  Local neural text-to-speech")
        subtitle.setObjectName("AddrLabel")
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        creator_url = f"https://github.com/{self._CREATOR_HANDLE}"
        info = QLabel(
            "A free, offline, private desktop GUI for the "
            "<a href='https://huggingface.co/hexgrad/Kokoro-82M'>Kokoro-82M"
            "</a> neural TTS model.  "
            "29 built-in voices · real-time streaming · multi-format "
            "export (WAV / MP3 / FLAC / OGG) · pronunciation dictionary · "
            "multi-speaker dialogue mode · SSML-lite controls · "
            "voice blending · character profiles · emotion/style sliders · "
            "audio post-processing · generation history · batch queue · "
            "audiobook chapter builder · project files · CLI batch mode · "
            "local REST API server · light/dark theme.<br><br>"
            f"<b>Created by:</b> <a href='{creator_url}'>{self._CREATOR_HANDLE}</a> on GitHub."
            "<br><br>"
            "<b>Engine:</b> Kokoro-82M by hexgrad &amp; the Kokoro contributors."
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
            "Built with PySide6 · kokoro · soundfile · lameenc · "
            "pypdf · ebooklib · beautifulsoup4"
        )
        footer.setObjectName("AddrLabel")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        return page

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
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

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

        layout.addWidget(self._build_address_row("Bitcoin (BTC)", self._DONATE_BTC))
        layout.addWidget(self._build_address_row("Ethereum (ETH)", self._DONATE_ETH))
        layout.addStretch(1)
        return page

    def _build_address_row(self, label_text: str, address: str) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)

        lbl = QLabel(label_text)
        lbl.setObjectName("AddrLabel")
        lbl.setMinimumWidth(110)
        hl.addWidget(lbl)

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
            lambda _checked=False, addr=address, btn=copy_btn: self._copy_and_flash(addr, btn)
        )
        hl.addWidget(copy_btn)

        return row

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
            "v2.0</b>.<br><br>"
            "Permits personal, educational, and commercial use, "
            "modifications, and redistribution — provided the original "
            "copyright notice and donation info are preserved in any "
            "redistribution.<br><br>"
            "The full text lives in the <code>LICENSE</code> file at the "
            "project root. See also <code>DONATIONS.md</code> for the "
            "donation channels list."
        )
        body.setObjectName("SettingsBlock")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        layout.addWidget(body)
        layout.addStretch(1)
        return page

    def _copy_and_flash(self, address: str, button: QPushButton) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(address)
        original = button.text()
        button.setText("Copied!")
        button.setEnabled(False)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1400, lambda b=button, txt=original: self._restore_copy_btn(b, txt))

    @staticmethod
    def _restore_copy_btn(button: QPushButton, original_text: str) -> None:
        button.setText(original_text)
        button.setEnabled(True)


# ---------------------------------------------------------------------------
# Voice Blending dialog
# ---------------------------------------------------------------------------

class BlendVoiceDialog(QDialog):
    """Standalone window for creating / previewing custom voice blends."""

    blend_saved = Signal(str, object)

    def __init__(self, loaded_blends: dict, blend_path: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("🎛  Voice Blending")
        self.resize(520, 360)
        self.setStyleSheet(_resolve_settings_qss())

        self._loaded_blends = loaded_blends
        self._blend_path = blend_path
        self._preview_in_progress = False
        self._preview_player: Optional[QMediaPlayer] = None
        self._preview_audio_out: Optional[QAudioOutput] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Create a custom voice blend")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        # Voice A / Voice B row
        ab_row = QHBoxLayout()
        ab_row.setSpacing(12)
        self._voice_a_combo = QComboBox()
        self._voice_b_combo = QComboBox()
        for v in list_voices():
            self._voice_a_combo.addItem(v, v)
            self._voice_b_combo.addItem(v, v)
        self._voice_a_combo.setCurrentText("af_bella")
        self._voice_b_combo.setCurrentText("af_sarah")

        a_box = QVBoxLayout()
        a_lbl = QLabel("Voice A")
        a_lbl.setObjectName("AddrLabel")
        a_box.addWidget(a_lbl)
        a_box.addWidget(self._voice_a_combo)
        b_box = QVBoxLayout()
        b_lbl = QLabel("Voice B")
        b_lbl.setObjectName("AddrLabel")
        b_box.addWidget(b_lbl)
        b_box.addWidget(self._voice_b_combo)
        ab_row.addLayout(a_box, 1)
        ab_row.addLayout(b_box, 1)
        root.addLayout(ab_row)

        # Alpha slider + spin
        alpha_row = QHBoxLayout()
        alpha_row.setSpacing(8)
        self._alpha_slider = QSlider(Qt.Horizontal)
        self._alpha_slider.setRange(0, 100)
        self._alpha_slider.setValue(50)
        self._alpha_spin = QDoubleSpinBox()
        self._alpha_spin.setDecimals(2)
        self._alpha_spin.setSingleStep(0.05)
        self._alpha_spin.setRange(0.0, 1.0)
        self._alpha_spin.setValue(0.50)
        self._alpha_spin.setMinimumWidth(72)
        alpha_row.addWidget(QLabel("Mix (A → B)"))
        alpha_row.addWidget(self._alpha_slider, 1)
        alpha_row.addWidget(self._alpha_spin)
        root.addLayout(alpha_row)

        # Name + actions
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(QLabel("Name"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(self._default_name())
        action_row.addWidget(self._name_edit, 1)

        self._preview_btn = QPushButton("▶  Preview")
        self._preview_btn.setProperty("role", "ghost")
        self._save_btn = QPushButton("💾  Save blend")
        self._save_btn.setProperty("role", "primary")
        action_row.addWidget(self._preview_btn)
        action_row.addWidget(self._save_btn)
        root.addLayout(action_row)

        self._count_label = QLabel(f"{len(loaded_blends)} blends saved")
        self._count_label.setObjectName("Counter")
        root.addWidget(self._count_label)

        root.addStretch(1)

        # Wire internal controls
        self._alpha_slider.valueChanged.connect(self._on_slider_changed)
        self._alpha_spin.valueChanged.connect(self._on_spin_changed)
        self._voice_a_combo.currentIndexChanged.connect(self._update_placeholder)
        self._voice_b_combo.currentIndexChanged.connect(self._update_placeholder)
        self._save_btn.clicked.connect(self._on_save)
        self._preview_btn.clicked.connect(self._on_preview)

    def _default_name(self) -> str:
        va = self._voice_a_combo.currentText() if self._voice_a_combo else "af_heart"
        vb = self._voice_b_combo.currentText() if self._voice_b_combo else "af_heart"
        alpha = self._alpha_spin.value() if self._alpha_spin else 0.5
        short_a = va.split("_", 1)[1] if "_" in va else va
        short_b = vb.split("_", 1)[1] if "_" in vb else vb
        if short_a == short_b:
            return f"{short_a}_shift{int(round(alpha * 100))}"
        return f"{short_a}_{short_b}_{int(round(alpha * 100))}"

    def _update_placeholder(self) -> None:
        self._name_edit.setPlaceholderText(self._default_name())

    def _on_slider_changed(self, v: int) -> None:
        self._alpha_spin.blockSignals(True)
        self._alpha_spin.setValue(v / 100.0)
        self._alpha_spin.blockSignals(False)

    def _on_spin_changed(self, v: float) -> None:
        self._alpha_slider.blockSignals(True)
        self._alpha_slider.setValue(int(round(v * 100)))
        self._alpha_slider.blockSignals(False)

    def _current_blend(self) -> VoiceBlend:
        return VoiceBlend(
            voice_a=self._voice_a_combo.currentText(),
            voice_b=self._voice_b_combo.currentText(),
            alpha=round(self._alpha_spin.value(), 4),
        )

    def _on_save(self) -> None:
        from kokoro_studio.blending import is_valid_blend_name, save_blends
        name = self._name_edit.text().strip() or self._default_name()
        blend = self._current_blend()
        if not is_valid_blend_name(name):
            QMessageBox.warning(
                self, "Invalid blend name",
                "Blend names must match `[A-Za-z_][A-Za-z0-9_]*`.\n"
                f"You provided: {name!r}"
            )
            return
        if name in VOICES:
            QMessageBox.warning(
                self, "Name reserved",
                f"{name!r} is the name of a built-in voice. Choose a different name."
            )
            return
        new_dict = dict(self._loaded_blends)
        if name in new_dict:
            ans = QMessageBox.question(
                self, "Overwrite blend?",
                f"A blend named {name!r} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        new_dict[name] = blend
        try:
            save_blends(self._blend_path, new_dict, reserved_names=VOICES)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Could not save blend", f"{type(e).__name__}: {e}")
            return
        self._loaded_blends.clear()
        self._loaded_blends.update(new_dict)
        self._count_label.setText(f"{len(new_dict)} blends saved")
        self.blend_saved.emit(name, blend)

    def _on_preview(self) -> None:
        if self._preview_in_progress:
            return
        if self._preview_player is not None:
            self._preview_player.stop()
        blend = self._current_blend()
        phrase = "Hello! This is a quick preview of my voice as a blend."
        out_path = default_output_path(
            f"blend_{int(round(blend.alpha * 100))}_{blend.voice_a}_{blend.voice_b}",
            "wav",
        )
        self._preview_in_progress = True
        try:
            audio = generate_speech(
                text=phrase, voice_blend=blend, output_path=out_path, speed=1.0
            )
        except Exception as e:
            QMessageBox.critical(self, "Blend preview failed", f"{type(e).__name__}: {e}")
            return
        finally:
            self._preview_in_progress = False
        # Play locally
        self._preview_player = QMediaPlayer(self)
        self._preview_audio_out = QAudioOutput(self)
        self._preview_player.setAudioOutput(self._preview_audio_out)
        self._preview_player.setSource(QUrl.fromLocalFile(out_path))
        self._preview_player.play()


# ---------------------------------------------------------------------------
# Generation History dialog
# ---------------------------------------------------------------------------

class HistoryDialog(QDialog):
    """Standalone window for browsing / replaying / reloading past generations."""

    load_text_requested = Signal(str)
    play_requested = Signal(str)
    reexport_requested = Signal(str)

    def __init__(self, history: GenerationHistory, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("🕒  Generation History")
        self.resize(760, 480)
        self.setStyleSheet(_resolve_settings_qss())

        self._history = history

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Generation History")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._play_btn = QPushButton("▶  Play")
        self._load_btn = QPushButton("📋  Load text")
        self._export_btn = QPushButton("💾  Re-export")
        self._delete_btn = QPushButton("🗑  Delete")
        self._delete_btn.setProperty("role", "danger")
        for btn in (self._play_btn, self._load_btn, self._export_btn, self._delete_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Time", "Voice", "Speed", "Duration", "Format", "Text snippet"]
        )
        for i in range(5):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(False)
        root.addWidget(self._table, 1)

        self._play_btn.clicked.connect(self._on_play)
        self._load_btn.clicked.connect(self._on_load)
        self._export_btn.clicked.connect(self._on_reexport)
        self._delete_btn.clicked.connect(self._on_delete)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._refresh()
        self._on_selection_changed()

    def _refresh(self) -> None:
        entries = self._history.get_recent(limit=50)
        self._table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self._table.setItem(row, 0, QTableWidgetItem(str(entry.created_at)))
            self._table.setItem(row, 1, QTableWidgetItem(entry.voice))
            self._table.setItem(row, 2, QTableWidgetItem(f"{entry.speed:.2f}x"))
            self._table.setItem(row, 3, QTableWidgetItem(f"{entry.duration_s:.2f}s"))
            self._table.setItem(row, 4, QTableWidgetItem(entry.format))
            snippet = entry.text.replace("\n", " ")[:80]
            self._table.setItem(row, 5, QTableWidgetItem(snippet))
            self._table.item(row, 0).setData(Qt.UserRole, entry.id)

    def _selected_entry(self) -> Optional[HistoryEntry]:
        selected = self._table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        entry_id = self._table.item(row, 0).data(Qt.UserRole)
        return self._history.get_by_id(entry_id)

    def _on_selection_changed(self) -> None:
        enabled = bool(self._table.selectedItems())
        self._play_btn.setEnabled(enabled)
        self._load_btn.setEnabled(enabled)
        self._export_btn.setEnabled(enabled)
        self._delete_btn.setEnabled(enabled)

    def _on_play(self) -> None:
        entry = self._selected_entry()
        if entry and Path(entry.audio_path).exists():
            self.play_requested.emit(entry.audio_path)
        elif entry:
            QMessageBox.warning(self, "File not found", f"The audio file no longer exists:\n{entry.audio_path}")

    def _on_load(self) -> None:
        entry = self._selected_entry()
        if entry:
            self.load_text_requested.emit(entry.text)

    def _on_reexport(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        src = Path(entry.audio_path)
        if not src.exists():
            QMessageBox.warning(self, "File not found", f"The audio file no longer exists:\n{entry.audio_path}")
            return
        default = str(default_output_dir() / f"Kokoro_reexport_{src.name}")
        dest, _ = QFileDialog.getSaveFileName(
            self, "Re-export audio", default,
            f"Audio files (*.{entry.format});;All files (*.*)",
        )
        if dest:
            try:
                shutil.copy2(str(src), dest)
            except OSError as e:
                QMessageBox.critical(self, "Re-export failed", f"{type(e).__name__}: {e}")

    def _on_delete(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        reply = QMessageBox.question(
            self, "Delete history entry?",
            "Remove this generation from history?\nThe audio file will NOT be deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._history.delete(entry.id)
            self._refresh()


# ---------------------------------------------------------------------------
# Pronunciation Dictionary dialog
# ---------------------------------------------------------------------------

class PronunciationDialog(QDialog):
    """Standalone window for editing the pronunciation dictionary."""

    rules_saved = Signal(dict)

    def __init__(self, rules: dict, path: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("📖  Pronunciation Dictionary")
        self.resize(520, 420)
        self.setStyleSheet(_resolve_settings_qss())

        self._rules = dict(rules)
        self._path = path

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Pronunciation Dictionary")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "Map each whole-word \"find\" to a \"replace\" string. "
            "Case-sensitive. Longest rules win. Empty replacement = delete.\n"
            f"Path: {path}"
        )
        intro.setWordWrap(True)
        intro.setObjectName("SettingsBlock")
        root.addWidget(intro)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Find (whole word)", "Replace"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.verticalHeader().setVisible(False)

        for key, val in self._rules.items():
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(key))
            self._table.setItem(r, 1, QTableWidgetItem(val))

        root.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add row")
        add_btn.setProperty("role", "ghost")
        del_btn = QPushButton("− Remove selected")
        del_btn.setProperty("role", "ghost")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        self._count_label = QLabel(f"{len(self._rules)} rules currently")
        btn_row.addWidget(self._count_label)
        root.addLayout(btn_row)

        bbox = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_btn = bbox.button(QDialogButtonBox.Save)
        save_btn.setProperty("role", "primary")
        save_btn.setText("Save")
        root.addWidget(bbox)

        add_btn.clicked.connect(self._on_add)
        del_btn.clicked.connect(self._on_remove)
        bbox.accepted.connect(self._on_save)
        bbox.rejected.connect(self.reject)

    def _on_add(self) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem(""))
        self._table.setItem(r, 1, QTableWidgetItem(""))
        self._table.editItem(self._table.item(r, 0))

    def _on_remove(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)

    def _on_save(self) -> None:
        from kokoro_studio.pronunciation import save_dictionary
        new_rules: dict = {}
        duplicates = set()
        for r in range(self._table.rowCount()):
            fk_item = self._table.item(r, 0)
            rv_item = self._table.item(r, 1)
            fk = fk_item.text().strip() if fk_item else ""
            if not fk:
                continue
            if fk in new_rules:
                duplicates.add(fk)
            new_rules[fk] = rv_item.text() if rv_item else ""
        if duplicates:
            QMessageBox.warning(
                self, "Duplicate find-keys",
                "These `find` keys appear more than once; the last one wins:\n  · "
                + "\n  · ".join(sorted(duplicates))
            )
        try:
            save_dictionary(self._path, new_rules)
        except OSError as e:
            QMessageBox.critical(self, "Could not save dictionary", f"{type(e).__name__}: {e}")
            return
        self._rules = new_rules
        self.rules_saved.emit(new_rules)
        self._count_label.setText(f"{len(new_rules)} rules currently")
        self.accept()


# ---------------------------------------------------------------------------
# Batch Generation Queue dialog
# ---------------------------------------------------------------------------

class BatchQueueDialog(QDialog):
    """Standalone window for managing and running a batch generation queue.

    Users can add items from the editor text, from text files (one item per
    line or full-file), or manually via a text area.  The queue processes
    items sequentially in a background thread, showing per-item progress
    and a final summary report.
    """

    def __init__(
        self,
        editor_text: str,
        current_voice: str,
        current_speed: float,
        current_format: str,
        pronunciation_rules: Optional[dict] = None,
        blends: Optional[dict] = None,
        post_process_params: Optional[PostProcessingParams] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("📦  Batch Generation Queue")
        self.resize(800, 540)
        self.setStyleSheet(_resolve_settings_qss())

        self._editor_text = editor_text
        self._current_voice = current_voice
        self._current_speed = current_speed
        self._current_format = current_format
        self._pronunciation_rules = pronunciation_rules
        self._blends = blends
        self._post_process_params = post_process_params

        # Internal state
        self._items: list = []  # list of BatchQueueItem
        self._worker: Optional[QThread] = None
        self._running = False
        self._output_dir: Path = default_output_dir()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # -- Title row --
        title_row = QHBoxLayout()
        title = QLabel("Batch Generation Queue")
        title.setObjectName("SettingsH1")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._count_label = QLabel("0 items queued")
        self._count_label.setObjectName("Counter")
        self._count_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        title_row.addWidget(self._count_label)
        root.addLayout(title_row)

        # -- Settings row --
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        self._voice_combo = QComboBox()
        voices = list_voices()
        for v in voices:
            self._voice_combo.addItem(v, v)
        if current_voice in voices:
            self._voice_combo.setCurrentText(current_voice)
        self._voice_combo.setMinimumWidth(140)
        settings_row.addWidget(QLabel("Voice:"))
        settings_row.addWidget(self._voice_combo)

        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setDecimals(2)
        self._speed_spin.setSingleStep(0.05)
        self._speed_spin.setRange(0.1, 3.0)
        self._speed_spin.setValue(current_speed)
        self._speed_spin.setSuffix("x")
        self._speed_spin.setMinimumWidth(80)
        settings_row.addWidget(QLabel("Speed:"))
        settings_row.addWidget(self._speed_spin)

        self._format_combo = QComboBox()
        for f in OUTPUT_FORMATS:
            self._format_combo.addItem(f.upper(), f)
        if current_format.upper() in [f.upper() for f in OUTPUT_FORMATS]:
            self._format_combo.setCurrentText(current_format.upper())
        else:
            self._format_combo.setCurrentText("WAV")
        settings_row.addWidget(QLabel("Format:"))
        settings_row.addWidget(self._format_combo)

        settings_row.addStretch(1)

        self._output_dir_label = QLabel(f"Output: {self._output_dir}")
        self._output_dir_label.setObjectName("Counter")
        self._output_dir_label.setStyleSheet("font-size: 10px;")
        settings_row.addWidget(self._output_dir_label)
        self._output_dir_btn = QPushButton("📁")
        self._output_dir_btn.setProperty("role", "ghost")
        self._output_dir_btn.setFixedSize(32, 32)
        self._output_dir_btn.setToolTip("Choose output directory")
        settings_row.addWidget(self._output_dir_btn)

        root.addLayout(settings_row)

        # -- Add items row --
        add_row = QHBoxLayout()
        add_row.setSpacing(8)

        self._add_editor_btn = QPushButton("📝  Add editor text")
        self._add_editor_btn.setProperty("role", "ghost")
        add_row.addWidget(self._add_editor_btn)

        self._add_file_btn = QPushButton("📂  Add from file")
        self._add_file_btn.setProperty("role", "ghost")
        self._add_file_btn.setToolTip(
            "Import a .txt file. Paragraphs (separated by blank lines)"
            " become individual queue items."
        )
        add_row.addWidget(self._add_file_btn)

        self._add_text_btn = QPushButton("✏️  Add custom text")
        self._add_text_btn.setProperty("role", "ghost")
        add_row.addWidget(self._add_text_btn)

        add_row.addStretch(1)

        self._remove_btn = QPushButton("−  Remove selected")
        self._remove_btn.setProperty("role", "ghost")
        add_row.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("🗑  Clear all")
        self._clear_btn.setProperty("role", "ghost")
        add_row.addWidget(self._clear_btn)

        root.addLayout(add_row)

        # -- Queue table --
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "#", "Label", "Voice", "Speed", "Format", "Status",
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in range(2, 6):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        # -- Progress row --
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(16)
        progress_row.addWidget(self._progress_bar, 1)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("Counter")
        progress_row.addWidget(self._progress_label)
        root.addLayout(progress_row)

        # -- Action buttons --
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch(1)

        self._start_btn = QPushButton("▶  Start batch")
        self._start_btn.setProperty("role", "primary")
        self._start_btn.setEnabled(False)
        action_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setProperty("role", "danger")
        self._stop_btn.setVisible(False)
        action_row.addWidget(self._stop_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        action_row.addWidget(close_btn)

        root.addLayout(action_row)

        # -- Wire signals --
        self._add_editor_btn.clicked.connect(self._on_add_editor)
        self._add_file_btn.clicked.connect(self._on_add_file)
        self._add_text_btn.clicked.connect(self._on_add_text)
        self._remove_btn.clicked.connect(self._on_remove)
        self._clear_btn.clicked.connect(self._on_clear)
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn.clicked.connect(self._on_stop)
        self._output_dir_btn.clicked.connect(self._on_choose_output_dir)
        self._table.itemSelectionChanged.connect(self._update_button_states)

        self._update_button_states()

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _add_item(self, text: str, label: str = "") -> None:
        """Build a BatchQueueItem from the current settings and add it."""
        from kokoro_studio.gui.batch_worker import BatchQueueItem

        voice = self._voice_combo.currentData() or self._current_voice
        speed = self._speed_spin.value()
        fmt = (self._format_combo.currentData() or self._current_format)
        n = len(self._items) + 1
        fname = f"batch_{n:03d}_{voice.replace('.', '_')}.{fmt}"
        out_path = str(self._output_dir / fname)

        item = BatchQueueItem(
            text=text,
            voice=voice,
            speed=speed,
            output_path=out_path,
            output_format=fmt,
            label=label or fname,
        )
        self._items.append(item)
        self._refresh_table()

    def _on_add_editor(self) -> None:
        text = self._editor_text.strip()
        if not text:
            QMessageBox.information(self, "No text", "The editor is empty.")
            return
        self._add_item(text, label="editor text")

    def _on_add_file(self) -> None:
        start_dir = str(default_output_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "Add text file", start_dir,
            "Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            QMessageBox.critical(self, "Read failed", f"{type(e).__name__}: {e}")
            return

        # Split into paragraphs (double-newline) and add each non-empty block.
        blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
        if not blocks:
            # Fallback: split by single newlines.
            blocks = [b.strip() for b in content.split("\n") if b.strip()]
        if not blocks:
            QMessageBox.information(self, "Empty file", "No non-empty text found.")
            return

        fname_stem = Path(path).stem
        for i, block in enumerate(blocks):
            self._add_item(block, label=f"{fname_stem} #{i + 1}")

    def _on_add_text(self) -> None:
        """Open a small dialog to type/paste custom text."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Add custom text")
        dlg.resize(480, 300)
        dlg.setStyleSheet(_resolve_settings_qss())
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        edit = QPlainTextEdit()
        edit.setPlaceholderText("Type or paste the text to synthesise…")
        edit.setMinimumHeight(160)
        layout.addWidget(edit, 1)

        bbox = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok_btn = bbox.button(QDialogButtonBox.Ok)
        ok_btn.setProperty("role", "primary")
        ok_btn.setText("Add to queue")
        bbox.accepted.connect(dlg.accept)
        bbox.rejected.connect(dlg.reject)
        layout.addWidget(bbox)

        if dlg.exec() == QDialog.Accepted:
            text = edit.toPlainText().strip()
            if text:
                self._add_item(text)

    def _on_remove(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        for r in rows:
            if r < len(self._items):
                self._items.pop(r)
        self._refresh_table()

    def _on_clear(self) -> None:
        if not self._items:
            return
        ans = QMessageBox.question(
            self, "Clear queue?",
            f"Remove all {len(self._items)} items from the queue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self._items.clear()
            self._refresh_table()

    def _on_choose_output_dir(self) -> None:
        start = str(self._output_dir)
        path = QFileDialog.getExistingDirectory(
            self, "Choose output directory", start,
        )
        if path:
            self._output_dir = Path(path)
            self._output_dir_label.setText(f"Output: {self._output_dir}")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        self._table.setRowCount(len(self._items))
        for idx, item in enumerate(self._items):
            self._table.setItem(idx, 0, QTableWidgetItem(str(idx + 1)))
            label = item.label or Path(item.output_path).stem
            self._table.setItem(idx, 1, QTableWidgetItem(label))
            self._table.setItem(idx, 2, QTableWidgetItem(item.voice))
            self._table.setItem(idx, 3, QTableWidgetItem(f"{item.speed:.2f}x"))
            self._table.setItem(idx, 4, QTableWidgetItem(item.output_format.upper()))
            self._table.setItem(idx, 5, QTableWidgetItem("⏳ Queued"))
        self._count_label.setText(f"{len(self._items)} item{'s' if len(self._items) != 1 else ''} queued")
        self._update_button_states()

    def _update_button_states(self) -> None:
        has_items = len(self._items) > 0
        has_selection = bool(self._table.selectedItems())
        self._start_btn.setEnabled(has_items and not self._running)
        self._remove_btn.setEnabled(has_selection and not self._running)
        self._clear_btn.setEnabled(has_items and not self._running)
        self._add_editor_btn.setEnabled(not self._running)
        self._add_file_btn.setEnabled(not self._running)
        self._add_text_btn.setEnabled(not self._running)
        self._voice_combo.setEnabled(not self._running)
        self._speed_spin.setEnabled(not self._running)
        self._format_combo.setEnabled(not self._running)
        self._output_dir_btn.setEnabled(not self._running)

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        from kokoro_studio.gui.batch_worker import BatchWorker

        if self._running or not self._items:
            return
        self._running = True
        self._update_button_states()
        self._start_btn.setVisible(False)
        self._stop_btn.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_label.setText("Starting…")

        for row in range(self._table.rowCount()):
            self._table.item(row, 5).setText("⏳ Queued")

        self._worker = BatchWorker(
            items=list(self._items),
            pronunciation_rules=self._pronunciation_rules,
            blends=self._blends,
            post_process_params=self._post_process_params,
        )
        self._worker.item_progress.connect(self._on_item_progress)
        self._worker.item_done.connect(self._on_item_done)
        self._worker.finished_ok.connect(self._on_batch_finished)
        self._worker.failed.connect(self._on_batch_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._progress_label.setText("Stopping…")
            self._stop_btn.setEnabled(False)
            self._worker.request_stop()

    def _on_item_progress(self, current: int, total: int, label: str) -> None:
        pct = int(current / total * 100) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._progress_label.setText(f"Item {current} / {total}")
        # Mark current item as generating
        row = current - 1
        if 0 <= row < self._table.rowCount():
            self._table.item(row, 5).setText("⏳ Generating…")
            self._table.scrollToItem(self._table.item(row, 0))

    def _on_item_done(self, index: int, result) -> None:
        if 0 <= index < self._table.rowCount():
            if result.success:
                dur = format_duration(result.duration_s)
                self._table.item(index, 5).setText(f"✅ {dur}")
            else:
                short = result.error_msg[:40]
                self._table.item(index, 5).setText(f"❌ {short}")

    def _on_batch_finished(self, summary) -> None:
        self._progress_bar.setValue(100)
        parts = []
        if summary.succeeded > 0:
            total_audio = format_duration(summary.total_audio_duration_s)
            elapsed = format_duration(summary.elapsed_s)
            parts.append(f"{summary.succeeded} succeeded ({total_audio} in {elapsed})")
        if summary.failed > 0:
            parts.append(f"{summary.failed} failed")
        self._progress_label.setText(
            f"Done  ·  {'  ·  '.join(parts)}" if parts else "Done."
        )

        # Show summary dialog
        msg = (
            f"<b>Batch complete</b><br><br>"
            f"Total items: {summary.total}<br>"
            f"Succeeded: {summary.succeeded}<br>"
            f"Failed: {summary.failed}<br>"
            f"Total audio: {format_duration(summary.total_audio_duration_s)}<br>"
            f"Elapsed: {format_duration(summary.elapsed_s)}<br>"
        )
        QMessageBox.information(self, "Batch Complete", msg)

    def _on_batch_failed(self, error_msg: str) -> None:
        self._progress_label.setText("Failed.")
        QMessageBox.critical(self, "Batch failed", error_msg)

    def _on_worker_finished(self) -> None:
        self._running = False
        self._worker = None
        self._start_btn.setVisible(True)
        self._stop_btn.setVisible(False)
        self._stop_btn.setEnabled(True)
        self._update_button_states()


# ---------------------------------------------------------------------------
# Character Profiles dialog
# ---------------------------------------------------------------------------

class ProfilesDialog(QDialog):
    """Standalone window for managing character profiles.

    Shows all profiles (built-in + user-defined) in a table, lets users
    create new profiles from current settings or edit existing ones.
    """

    profile_applied = Signal(str, object)

    def __init__(
        self,
        profiles: Dict[str, CharacterProfile],
        profiles_path: Path,
        current_voice: str,
        current_speed: float,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("🎭  Character Profiles")
        self.resize(640, 440)
        self.setStyleSheet(_resolve_settings_qss())

        self._profiles = dict(profiles)
        self._profiles_path = profiles_path
        self._current_voice = current_voice
        self._current_speed = current_speed

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Character Profiles")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "One-click presets: select a profile to set voice + speed. "
            "Built-in profiles are always available. Create your own "
            "from the current voice & speed settings."
        )
        intro.setObjectName("SettingsBlock")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # Action row
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._save_as_btn = QPushButton("💾  Save current as…")
        self._save_as_btn.setProperty("role", "ghost")
        action_row.addWidget(self._save_as_btn)

        self._delete_btn = QPushButton("🗑  Delete")
        self._delete_btn.setProperty("role", "danger")
        action_row.addWidget(self._delete_btn)

        action_row.addStretch(1)
        self._count_label = QLabel(f"{len(self._profiles)} profiles")
        self._count_label.setObjectName("Counter")
        action_row.addWidget(self._count_label)
        root.addLayout(action_row)

        # Profile table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels([
            "Profile", "Voice", "Speed", "Description",
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        # Bottom buttons
        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        apply_btn = bbox.button(QDialogButtonBox.Apply)
        apply_btn.setText("Apply selected")
        apply_btn.setProperty("role", "primary")
        ok_btn = bbox.button(QDialogButtonBox.Ok)
        ok_btn.setText("Apply & Close")
        ok_btn.setProperty("role", "primary")
        cancel_btn = bbox.button(QDialogButtonBox.Cancel)
        cancel_btn.setText("Close")

        bbox.accepted.connect(self._on_apply_and_close)
        bbox.rejected.connect(self.reject)
        apply_btn.clicked.connect(self._on_apply_selected)
        root.addWidget(bbox)

        # Wire signals
        self._save_as_btn.clicked.connect(self._on_save_as)
        self._delete_btn.clicked.connect(self._on_delete)
        self._table.itemSelectionChanged.connect(self._update_buttons)
        self._table.itemDoubleClicked.connect(self._on_apply_selected)

        self._refresh()
        self._update_buttons()

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self._table.setRowCount(len(self._profiles))
        for idx, (name, profile) in enumerate(self._profiles.items()):
            badge = "📜 " if profile.is_builtin else "✏️ "
            self._table.setItem(idx, 0, QTableWidgetItem(f"{badge}{name}"))
            self._table.item(idx, 0).setData(Qt.UserRole, name)
            self._table.setItem(idx, 1, QTableWidgetItem(profile.voice))
            self._table.setItem(idx, 2, QTableWidgetItem(f"{profile.speed:.2f}x"))
            self._table.setItem(idx, 3, QTableWidgetItem(profile.description))
            # Mark built-in rows with a subtle visual hint
            if profile.is_builtin:
                for col in range(4):
                    item = self._table.item(idx, col)
                    if item:
                        item.setToolTip("Built-in profile (read-only)")
        self._count_label.setText(f"{len(self._profiles)} profiles")

    def _update_buttons(self) -> None:
        has_selection = bool(self._table.selectedItems())
        self._delete_btn.setEnabled(has_selection)
        if has_selection:
            row = self._table.selectedItems()[0].row()
            name = self._table.item(row, 0).data(Qt.UserRole)
            profile = self._profiles.get(name)
            if profile and profile.is_builtin:
                self._delete_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _selected_profile(self) -> Optional[CharacterProfile]:
        items = self._table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        name = self._table.item(row, 0).data(Qt.UserRole)
        return self._profiles.get(name)

    def _on_apply_selected(self) -> None:
        profile = self._selected_profile()
        if profile:
            self.profile_applied.emit(profile.name, profile)

    def _on_apply_and_close(self) -> None:
        self._on_apply_selected()
        self.accept()

    def _on_save_as(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Save profile as…")
        dlg.resize(380, 200)
        dlg.setStyleSheet(_resolve_settings_qss())
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Profile name:"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. My Custom Voice")
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("Description (optional):"))
        desc_edit = QLineEdit()
        desc_edit.setPlaceholderText("Brief note about this profile…")
        layout.addWidget(desc_edit)

        info = QLabel(
            f"Will save: voice <b>{self._current_voice}</b>, "
            f"speed <b>{self._current_speed:.2f}x</b>"
        )
        info.setObjectName("SettingsBlock")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        bbox = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok_btn = bbox.button(QDialogButtonBox.Ok)
        ok_btn.setText("Save")
        ok_btn.setProperty("role", "primary")
        bbox.accepted.connect(dlg.accept)
        bbox.rejected.connect(dlg.reject)
        layout.addWidget(bbox)
        layout.addStretch(1)

        if dlg.exec() != QDialog.Accepted:
            return

        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "No name", "Please enter a profile name.")
            return
        if not is_valid_profile_name(name):
            QMessageBox.warning(
                self, "Invalid name",
                "Profile names must start with a letter or underscore\n"
                "and contain only letters, digits, and underscores."
            )
            return
        if name in [p.name for p in BUILTIN_PROFILES]:
            QMessageBox.warning(
                self, "Name reserved",
                f"{name!r} is a built-in profile name. Choose a different name."
            )
            return

        desc = desc_edit.text().strip()

        # Check for overwrite of existing user profile
        if name in self._profiles and not self._profiles[name].is_builtin:
            ans = QMessageBox.question(
                self, "Overwrite profile?",
                f"A profile named {name!r} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return

        profile = CharacterProfile(
            name=name,
            voice=self._current_voice,
            speed=self._current_speed,
            description=desc,
            is_builtin=False,
        )
        self._profiles[name] = profile
        try:
            save_profiles(self._profiles_path, self._profiles)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", f"{type(e).__name__}: {e}")
            return
        self._refresh()

    def _on_delete(self) -> None:
        profile = self._selected_profile()
        if profile is None or profile.is_builtin:
            return
        ans = QMessageBox.question(
            self, "Delete profile?",
            f"Remove profile {profile.name!r}?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self._profiles.pop(profile.name, None)
            try:
                save_profiles(self._profiles_path, self._profiles)
            except OSError as e:
                QMessageBox.critical(self, "Delete failed", f"{type(e).__name__}: {e}")
                return
            self._refresh()


# ---------------------------------------------------------------------------
# Audio Post-Processing dialog
# ---------------------------------------------------------------------------

class PostProcessingDialog(QDialog):
    """Standalone window for configuring audio post-processing.

    Lets users toggle and adjust:
      - ✂️  Silence trimming (threshold + min length)
      - 📈  Volume boost/cut (dB)
      - 🌀  Fade in / fade out (duration)
      - ⚡  Peak or loudness normalisation (target level)

    Each section has a detailed description so first-time users understand
    the effect of each option on the final audio.
    """

    # Explanatory texts used across the dialog
    _TRIM_DESC = (
        "Removes silence from the start and end of the audio file. "
        "Useful for cutting out dead air at the beginning or end of a recording."
    )
    _VOL_DESC = (
        "Makes the audio louder or quieter by a fixed amount. "
        "Positive values boost volume, negative values reduce it. "
        "Useful when a voice sounds too quiet or too loud overall."
    )
    _FADE_DESC = (
        "Smoothly ramps the volume up at the start (fade-in) and/or down "
        "at the end (fade-out). Prevents abrupt starts/stops that can "
        "sound like clicks or pops."
    )
    _NORM_DESC = (
        "Adjusts the overall level to a consistent target. "
        "Peak normalisation sets the loudest sample to a specific level. "
        "Loudness normalisation (RMS) matches the average perceived volume, "
        "which can produce more consistent results across different recordings."
    )

    params_changed = Signal(object)  # PostProcessingParams

    def __init__(
        self,
        current_params: PostProcessingParams,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("🎚  Audio Post-Processing")
        self.resize(580, 580)
        self.setMinimumWidth(520)
        self.setStyleSheet(_resolve_settings_qss())

        self._params = current_params

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Audio Post-Processing")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "Apply adjustments to the final audio before saving. "
            "Processing runs in this order: "
            "<b>trim ✂️</b> → <b>volume 📈</b> → <b>fade 🌀</b> → <b>normalise ⚡</b>. "
            "Toggle each feature on/off with its checkbox."
        )
        intro.setObjectName("SettingsBlock")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        root.addWidget(intro)

        # =================================================================
        # ✂️  Trim silence
        # =================================================================
        trim_group = QVBoxLayout()
        trim_group.setSpacing(3)

        self._trim_cb = QCheckBox("✂️  Trim leading / trailing silence")
        self._trim_cb.setChecked(self._params.trim_silence)
        self._trim_cb.setToolTip(
            "When checked, silence at the very start and very end of the "
            "audio will be removed.  Silence in the middle (between words) "
            "is never affected.  Recommended for most use cases."
        )
        trim_group.addWidget(self._trim_cb)

        trim_desc = QLabel(self._TRIM_DESC)
        trim_desc.setWordWrap(True)
        trim_desc.setStyleSheet("font-size: 10px; color: #9DA0A8; padding-left: 27px;")
        trim_group.addWidget(trim_desc)

        trim_opts = QHBoxLayout()
        trim_opts.setSpacing(8)
        trim_opts.setContentsMargins(27, 0, 0, 0)

        trim_threshold_lbl = QLabel("Threshold:")
        trim_threshold_lbl.setToolTip(
            "Loudness level (in dBFS) below which audio is considered 'silence'. "
            "-40 dBFS is a good starting point — quiet enough to remove hiss "
            "but loud enough to keep soft speech.  More negative = more "
            "aggressive (removes more)."
        )
        trim_opts.addWidget(trim_threshold_lbl)
        self._trim_threshold_spin = QDoubleSpinBox()
        self._trim_threshold_spin.setRange(-96.0, -1.0)
        self._trim_threshold_spin.setDecimals(1)
        self._trim_threshold_spin.setSuffix(" dBFS")
        self._trim_threshold_spin.setValue(self._params.trim_threshold_db)
        self._trim_threshold_spin.setToolTip(
            "A threshold of -40 dBFS will remove quiet background noise. "
            "Lower values (e.g. -60) trim more aggressively. "
            "Higher values (e.g. -20) only remove very loud silence."
        )
        trim_opts.addWidget(self._trim_threshold_spin)

        trim_min_lbl = QLabel("Min silence:")
        trim_min_lbl.setToolTip(
            "How many consecutive quiet samples are needed before we cut. "
            "At 24 kHz, 100 samples ≈ 4 ms.  Smaller values trim more "
            "aggressively but may eat into natural pauses between words."
        )
        trim_opts.addWidget(trim_min_lbl)
        self._trim_min_spin = QDoubleSpinBox()
        self._trim_min_spin.setRange(1, 10000)
        self._trim_min_spin.setDecimals(0)
        self._trim_min_spin.setSuffix(" samples")
        self._trim_min_spin.setValue(float(self._params.trim_min_silence_len))
        self._trim_min_spin.setToolTip(
            "100 samples (~4 ms) works well for speech. "
            "Increase for music-like content; decrease for precise trimming."
        )
        trim_opts.addWidget(self._trim_min_spin, 1)
        trim_group.addLayout(trim_opts)
        root.addLayout(trim_group)

        root.addSpacing(2)

        # =================================================================
        # 📈  Volume boost / cut
        # =================================================================
        vol_group = QVBoxLayout()
        vol_group.setSpacing(3)

        self._vol_cb = QCheckBox("📈  Volume boost / cut")
        self._vol_cb.setChecked(self._params.volume_enabled)
        self._vol_cb.setToolTip(
            "When checked, the entire audio is made louder or quieter by "
            "a fixed amount.  Useful for normalising voices that are much "
            "louder or softer than expected."
        )
        vol_group.addWidget(self._vol_cb)

        vol_desc = QLabel(self._VOL_DESC)
        vol_desc.setWordWrap(True)
        vol_desc.setStyleSheet("font-size: 10px; color: #9DA0A8; padding-left: 27px;")
        vol_group.addWidget(vol_desc)

        vol_opts = QHBoxLayout()
        vol_opts.setSpacing(8)
        vol_opts.setContentsMargins(27, 0, 0, 0)

        vol_gain_lbl = QLabel("Gain:")
        vol_gain_lbl.setToolTip(
            "Gain in decibels.  +3 dB = 2x power (noticeably louder). "
            "-3 dB = half the power.  +6 dB = 4x power (significantly louder). "
            "Stay between -6 and +6 dB to avoid distortion."
        )
        vol_opts.addWidget(vol_gain_lbl)
        self._vol_gain_slider = QSlider(Qt.Horizontal)
        self._vol_gain_slider.setRange(-24, 24)
        self._vol_gain_slider.setValue(int(round(self._params.volume_gain_db)))
        self._vol_gain_slider.setToolTip(
            "Drag to adjust.  Small adjustments (1-3 dB) work best. "
            "More than ±12 dB may cause audible distortion."
        )
        vol_opts.addWidget(self._vol_gain_slider, 1)
        self._vol_gain_spin = QDoubleSpinBox()
        self._vol_gain_spin.setRange(-24.0, 24.0)
        self._vol_gain_spin.setDecimals(1)
        self._vol_gain_spin.setSuffix(" dB")
        self._vol_gain_spin.setValue(self._params.volume_gain_db)
        self._vol_gain_spin.setToolTip(
            "Positive = louder, negative = quieter. "
            "Example: -3 dB to reduce volume by half, +6 dB to double it."
        )
        vol_opts.addWidget(self._vol_gain_spin)
        vol_group.addLayout(vol_opts)
        root.addLayout(vol_group)

        root.addSpacing(2)

        # =================================================================
        # 🌀  Fade in / fade out
        # =================================================================
        fade_group = QVBoxLayout()
        fade_group.setSpacing(3)

        self._fade_cb = QCheckBox("🌀  Fade in / fade out")
        self._fade_cb.setChecked(self._params.fade_enabled)
        self._fade_cb.setToolTip(
            "When checked, the audio will smoothly ramp up at the start "
            "and/or ramp down at the end.  A short fade (5-50 ms) removes "
            "click/pop transients.  Longer fades (0.5-2 s) create "
            "dramatic transitions like in podcasts."
        )
        fade_group.addWidget(self._fade_cb)

        fade_desc = QLabel(self._FADE_DESC)
        fade_desc.setWordWrap(True)
        fade_desc.setStyleSheet("font-size: 10px; color: #9DA0A8; padding-left: 27px;")
        fade_group.addWidget(fade_desc)

        fade_opts = QHBoxLayout()
        fade_opts.setSpacing(8)
        fade_opts.setContentsMargins(27, 0, 0, 0)

        fi_lbl = QLabel("Fade in:")
        fi_lbl.setToolTip(
            "Duration of the fade-in ramp.  A short fade (5 ms = 0.005 s) "
            "is enough to remove the initial pop.  Longer fades (0.5-2 s) "
            "smoothly introduce the audio — nice for audiobook chapters."
        )
        fade_opts.addWidget(fi_lbl)
        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setRange(0.0, 5.0)
        self._fade_in_spin.setDecimals(3)
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.setSingleStep(0.005)
        self._fade_in_spin.setValue(self._params.fade_in_duration_s)
        self._fade_in_spin.setToolTip(
            "0.005 s (5 ms) = click removal.  "
            "0.500 s (500 ms) = gentle fade.  "
            "2.000 s (2 s) = dramatic fade."
        )
        fade_opts.addWidget(self._fade_in_spin)

        fo_lbl = QLabel("Fade out:")
        fo_lbl.setToolTip(
            "Duration of the fade-out ramp.  Same idea as fade-in. "
            "A short fade (5 ms) removes the end pop, a longer fade "
            "(1-2 s) creates a smooth ending."
        )
        fade_opts.addWidget(fo_lbl)
        self._fade_out_spin = QDoubleSpinBox()
        self._fade_out_spin.setRange(0.0, 5.0)
        self._fade_out_spin.setDecimals(3)
        self._fade_out_spin.setSuffix(" s")
        self._fade_out_spin.setSingleStep(0.005)
        self._fade_out_spin.setValue(self._params.fade_out_duration_s)
        self._fade_out_spin.setToolTip(
            "0.005 s (5 ms) = click removal.  "
            "0.500 s (500 ms) = gentle fade.  "
            "2.000 s (2 s) = dramatic fade."
        )
        fade_opts.addWidget(self._fade_out_spin)
        fade_opts.addStretch(1)
        fade_group.addLayout(fade_opts)
        root.addLayout(fade_group)

        root.addSpacing(2)

        # =================================================================
        # ⚡  Normalisation
        # =================================================================
        norm_group = QVBoxLayout()
        norm_group.setSpacing(3)

        self._norm_cb = QCheckBox("⚡  Normalise audio")
        self._norm_cb.setChecked(self._params.normalize_enabled)
        self._norm_cb.setToolTip(
            "When checked, the audio level is adjusted to hit a consistent "
            "target.  Choose between peak (loudest sample) or loudness "
            "(average perceived volume) normalisation."
        )
        norm_group.addWidget(self._norm_cb)

        norm_desc = QLabel(self._NORM_DESC)
        norm_desc.setWordWrap(True)
        norm_desc.setStyleSheet("font-size: 10px; color: #9DA0A8; padding-left: 27px;")
        norm_group.addWidget(norm_desc)

        norm_opts = QHBoxLayout()
        norm_opts.setSpacing(8)
        norm_opts.setContentsMargins(27, 0, 0, 0)

        self._norm_mode_combo = QComboBox()
        self._norm_mode_combo.addItem(
            "Peak normalisation — sets the loudest peak to the target level",
            "peak",
        )
        self._norm_mode_combo.addItem(
            "Loudness normalisation (RMS) — matches average perceived volume",
            "loudness",
        )
        self._norm_mode_combo.setToolTip(
            "Peak: adjusts so the single loudest sample hits the target. "
            "Simple, fast, preserves dynamics.\n\n"
            "Loudness (RMS): adjusts so the overall average volume matches. "
            "More consistent across different recordings. "
            "-16 dBFS is the standard for speech content."
        )
        idx = self._norm_mode_combo.findData(self._params.normalize_mode)
        if idx >= 0:
            self._norm_mode_combo.setCurrentIndex(idx)
        norm_opts.addWidget(self._norm_mode_combo, 1)

        target_lbl = QLabel("Target:")
        target_lbl.setToolTip(
            "The desired output level.  For peak mode, -1 dBFS leaves headroom "
            "(prevents clipping in MP3/OGG encoding).  For loudness mode, "
            "-16 dBFS matches the dialogue standard used in broadcast."
        )
        norm_opts.addWidget(target_lbl)
        self._norm_target_spin = QDoubleSpinBox()
        self._norm_target_spin.setRange(-36.0, 0.0)
        self._norm_target_spin.setDecimals(1)
        self._norm_target_spin.setSuffix(" dBFS")
        self._norm_target_spin.setValue(self._params.normalize_target_db)
        self._norm_target_spin.setToolTip(
            "Peak: -1 dBFS (standard, leaves 1 dB headroom). "
            "0 dBFS (maximum, risk of clipping in lossy formats).\n\n"
            "Loudness: -16 dBFS (broadcast speech standard). "
            "-14 dBFS (louder, for podcasts). "
            "-23 dBFS (quieter, EBU standard for film/TV)."
        )
        norm_opts.addWidget(self._norm_target_spin)
        norm_group.addLayout(norm_opts)
        root.addLayout(norm_group)

        root.addStretch(1)

        # Summary chip
        self._summary_label = QLabel("")
        self._summary_label.setObjectName("SettingsBlock")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            "color: #10B981;"
            " background-color: rgba(16,185,129,0.08);"
            " border: 1px solid rgba(16,185,129,0.25);"
            " border-radius: 6px; padding: 6px 10px;"
            " font-size: 11px; font-weight: 600;"
        )
        root.addWidget(self._summary_label)

        # Buttons
        bbox = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Reset
        )
        ok_btn = bbox.button(QDialogButtonBox.Ok)
        ok_btn.setText("Apply")
        ok_btn.setProperty("role", "primary")
        reset_btn = bbox.button(QDialogButtonBox.Reset)
        reset_btn.setText("Reset to defaults")
        reset_btn.setProperty("role", "ghost")
        bbox.accepted.connect(self._on_apply)
        bbox.rejected.connect(self.reject)
        reset_btn.clicked.connect(self._on_reset)
        root.addWidget(bbox)

        # Wire internal controls
        self._trim_cb.toggled.connect(self._refresh_summary)
        self._vol_cb.toggled.connect(self._refresh_summary)
        self._fade_cb.toggled.connect(self._refresh_summary)
        self._norm_cb.toggled.connect(self._refresh_summary)
        self._vol_gain_slider.valueChanged.connect(self._on_vol_slider)
        self._vol_gain_spin.valueChanged.connect(self._on_vol_spin)
        self._norm_mode_combo.currentIndexChanged.connect(self._refresh_summary)
        self._norm_target_spin.valueChanged.connect(self._refresh_summary)

        self._refresh_summary()

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _on_vol_slider(self, v: int) -> None:
        self._vol_gain_spin.blockSignals(True)
        self._vol_gain_spin.setValue(float(v))
        self._vol_gain_spin.blockSignals(False)
        self._refresh_summary()

    def _on_vol_spin(self, v: float) -> None:
        self._vol_gain_slider.blockSignals(True)
        self._vol_gain_slider.setValue(int(round(v)))
        self._vol_gain_slider.blockSignals(False)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        parts = []
        if self._trim_cb.isChecked():
            parts.append("✂️ Trim")
        if self._vol_cb.isChecked():
            parts.append(f"📈 {self._vol_gain_spin.value():+.1f} dB")
        if self._fade_cb.isChecked():
            fi = self._fade_in_spin.value()
            fo = self._fade_out_spin.value()
            parts.append(f"🌀 {fi*1000:.0f}ms / {fo*1000:.0f}ms fade")
        if self._norm_cb.isChecked():
            mode = self._norm_mode_combo.currentData()
            target = self._norm_target_spin.value()
            parts.append(f"⚡ {mode} @ {target:.0f} dBFS")
        if parts:
            self._summary_label.setText("Active:  " + "  ·  ".join(parts))
        else:
            self._summary_label.setText("No processing active.")

    # ------------------------------------------------------------------
    # Apply / Reset
    # ------------------------------------------------------------------

    def _collect_params(self) -> PostProcessingParams:
        return PostProcessingParams(
            trim_silence=self._trim_cb.isChecked(),
            trim_threshold_db=self._trim_threshold_spin.value(),
            trim_min_silence_len=int(self._trim_min_spin.value()),
            volume_enabled=self._vol_cb.isChecked(),
            volume_gain_db=self._vol_gain_spin.value(),
            fade_enabled=self._fade_cb.isChecked(),
            fade_in_duration_s=self._fade_in_spin.value(),
            fade_out_duration_s=self._fade_out_spin.value(),
            normalize_enabled=self._norm_cb.isChecked(),
            normalize_mode=str(self._norm_mode_combo.currentData()),
            normalize_target_db=self._norm_target_spin.value(),
        )

    def _on_apply(self) -> None:
        self.params_changed.emit(self._collect_params())
        self.accept()

    def _on_reset(self) -> None:
        defaults = default_processing_params()
        self._trim_cb.setChecked(defaults.trim_silence)
        self._trim_threshold_spin.setValue(defaults.trim_threshold_db)
        self._trim_min_spin.setValue(float(defaults.trim_min_silence_len))
        self._vol_cb.setChecked(defaults.volume_enabled)
        self._vol_gain_slider.setValue(int(round(defaults.volume_gain_db)))
        self._vol_gain_spin.setValue(defaults.volume_gain_db)
        self._fade_cb.setChecked(defaults.fade_enabled)
        self._fade_in_spin.setValue(defaults.fade_in_duration_s)
        self._fade_out_spin.setValue(defaults.fade_out_duration_s)
        self._norm_cb.setChecked(defaults.normalize_enabled)
        norm_idx = self._norm_mode_combo.findData(defaults.normalize_mode)
        if norm_idx >= 0:
            self._norm_mode_combo.setCurrentIndex(norm_idx)
        self._norm_target_spin.setValue(defaults.normalize_target_db)
        self._refresh_summary()


# ---------------------------------------------------------------------------
# Audiobook Chapter Builder dialog
# ---------------------------------------------------------------------------

class AudiobookDialog(QDialog):
    """Standalone window for building audiobooks from EPUB/TXT documents.

    Lets users:
      1. Load an EPUB or TXT document → chapters are parsed automatically
      2. Assign a voice per chapter (or use a default for all)
      3. Set global speed, format, output directory
      4. Generate separate chapter files and/or a single merged file
      5. Track progress per chapter with a progress bar
    """

    def __init__(
        self,
        current_voice: str,
        current_speed: float,
        current_format: str,
        pronunciation_rules: Optional[dict] = None,
        blends: Optional[dict] = None,
        post_process_params: Optional[PostProcessingParams] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("📚  Audiobook Chapter Builder")
        self.resize(820, 620)
        self.setMinimumSize(720, 520)
        self.setStyleSheet(_resolve_settings_qss())

        # Internal state
        self._chapters: list = []  # list of ChapterInfo
        self._project = None
        self._worker: Optional[QThread] = None
        self._running = False

        # Global settings
        self._default_voice = current_voice
        self._current_speed = current_speed
        self._current_format = current_format
        self._pronunciation_rules = pronunciation_rules
        self._blends = dict(blends) if blends else None
        self._post_process_params = post_process_params
        self._output_dir: Path = default_output_dir()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # -- Title row --
        title_row = QHBoxLayout()
        title = QLabel("Audiobook Chapter Builder")
        title.setObjectName("SettingsH1")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._doc_info_label = QLabel("")
        self._doc_info_label.setObjectName("Counter")
        title_row.addWidget(self._doc_info_label)
        root.addLayout(title_row)

        # -- Document load row --
        doc_row = QHBoxLayout()
        doc_row.setSpacing(8)
        self._load_doc_btn = QPushButton("📂  Open EPUB / TXT document")
        self._load_doc_btn.setProperty("role", "ghost")
        self._load_doc_btn.setToolTip(
            "Load an EPUB (chapters auto-detected) or TXT file "
            "(split by blank-line paragraphs)."
        )
        doc_row.addWidget(self._load_doc_btn)

        self._doc_title_label = QLabel("No document loaded — click Open to start")
        self._doc_title_label.setObjectName("AddrLabel")
        self._doc_title_label.setWordWrap(True)
        doc_row.addWidget(self._doc_title_label, 1)
        root.addLayout(doc_row)

        # -- Global settings row --
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        # Default voice
        self._voice_combo = QComboBox()
        voices = list_voices()
        for v in voices:
            self._voice_combo.addItem(v, v)
        if current_voice in voices:
            self._voice_combo.setCurrentText(current_voice)
        self._voice_combo.setMinimumWidth(140)
        settings_row.addWidget(QLabel("Default voice:"))
        settings_row.addWidget(self._voice_combo)

        # Speed
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setDecimals(2)
        self._speed_spin.setSingleStep(0.05)
        self._speed_spin.setRange(0.1, 3.0)
        self._speed_spin.setValue(current_speed)
        self._speed_spin.setSuffix("x")
        self._speed_spin.setMinimumWidth(80)
        settings_row.addWidget(QLabel("Speed:"))
        settings_row.addWidget(self._speed_spin)

        # Format
        self._format_combo = QComboBox()
        for f in OUTPUT_FORMATS:
            self._format_combo.addItem(f.upper(), f)
        if current_format.upper() in [f.upper() for f in OUTPUT_FORMATS]:
            self._format_combo.setCurrentText(current_format.upper())
        else:
            self._format_combo.setCurrentText("WAV")
        settings_row.addWidget(QLabel("Format:"))
        settings_row.addWidget(self._format_combo)

        settings_row.addStretch(1)

        # Output dir
        self._output_dir_label = QLabel(f"{self._output_dir}")
        self._output_dir_label.setObjectName("Counter")
        self._output_dir_label.setStyleSheet("font-size: 10px;")
        settings_row.addWidget(self._output_dir_label)
        self._output_dir_btn = QPushButton("📁")
        self._output_dir_btn.setProperty("role", "ghost")
        self._output_dir_btn.setFixedSize(32, 32)
        self._output_dir_btn.setToolTip("Choose output directory")
        settings_row.addWidget(self._output_dir_btn)
        root.addLayout(settings_row)

        # -- Export options row --
        export_row = QHBoxLayout()
        export_row.setSpacing(16)
        self._separate_cb = QCheckBox("📄 Generate separate files")
        self._separate_cb.setChecked(True)
        export_row.addWidget(self._separate_cb)
        self._merged_cb = QCheckBox("🔗 Also generate merged file")
        self._merged_cb.setChecked(False)
        export_row.addWidget(self._merged_cb)
        self._gap_label = QLabel("Gap between chapters:")
        export_row.addWidget(self._gap_label)
        self._gap_spin = QDoubleSpinBox()
        self._gap_spin.setDecimals(1)
        self._gap_spin.setSingleStep(0.1)
        self._gap_spin.setRange(0.0, 5.0)
        self._gap_spin.setValue(0.5)
        self._gap_spin.setSuffix("s")
        self._gap_spin.setMinimumWidth(70)
        export_row.addWidget(self._gap_spin)
        export_row.addStretch(1)
        root.addLayout(export_row)

        # -- Chapter table --
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            "✅", "#", "Chapter", "Voice", "Status",
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        # -- Progress row --
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(16)
        progress_row.addWidget(self._progress_bar, 1)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("Counter")
        progress_row.addWidget(self._progress_label)
        root.addLayout(progress_row)

        # -- Action buttons --
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch(1)

        self._select_all_btn = QPushButton("✅ Select all")
        self._select_all_btn.setProperty("role", "ghost")
        self._select_all_btn.setEnabled(False)
        action_row.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton("⬜ Deselect all")
        self._deselect_all_btn.setProperty("role", "ghost")
        self._deselect_all_btn.setEnabled(False)
        action_row.addWidget(self._deselect_all_btn)

        self._apply_voice_btn = QPushButton("🎤  Apply default voice to all")
        self._apply_voice_btn.setProperty("role", "ghost")
        self._apply_voice_btn.setEnabled(False)
        action_row.addWidget(self._apply_voice_btn)

        self._generate_btn = QPushButton("▶  Generate audiobook")
        self._generate_btn.setProperty("role", "primary")
        self._generate_btn.setEnabled(False)
        action_row.addWidget(self._generate_btn)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setProperty("role", "danger")
        self._stop_btn.setVisible(False)
        action_row.addWidget(self._stop_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        action_row.addWidget(close_btn)
        root.addLayout(action_row)

        # -- Wire signals --
        self._load_doc_btn.clicked.connect(self._on_load_document)
        self._output_dir_btn.clicked.connect(self._on_choose_output_dir)
        self._voice_combo.currentIndexChanged.connect(self._on_default_voice_changed)
        self._apply_voice_btn.clicked.connect(self._on_apply_default_voice)
        self._select_all_btn.clicked.connect(self._on_select_all)
        self._deselect_all_btn.clicked.connect(self._on_deselect_all)
        self._generate_btn.clicked.connect(self._on_generate)
        self._stop_btn.clicked.connect(self._on_stop)
        self._table.cellDoubleClicked.connect(self._on_voice_cell_double_clicked)

        self._update_button_states()

    # ------------------------------------------------------------------
    # Document loading
    # ------------------------------------------------------------------

    def _on_load_document(self) -> None:
        start_dir = str(default_output_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open EPUB or TXT document", start_dir,
            "Documents (*.epub *.txt);;All files (*.*)",
        )
        if not path:
            return

        self._status_label_set("Loading document…")
        try:
            from kokoro_studio.document_loader import load_document
            doc = load_document(path)
        except Exception as e:
            QMessageBox.critical(self, "Could not load document",
                                 f"{type(e).__name__}: {e}")
            self._status_label_set("Loading failed.")
            return

        if not doc.chapters:
            QMessageBox.information(self, "Empty document",
                                    "No readable chapters found.")
            self._status_label_set("Document is empty.")
            return

        from kokoro_studio.audiobook import chapters_from_document, AudiobookProject
        chapters = chapters_from_document(doc, default_voice=self._voice_combo.currentText())
        self._chapters = chapters

        # Build project
        self._project = AudiobookProject(
            source_path=Path(path),
            title=doc.title,
            author=doc.author,
            language=doc.language,
            chapters=chapters,
            default_voice=self._voice_combo.currentText(),
            speed=self._speed_spin.value(),
            output_format=self._format_combo.currentData() or "wav",
            output_dir=self._output_dir,
            chapter_gap_s=self._gap_spin.value(),
            post_process_params=self._post_process_params,
            separate_files=self._separate_cb.isChecked(),
            merged_file=self._merged_cb.isChecked(),
            merged_filename=f"{_safe_filename(doc.title)}_audiobook",
        )

        # Update doc info
        info_parts = [f"{len(chapters)} chapters"]
        if doc.author:
            info_parts.append(f"by {doc.author}")
        self._doc_info_label.setText("  ·  ".join(info_parts))

        author_str = f" by {doc.author}" if doc.author else ""
        self._doc_title_label.setText(
            f"📖 <b>{doc.title}</b>{author_str} — {len(chapters)} chapters loaded"
        )
        self._doc_title_label.setTextFormat(Qt.RichText)

        self._refresh_table()
        self._status_label_set(
            f"Loaded {len(chapters)} chapters from {Path(path).name}"
        )

    def _status_label_set(self, text: str) -> None:
        self._progress_label.setText(text)

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        self._table.setRowCount(len(self._chapters))
        for idx, chapter in enumerate(self._chapters):
            # Checkbox column (checked by default)
            cb_item = QTableWidgetItem()
            cb_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            cb_item.setCheckState(Qt.Checked)
            self._table.setItem(idx, 0, cb_item)

            self._table.setItem(idx, 1, QTableWidgetItem(str(chapter.index)))
            self._table.setItem(idx, 2, QTableWidgetItem(chapter.title))
            # Voice combo per chapter
            combo = QComboBox()
            voices = list_voices()
            for v in voices:
                combo.addItem(v, v)
            combo.setCurrentText(chapter.voice)
            combo.currentTextChanged.connect(
                lambda text, i=idx: self._on_chapter_voice_changed(i, text)
            )
            self._table.setCellWidget(idx, 3, combo)
            self._table.setItem(idx, 4, QTableWidgetItem("⏳ Queued"))
        self._update_button_states()

    def _get_selected_chapters(self) -> list:
        """Return only the chapters whose checkbox is checked."""
        return [
            ch for idx, ch in enumerate(self._chapters)
            if idx < self._table.rowCount()
            and self._table.item(idx, 0) is not None
            and self._table.item(idx, 0).checkState() == Qt.Checked
        ]

    def _on_chapter_voice_changed(self, idx: int, voice: str) -> None:
        if 0 <= idx < len(self._chapters):
            from kokoro_studio.audiobook import ChapterInfo
            old = self._chapters[idx]
            self._chapters[idx] = ChapterInfo(
                index=old.index, title=old.title, text=old.text, voice=voice,
            )
            # Update project's chapters too
            if self._project is not None:
                new_chapters = list(self._project.chapters)
                new_chapters[idx] = self._chapters[idx]
                self._project = AudiobookProject(
                    source_path=self._project.source_path,
                    title=self._project.title,
                    author=self._project.author,
                    language=self._project.language,
                    chapters=new_chapters,
                    default_voice=self._project.default_voice,
                    speed=self._project.speed,
                    output_format=self._project.output_format,
                    output_dir=self._project.output_dir,
                    chapter_gap_s=self._project.chapter_gap_s,
                    post_process_params=self._project.post_process_params,
                    separate_files=self._project.separate_files,
                    merged_file=self._project.merged_file,
                    merged_filename=self._project.merged_filename,
                )

    def _on_voice_cell_double_clicked(self, row: int, col: int) -> None:
        if col == 3:  # Voice column (after checkbox + # columns)
            widget = self._table.cellWidget(row, col)
            if isinstance(widget, QComboBox):
                widget.showPopup()

    def _on_default_voice_changed(self) -> None:
        pass  # Voice changes are applied per-chapter via the table combos

    def _on_apply_default_voice(self) -> None:
        """Set all chapter voices to the current default voice."""
        voice = self._voice_combo.currentText()
        for i in range(len(self._chapters)):
            combo = self._table.cellWidget(i, 3)
            if isinstance(combo, QComboBox):
                combo.setCurrentText(voice)

    def _on_select_all(self) -> None:
        """Check all chapter checkboxes."""
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item is not None:
                item.setCheckState(Qt.Checked)

    def _on_deselect_all(self) -> None:
        """Uncheck all chapter checkboxes."""
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item is not None:
                item.setCheckState(Qt.Unchecked)
        self._status_label_set("All chapters deselected — nothing will be generated")

    # ------------------------------------------------------------------
    # Output directory
    # ------------------------------------------------------------------

    def _on_choose_output_dir(self) -> None:
        """Open a folder picker to change the output directory."""
        start = str(self._output_dir)
        path = QFileDialog.getExistingDirectory(
            self, "Choose output directory", start,
        )
        if path:
            self._output_dir = Path(path)
            self._output_dir_label.setText(f"📁 {self._output_dir}")
            self._output_dir_label.setToolTip(str(self._output_dir))
            self._status_label_set(f"Output folder set to: {self._output_dir}")
            if self._project is not None:
                self._project = AudiobookProject(
                    source_path=self._project.source_path,
                    title=self._project.title,
                    author=self._project.author,
                    language=self._project.language,
                    chapters=self._project.chapters,
                    default_voice=self._project.default_voice,
                    speed=self._project.speed,
                    output_format=self._project.output_format,
                    output_dir=self._output_dir,
                    chapter_gap_s=self._project.chapter_gap_s,
                    post_process_params=self._project.post_process_params,
                    separate_files=self._project.separate_files,
                    merged_file=self._project.merged_file,
                    merged_filename=self._project.merged_filename,
                )

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _on_generate(self) -> None:
        if self._running or not self._chapters:
            return

        # Filter only checked (selected) chapters
        selected = self._get_selected_chapters()
        if not selected:
            QMessageBox.warning(
                self, "No chapters selected",
                "No chapters are checked. Tick the checkbox next to the "
                "chapters you want to generate, then try again."
            )
            return

        self._running = True
        self._update_button_states()
        self._generate_btn.setVisible(False)
        self._stop_btn.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_label.setText("Starting…")

        # Reset status (only for visible rows that match selected chapters)
        selected_indices = {
            idx for idx, ch in enumerate(self._chapters)
            if ch in selected
        }
        for row in range(self._table.rowCount()):
            if row in selected_indices:
                self._table.item(row, 4).setText("⏳ Queued")
            else:
                self._table.item(row, 4).setText("⬜ Skipped")

        # Build final project with current settings (only selected chapters)
        project = AudiobookProject(
            source_path=self._project.source_path if self._project else None,
            title=self._project.title if self._project else "Untitled",
            chapters=list(selected),
            default_voice=self._voice_combo.currentText(),
            speed=self._speed_spin.value(),
            output_format=self._format_combo.currentData() or "wav",
            output_dir=self._output_dir,
            chapter_gap_s=self._gap_spin.value(),
            post_process_params=self._post_process_params,
            separate_files=self._separate_cb.isChecked(),
            merged_file=self._merged_cb.isChecked(),
            merged_filename=f"{_safe_filename(self._project.title if self._project else 'audiobook')}_audiobook",
        )

        # Run generation in a background thread
        self._run_generation(project)

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._progress_label.setText("Stopping…")
            self._stop_btn.setEnabled(False)
            self._worker.request_stop()

    def _run_generation(self, project) -> None:
        """Start audiobook generation in a background thread."""
        from kokoro_studio.gui.batch_worker import QThread, QObject, Signal

        class AudiobookGenWorker(QThread):
            progress = Signal(int, int, str)  # current, total, title
            chapter_done = Signal(int, object)  # index, ChapterResult
            finished_ok = Signal(object)  # AudiobookSummary
            failed = Signal(str)

            def __init__(self, proj, rules, blands):
                super().__init__()
                self._proj = proj
                self._rules = rules
                self._blands = blands
                self._stop_requested = False

            def request_stop(self) -> None:
                self._stop_requested = True

            def run(self) -> None:
                try:
                    summary = generate_audiobook(
                        project=self._proj,
                        pronunciation_rules=self._rules,
                        blends=self._blands,
                        on_progress=lambda c, t, l: self.progress.emit(c, t, l),
                        on_chapter_done=lambda i, r: self.chapter_done.emit(i, r),
                        stop_check=lambda: self._stop_requested,
                    )
                    self.finished_ok.emit(summary)
                except Exception as e:
                    self.failed.emit(f"{type(e).__name__}: {e}")

        self._worker = AudiobookGenWorker(
            project, self._pronunciation_rules, self._blends,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.chapter_done.connect(self._on_chapter_done)
        self._worker.finished_ok.connect(self._on_generation_finished)
        self._worker.failed.connect(self._on_generation_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int, title: str) -> None:
        pct = int(current / total * 100) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._progress_label.setText(f"Chapter {current} / {total}: {title}")
        # Map back to the original chapter index in the table (progress callback
        # uses the filtered list, so we need to find the matching row by title)
        for row in range(self._table.rowCount()):
            t_item = self._table.item(row, 2)
            if t_item and t_item.text().strip() == title.strip():
                self._table.item(row, 4).setText("⏳ Generating…")
                self._table.scrollToItem(self._table.item(row, 0))
                break

    def _on_chapter_done(self, index: int, result) -> None:
        """Update table status for a completed chapter.

        The `index` comes from the *filtered* chapter list, so we need to
        find the correct table row by matching the chapter title.
        """
        chapter_title = result.chapter.title if hasattr(result, 'chapter') else ""
        for row in range(self._table.rowCount()):
            t_item = self._table.item(row, 2)
            if t_item and chapter_title and t_item.text().strip() == chapter_title.strip():
                if result.success:
                    dur = format_duration(result.duration_s)
                    self._table.item(row, 4).setText(f"✅ {dur}")
                else:
                    short = result.error_msg[:50]
                    self._table.item(row, 4).setText(f"❌ {short}")
                return
        # Fallback: update by filtered index (may be wrong if chapters unchecked)
        if 0 <= index < self._table.rowCount():
            if result.success:
                dur = format_duration(result.duration_s)
                self._table.item(index, 4).setText(f"✅ {dur}")
            else:
                short = result.error_msg[:50]
                self._table.item(index, 4).setText(f"❌ {short}")

    def _on_generation_finished(self, summary) -> None:
        self._progress_bar.setValue(100)
        parts = []
        if summary.succeeded > 0:
            total_audio = format_duration(summary.total_audio_duration_s)
            elapsed = format_duration(summary.elapsed_s)
            parts.append(f"{summary.succeeded} chapters ({total_audio} in {elapsed})")
        if summary.failed > 0:
            parts.append(f"{summary.failed} failed")
        self._progress_label.setText(
            f"Done  ·  {'  ·  '.join(parts)}" if parts else "Done."
        )

        file_list = ""
        if summary.output_files:
            lines = "\n".join(f"  • {Path(f).name}" for f in summary.output_files[:10])
            if len(summary.output_files) > 10:
                lines += f"\n  … and {len(summary.output_files) - 10} more"
            file_list = f"<br><br><b>Files created:</b><br>{lines}"

        msg = (
            f"<b>Audiobook generation complete</b><br><br>"
            f"Chapters: {summary.succeeded} / {summary.total}<br>"
            f"Failed: {summary.failed}<br>"
            f"Total audio: {format_duration(summary.total_audio_duration_s)}<br>"
            f"Elapsed: {format_duration(summary.elapsed_s)}<br>"
            f"{file_list}"
        )
        QMessageBox.information(self, "Audiobook Complete", msg)

    def _on_generation_failed(self, error_msg: str) -> None:
        self._progress_label.setText("Failed.")
        QMessageBox.critical(self, "Audiobook generation failed", error_msg)

    def _on_worker_finished(self) -> None:
        self._running = False
        self._worker = None
        self._generate_btn.setVisible(True)
        self._stop_btn.setVisible(False)
        self._stop_btn.setEnabled(True)
        self._update_button_states()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_button_states(self) -> None:
        has_chapters = len(self._chapters) > 0
        has_document = self._project is not None
        self._generate_btn.setEnabled(has_chapters and not self._running)
        self._apply_voice_btn.setEnabled(has_chapters and not self._running)
        self._select_all_btn.setEnabled(has_chapters and not self._running)
        self._deselect_all_btn.setEnabled(has_chapters and not self._running)
        self._load_doc_btn.setEnabled(not self._running)
        self._voice_combo.setEnabled(not self._running)
        self._speed_spin.setEnabled(not self._running)
        self._format_combo.setEnabled(not self._running)
        self._output_dir_btn.setEnabled(not self._running)


# ---------------------------------------------------------------------------
# Emotion / Style Sliders dialog (Phase 4)
# ---------------------------------------------------------------------------

class EmotionStyleDialog(QDialog):
    """Dialog for controlling emotional / style parameters.

    Three sliders (Energy, Warmth, Expressiveness) with live preview
    text and a preset dropdown for quick recall.  Emits
    ``style_changed(StyleParameters)`` when the user clicks Apply.
    """

    style_changed = Signal(object)  # StyleParameters

    _PRESET_NAMES = [
        "Neutral", "Warm & Calm", "Bright & Energetic",
        "Soft & Gentle", "Bold & Dynamic", "Cool & Crisp",
        "Deep & Rich", "Lively", "Monotone", "Expressive",
    ]

    def __init__(
        self,
        current_params,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("🎭  Emotion / Style Sliders")
        self.resize(520, 440)
        self.setMinimumWidth(460)
        self.setStyleSheet(_resolve_settings_qss())

        # Import StyleParameters if not already
        from kokoro_studio.emotional_style import (
            StyleParameters, default_style_params, style_presets,
            summarize_style,
        )
        self._StyleParams = StyleParameters
        self._style_presets = style_presets()
        self._summarize = summarize_style

        self._params = current_params or default_style_params()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("🎭  Emotion / Style Sliders")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "Adjust the emotional quality of the generated speech by "
            "modifying the voice style tensor.  Changes are applied "
            "<b>during synthesis</b> (not post-processing).\n\n"
            "<b>Energy</b>  — calm/smooth (left) to lively/dynamic (right).\n"
            "<b>Warmth</b>  — cool/crisp (left) to warm/deep (right).\n"
            "<b>Expressiveness</b> — flat/steady (left) to varied (right).\n"
            "All sliders default to the middle (neutral)."
        )
        intro.setObjectName("SettingsBlock")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        root.addWidget(intro)

        # -- Preset dropdown --
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_row.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(self._PRESET_NAMES)
        self._preset_combo.setToolTip(
            "Select a named preset to set all three sliders at once.\n"
            "Changes are applied immediately."
        )
        preset_row.addWidget(self._preset_combo)
        preset_row.addStretch(1)
        root.addLayout(preset_row)

        # -- Sliders --
        sliders_data = [
            ("Energy",        0.0, 1.0, self._params.energy,
             "⬅️ Calm / Smooth    ·    Energetic / Lively ➡️"),
            ("Warmth",        0.0, 1.0, self._params.warmth,
             "⬅️ Cool / Crisp     ·    Warm / Deep ➡️"),
            ("Expressiveness", 0.0, 1.0, self._params.expressiveness,
             "⬅️ Flat / Steady    ·    Varied / Dynamic ➡️"),
        ]
        self._sliders = {}  # name -> QSlider
        for name, _, _, val, hint in sliders_data:
            box = QVBoxLayout()
            box.setSpacing(2)
            lbl_row = QHBoxLayout()
            lbl = QLabel(name)
            lbl.setObjectName("AddrLabel")
            lbl.setStyleSheet("font-weight: 600; font-size: 12px;")
            lbl_row.addWidget(lbl)
            val_lbl = QLabel(f"{val:.2f}")
            val_lbl.setObjectName("Counter")
            val_lbl.setAlignment(Qt.AlignRight)
            lbl_row.addWidget(val_lbl)
            box.addLayout(lbl_row)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(round(val * 100)))
            slider.setToolTip(hint)
            box.addWidget(slider)
            self._sliders[name] = (slider, val_lbl)

            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet(
                "font-size: 10px; color: #9DA0A8; padding-left: 0px;"
            )
            box.addWidget(hint_lbl)
            root.addLayout(box)

        # -- Summary label --
        self._summary_lbl = QLabel("")
        self._summary_lbl.setObjectName("SettingsBlock")
        self._summary_lbl.setStyleSheet(
            "font-size: 11px; padding: 6px 10px; "
            "background-color: rgba(123,97,255,0.08);"
            " border-radius: 6px;"
        )
        root.addWidget(self._summary_lbl)

        root.addStretch(1)

        # -- Buttons --
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._reset_btn = QPushButton("↩  Reset to neutral")
        self._reset_btn.setProperty("role", "ghost")
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch(1)
        self._apply_btn = QPushButton("✅  Apply")
        self._apply_btn.setProperty("role", "primary")
        btn_row.addWidget(self._apply_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        # -- Wire signals --
        for name, (slider, _) in self._sliders.items():
            slider.valueChanged.connect(lambda v, n=name: self._on_slider_changed(n, v))
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self._reset_btn.clicked.connect(self._on_reset)
        self._apply_btn.clicked.connect(self._on_apply)

        self._update_summary()

    # ------------------------------------------------------------------
    def _slider_val(self, name: str) -> float:
        slider, _ = self._sliders[name]
        return slider.value() / 100.0

    def get_current_params(self):
        return self._StyleParams(
            energy=self._slider_val("Energy"),
            warmth=self._slider_val("Warmth"),
            expressiveness=self._slider_val("Expressiveness"),
        )

    def _on_slider_changed(self, name: str, value: int) -> None:
        _, val_lbl = self._sliders[name]
        val_lbl.setText(f"{value / 100.0:.2f}")
        self._update_summary()

    def _on_preset_selected(self, idx: int) -> None:
        name = self._preset_combo.currentText()
        if name in self._style_presets:
            p = self._style_presets[name]
            for slider_name, (slider, val_lbl) in self._sliders.items():
                key = slider_name.lower()
                val = getattr(p, key, 0.5)
                slider.blockSignals(True)
                slider.setValue(int(round(val * 100)))
                slider.blockSignals(False)
                val_lbl.setText(f"{val:.2f}")
            self._update_summary()

    def _on_reset(self) -> None:
        self._preset_combo.setCurrentIndex(0)  # Neutral
        self._on_preset_selected(0)

    def _update_summary(self) -> None:
        params = self.get_current_params()
        summary = self._summarize(params)
        self._summary_lbl.setText(
            f"<b>Style summary:</b>  {summary}  "
            f"(energy={params.energy:.2f}, warmth={params.warmth:.2f}, "
            f"expressiveness={params.expressiveness:.2f})"
        )

    def _on_apply(self) -> None:
        params = self.get_current_params()
        self._params = params
        self.style_changed.emit(params)


# ---------------------------------------------------------------------------
# Help dialogs
# ---------------------------------------------------------------------------

class _HelpDialog(QDialog):
    """Base class for SSML / Dialogue help dialogs with an insert button."""

    insert_requested = Signal(str)

    def __init__(self, title: str, intro_html: str, sample_text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 480)
        self.setStyleSheet(_resolve_settings_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("SettingsH1")
        root.addWidget(heading)

        intro = QLabel(intro_html)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setObjectName("SettingsBlock")
        intro.setOpenExternalLinks(True)
        root.addWidget(intro)

        sample = QPlainTextEdit()
        sample.setReadOnly(True)
        sample.setStyleSheet(
            "background-color: #1F2329; color: #E8EAED;"
            " border: 1px solid #252932; border-radius: 8px; padding: 10px;"
            " font-family: 'Consolas', 'Cascadia Code', 'JetBrains Mono', monospace;"
            " font-size: 12px;"
        )
        sample.setPlainText(sample_text)
        sample.setMinimumHeight(180)
        root.addWidget(sample, 1)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok)
        close_btn = bbox.button(QDialogButtonBox.Ok)
        close_btn.setText("Got it")
        close_btn.setProperty("role", "primary")
        bbox.accepted.connect(self.accept)

        insert_btn = bbox.addButton("Insert sample script", QDialogButtonBox.ButtonRole.ActionRole)
        insert_btn.clicked.connect(self._insert)
        root.addWidget(bbox)

        self._sample_text = sample_text

    def _insert(self) -> None:
        self.insert_requested.emit(self._sample_text)
        self.accept()


class DialogueHelpDialog(_HelpDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            "🎭  Multi-Speaker Dialogue Mode",
            "Put a <code>[voice_name]:</code> marker at the start of a line to switch "
            "voices mid-script. Lines before the first marker use the currently-selected "
            "voice. Lines without a marker stay on the previous voice.",
            DIALOGUE_HELP_TTS_SAMPLE,
            parent,
        )


class SSMLHelpDialog(_HelpDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            "⚡  SSML-lite Controls",
            "Tag-style controls for inline pauses, emphasis, and rate override. "
            "Type the literal markup into the editor and tick <b>Apply SSML</b>.",
            SSML_HELP_SAMPLE,
            parent,
        )
