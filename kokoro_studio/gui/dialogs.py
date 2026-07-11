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
    QPushButton, QSlider, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
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
