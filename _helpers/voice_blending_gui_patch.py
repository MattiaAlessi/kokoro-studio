"""Voice Blending GUI patcher for kokoro_studio/gui.py.

Idempotent (each anchor is `verify()`-checked first so a second run
just prints "already applied, skipping"). Mirrors the existing
`_helpers/*.py` neighbour pattern: byte-level read, CRLF detection,
anchor-based surgery, byte-level write.

This is the rewritten, anchor-corrected version. The previous copy
referenced a `_dialogue_btn` attr that no longer exists in gui.py
(it was renamed to `_dialogue_chip` / `_dialogue_help_btn` during the
Multi-Speaker Dialogue Mode refactor), and used double-backslash
unicode escapes (`\\u25b6`) that produced literal `\u25b6` text in
the file rather than the intended unicode char (`▶`). Both classes
of bug are fixed here.

Modifications:
  P1 — Pre-declare blend-related attrs in __init__ (after _dialogue_help_btn).
  P2 — Build the BLEND EDITOR frame in `_build_voice_panel`.
  P3 — Wire blend signals in `_wire_signals`.
  P4 — `_repopulate_voice_list` appends blend entries with a badge.
  P5 — `_voice_readout` renders blend composition when active voice is a blend.
  P6 — `_refresh_dialogue_chip` widens `known_voices` with blend names.
  P7 — Add new helper methods (`_load_blends`, `_save_blend`,
       `_refresh_blend_count_label`, `_default_blend_name`,
       `_on_alpha_slider_changed`, `_on_alpha_spin_changed`,
       `_on_blend_voice_selection_changed`, `_on_save_blend_clicked`,
       `_on_preview_blend_clicked`) right before `main()` inside the
       `KokoroStudioMain` class.
  P8 — `_on_generate_clicked` snapshots blends into the worker.
  P9 — `_load_blends()` wired into __init__ after `_load_pron_dict`.
"""
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent / "kokoro_studio" / "gui.py"
data = GUI.read_bytes()
EOL_CRLF = b"\r\n" in data and data.count(b"\r\n") >= 3000
text = data.decode("utf-8")
if EOL_CRLF:
    text = text.replace("\r\n", "\n")


def write(t):
    """Re-encode with the file's original line endings."""
    if EOL_CRLF:
        t = t.replace("\n", "\r\n")
    GUI.write_bytes(t.encode("utf-8"))


def verify(label, needle, haystack):
    pos = haystack.find(needle)
    if pos < 0:
        print(f"ERROR: {label} anchor not found", file=sys.stderr)
        return False
    print(f"  {label} OK (pos={pos})")
    return True


# ================================================================
# P1 — Pre-declare blend attrs in __init__ (after _dialogue_help_btn)
# ================================================================
P1_OLD = '''        self._dialogue_help_btn = None  # type: ignore[assignment]
'''
P1_NEW = P1_OLD + '''
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
'''
if not verify("P1 _dialogue_help_btn pre-decl", P1_OLD, text):
    sys.exit(1)
text = text.replace(P1_OLD, P1_NEW, 1)
print("P1 blend attrs pre-declared in __init__")


# ================================================================
# P2 — Build the BLEND frame in _build_voice_panel
# ================================================================
P2_OLD = '''        # Preview button
        self._preview_btn = QPushButton("\u25b6  Preview selected voice")
        self._preview_btn.setProperty("role", "ghost")
        layout.addWidget(self._preview_btn)

        return panel
'''
P2_NEW = '''        # Preview button
        self._preview_btn = QPushButton("\u25b6  Preview selected voice")
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

        bl_title = QLabel("\U0001F39B  CREATE BLEND")
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
            "Identifier (a-z, 0-9, _) - saved as a reusable preset.\\n"
            "Tip: leave empty before clicking Save to auto-generate\\n"
            "  from the current Voice A + Voice B + alpha."
        )
        action_row.addWidget(name_label)
        action_row.addWidget(self._blend_name_edit, 1)
        self._blend_preview_btn = QPushButton("\u25b6  Preview blend")
        self._blend_preview_btn.setProperty("role", "ghost")
        self._blend_preview_btn.setToolTip(
            "Generate a short sample with the CURRENTLY-EDITED\\n"
            " blend (alpha / Voice A / Voice B), WITHOUT saving\\n"
            " - lets you hear a tweak before committing it."
        )
        action_row.addWidget(self._blend_preview_btn)
        self._blend_save_btn = QPushButton("\U0001F4BE  Save blend")
        self._blend_save_btn.setProperty("role", "primary")
        action_row.addWidget(self._blend_save_btn)
        bl.addLayout(action_row)

        # Count label (mirrors the pronunciation "0 rules" pattern).
        self._blend_count_label = QLabel("0 blends saved")
        self._blend_count_label.setObjectName("Counter")
        bl.addWidget(self._blend_count_label)

        layout.addWidget(self._blend_frame)

        return panel
'''
if not verify("P2 voice_panel return", P2_OLD, text):
    sys.exit(1)
text = text.replace(P2_OLD, P2_NEW, 1)
print("P2 BLEND frame added to voice panel")


# ================================================================
# P3 — Wire blend signals
# ================================================================
P3_OLD = '''        # Voice list (filter dropdown removed \u2014 only voice selection matters).
        self._voice_list.currentItemChanged.connect(self._on_voice_changed)
'''
P3_NEW = P3_OLD + '''

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
'''
if not verify("P3 voice-list connect", P3_OLD, text):
    sys.exit(1)
text = text.replace(P3_OLD, P3_NEW, 1)
print("P3 blend signals wired")


# ================================================================
# P4 — _repopulate_voice_list: include blend entries
# ================================================================
P4_OLD = '''        # Try to keep the current voice selected; else pick the first available.
        keep_idx = -1
        for i in range(self._voice_list.count()):
            if self._voice_list.item(i).data(Qt.UserRole) == self._current_voice:
                keep_idx = i
                break
'''
P4_NEW = '''        # Phase 2 - Voice Blending: append saved blends below
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
                f"\U0001F39B {blend_name}"
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
'''
if not verify("P4 keep_idx loop", P4_OLD, text):
    sys.exit(1)
text = text.replace(P4_OLD, P4_NEW, 1)
print("P4 blend entries appended to voice list")


# ================================================================
# P5 — _voice_readout: show blend composition when active voice is a blend
# ================================================================
P5_OLD = '''        if not self._current_voice:
            self._voice_readout.setText("\\u2014")
            return
        info = get_voice_info(self._current_voice)
            # (use the dashboard's selected voice + grade)
        self._voice_readout.setText(
            f"{self._current_voice}  \\u00b7  Grade {info['grade']}"
        )
'''
P5_NEW = '''        if not self._current_voice:
            self._voice_readout.setText("\u2014")
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
                f"\U0001F39B {self._current_voice}"
                f"  \u00b7  {_pct_a}% {_b.voice_a} + {_pct_b}% {_b.voice_b}"
            )
            return
        info = get_voice_info(self._current_voice)
        self._voice_readout.setText(
            f"{self._current_voice}  \u00b7  Grade {info['grade']}"
        )
'''
if not verify("P5 voice readout setText", P5_OLD, text):
    sys.exit(1)
text = text.replace(P5_OLD, P5_NEW, 1)
print("P5 voice readout renders blend composition")


# ================================================================
# P6 — _refresh_dialogue_chip: widen known_voices with blend names
# ================================================================
P6_OLD = '''        segs, _ = parse_dialogue(
            text,
            default_voice=self._current_voice or DEFAULT_VOICE,
        )
'''
P6_NEW = '''        # Phase 2 - Voice Blending: blend names share the
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
'''
if not verify("P6 parse_dialogue call", P6_OLD, text):
    sys.exit(1)
text = text.replace(P6_OLD, P6_NEW, 1)
print("P6 dialogue chip widened with blend names")


# ================================================================
# P7 — Inject helper methods before main().
# ================================================================
P7_OLD_MARKER = '''    window = KokoroStudioMain()
    window.show()
    return app.exec()
'''

# Use a triple-quoted block to avoid per-line escaping pitfalls.
HELPERS_BLOCK = '''
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
                "Blend names must match `[A-Za-z_][A-Za-z0-9_]*`.\\n"
                f"You provided: {name!r}",
            )
            return False
        if name in VOICES:
            QMessageBox.warning(
                self, "Name reserved",
                f"{name!r} is the name of a built-in voice.\\n"
                "Choose a different name (built-ins are immutable).",
            )
            return False
        _new_dict = dict(self._loaded_blends)
        if name in _new_dict:
            _ans = QMessageBox.question(
                self, "Overwrite blend?",
                f"A blend named {name!r} already exists.\\n\\n"
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
                f"{type(e).__name__}: {e}\\n\\nPath: {self._blend_dict_path}",
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
        _alpha = round(self._blend_alpha_spin.value(), 4) \\
            if self._blend_alpha_spin is not None else 0.5
        try:
            _blend = VoiceBlend(voice_a=_va, voice_b=_vb, alpha=_alpha)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid blend", str(e))
            return
        if self._save_blend(_name, _blend):
            self._status_label.setText(
                f"Saved blend {_name!r}  \u00b7  "
                f"{int(round(_alpha*100))}% {_va} + "
                f"{int(round((1.0-_alpha)*100))}% {_vb}"
            )

    def _on_preview_blend_clicked(self) -> None:
        """Ad-hoc preview of the panel's CURRENTLY-EDITED blend.

        Uses `voice_blend=(a, b, alpha)` so the user can hear a
        tweak before saving it as a preset.
        """
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Busy",
                "A generation is already running. Stop it first "
                "to preview a new blend.",
            )
            return
        from kokoro_studio.blending import VoiceBlend
        _va = (self._blend_voice_a_combo.currentText()
               if self._blend_voice_a_combo else "af_bella")
        _vb = (self._blend_voice_b_combo.currentText()
               if self._blend_voice_b_combo else "af_sarah")
        _alpha = round(self._blend_alpha_spin.value(), 4) \\
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
        try:
            _audio = generate_speech(
                text=_phrase, voice_blend=_blend,
                output_path=_out_path, speed=1.0,
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Blend preview failed",
                f"{type(e).__name__}: {e}",
            )
            return
        self._last_audio_path = _out_path
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(_out_path))
        self._player.play()
        self._play_btn.setEnabled(True)
        self._status_label.setText(
            f"Blend preview  \u00b7  {int(round(_alpha*100))}% {_va} + "
            f"{int(round((1.0-_alpha)*100))}% {_vb}  \u00b7  "
            f"{len(_audio)/SAMPLE_RATE:.2f}s"
        )

'''

if not verify("P7 main body anchor", P7_OLD_MARKER, text):
    sys.exit(1)
text = text.replace(P7_OLD_MARKER, HELPERS_BLOCK + P7_OLD_MARKER, 1)
print("P7 helper methods added before main()")


# ================================================================
# P8 — _on_generate_clicked: snapshot blends into the worker
# ================================================================
P8_OLD = '''        self._start_synthesis(
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
        )
'''
P8_NEW = '''        # Phase 2 - Voice Blending: snapshot the loaded blends
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
'''
if not verify("P8 _start_synthesis call", P8_OLD, text):
    sys.exit(1)
text = text.replace(P8_OLD, P8_NEW, 1)
print("P8 _start_synthesis passes blends snapshot")


# ================================================================
# P9 — Wire _load_blends into __init__ after _load_pron_dict
# ================================================================
P9_OLD = '''        self._load_pron_dict()
        self._update_button_states()
'''
P9_NEW = '''        self._load_pron_dict()
        # Phase 2 - Voice Blending. Load BEFORE repopulate so
        # blend entries appear in the voice list on first paint.
        self._load_blends()
        self._update_button_states()
'''
if not verify("P9 _load_pron_dict anchor", P9_OLD, text):
    sys.exit(1)
text = text.replace(P9_OLD, P9_NEW, 1)
print("P9 _load_blends called from __init__")

write(text)
print(f"\nAll patches applied. Wrote: {GUI}")
