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

from kokoro_studio.blending import VoiceBlend
from kokoro_studio.engine import (
    DEFAULT_VOICE, OUTPUT_FORMATS, SAMPLE_RATE, VOICES, generate_speech,
    get_voice_info, list_voices,
)
from kokoro_studio.history import GenerationHistory, HistoryEntry
from kokoro_studio.gui.theme import (
    DIALOGUE_HELP_TTS_SAMPLE, SSML_HELP_SAMPLE, SSML_HELP_TTS_SAMPLE,
    SETTINGS_QSS, default_output_dir, default_output_path, format_bytes,
    format_duration, preview_phrase_for_lang,
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
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kokoro Studio · Settings & Info")
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
            "</a> neural TTS model — 29 built-in voices, multi-format "
            "export (WAV / MP3 / FLAC / OGG), a pronunciation dictionary, "
            "<b>multi-speaker dialogue mode</b>, <b>SSML-lite controls</b>, "
            "and a growing set of audiobook / batch features.<br><br>"
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
            "v1.0</b>.<br><br>"
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
        self.setStyleSheet(SETTINGS_QSS)

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
        self.setStyleSheet(SETTINGS_QSS)

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
        self.setStyleSheet(SETTINGS_QSS)

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
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("📦  Batch Generation Queue")
        self.resize(800, 540)
        self.setStyleSheet(SETTINGS_QSS)

        self._editor_text = editor_text
        self._current_voice = current_voice
        self._current_speed = current_speed
        self._current_format = current_format
        self._pronunciation_rules = pronunciation_rules
        self._blends = blends

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
        dlg.setStyleSheet(SETTINGS_QSS)
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
        self.setStyleSheet(SETTINGS_QSS)

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
        dlg.setStyleSheet(SETTINGS_QSS)
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
# Help dialogs
# ---------------------------------------------------------------------------

class _HelpDialog(QDialog):
    """Base class for SSML / Dialogue help dialogs with an insert button."""

    insert_requested = Signal(str)

    def __init__(self, title: str, intro_html: str, sample_text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 480)
        self.setStyleSheet(SETTINGS_QSS)

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
