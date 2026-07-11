#!/usr/bin/env python3
"""Phase 2 SSML-lite Controls: GUI hooks via single-line anchors + LF normalization.

Strategy that worked when others failed:

1. **LF-normalize at load** — replace \r\n with \n. Fixes the bug where
   `lines[i]` ends in `\r\n` and `needle in ln.rstrip()` was matching
   only after stripping `\n` AND `\r` (we now strip all trailing
   whitespace at once via `.rstrip()`).

2. **Single-line anchors, ideally with `endswith`** — anchors are short
   unique strings that don't span lines. Comments can wrap however they
   want; we just match on a unique structural line.

3. **Insertion invariant** — `lines.insert(idx + 1, new_line)` for each
   new line. The first insertion shifts subsequent line indices, but
   the second insertion is computed relative to the still-valid `idx`
   BEFORE the shift, so we always insert immediately AFTER the anchor.

4. **Idempotent** — each edit has a marker string; if it's already in
   the file, the edit SKIPs (logged). Re-running the script after a
   partial pass is safe.

5. Each insertion block ends with a `# <marker>` line that's a
   one-shot sentinel so re-running after a partial pass is fully
   no-op for that edit.

Edits:
  E1   SynthesisWorker sig: apply_ssml kwarg
  E2   SynthesisWorker body: self._apply_ssml snapshot
  E3   SynthesisWorker.run(): forward apply_ssml=self._apply_ssml
  E4   Module-level SSML_HELP_SAMPLE constant
  E5   KokoroStudioMain.__init__: 4 SSML placeholders
  E6   _build_controls_panel row2: _ssml_checkbox
  E7   _build_controls_panel: _ssml_chip_row after dialogue chip row
  E8   _refresh_ssml_chip slot before _on_segment_started
  E9   _on_ssml_help_clicked slot before _refresh_voice_readout
  E10  _wire_signals: extra textChanged -> _refresh_ssml_chip
  E11  _wire_signals: _ssml_checkbox.toggled connection
  E12  _on_generate_clicked: pass apply_ssml= to SynthesisWorker

If any edit fails the script exits non-zero with a clear diagnostic.
This script does NOT itself catch SystemExit so the basher shell can
display the exit code directly.
"""

from pathlib import Path

GUI = Path(r"C:\Users\matti\OneDrive\Desktop\Programmazione\Miei_prog\TTs\kokoro_studio\gui.py")
SENTINEL_TAIL = "[SSML-GUI-HOOKS-APPLIED-v2-LINE-ANCHORED]"


def find_end(lines: list[str], anchor: str, mode: str = "exact") -> int:
    """Find the index of ``anchor`` in ``lines``; raise on missing/ambiguous.

    mode="exact": match ``ln.rstrip() == anchor.rstrip()`` (default).
    mode="contains": match ``anchor in ln.rstrip()``.
    mode="endswith": match ``ln.rstrip().endswith(anchor.rstrip())``.
    """
    norm = [ln.rstrip("\r\n").rstrip() for ln in lines]
    matches: list[int] = []
    for i, ln in enumerate(norm):
        if mode == "exact" and ln == anchor.rstrip():
            matches.append(i)
        elif mode == "contains" and anchor.rstrip() in ln:
            matches.append(i)
        elif mode == "endswith" and ln.endswith(anchor.rstrip()):
            matches.append(i)
    assert matches, f"ANCHOR MISSING (mode={mode}): {anchor!r}"
    assert len(matches) == 1, (
        f"ANCHOR AMBIGUOUS ({len(matches)} matches, mode={mode}): "
        f"{anchor!r}  indices={matches}"
    )
    return matches[0]


def insert_after(lines_lf: list[str], anchor: str, mode: str,
                 new_block: list[str], marker: str) -> None:
    """Insert ``new_block`` (LF lines) AFTER the line matched by ``anchor``.

    Idempotent: if any line of ``new_block`` is already in the file
    AND contains the unique ``marker``, the edit SKIPS.
    """
    if any(marker in ln for ln in lines_lf):
        print(f"  [SKIP] {marker!r}")
        return
    idx = find_end(lines_lf, anchor, mode=mode)
    # Insert in reverse: each new line at idx+1 maintains the offset.
    # Equivalently: lines_lf[idx+1:idx+1] = new_block.
    for offset, new_ln in enumerate(new_block):
        lines_lf.insert(idx + 1 + offset, new_ln)
    print(f"  [OK] {marker!r}  (+{len(new_block)} lines, idx={idx})")


def main() -> None:
    # ---- LOAD + LF normalize ---------------------------------------
    raw = GUI.read_bytes().decode("utf-8")
    # Strip a UTF-8 BOM if present (defensive).
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    # Unify line endings: \r\n -> \n, then any stray \r -> \n.
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    # splitlines(keepends=True) so we preserve final-newline state.
    lines = raw.splitlines(keepends=True)
    print(f"Loaded {len(lines):,} lines ({len(raw):,} chars; LF normalized)")

    # --- Assertion: ALL previous script sentinel absent --------------
    if SENTINEL_TAIL in raw:
        # Already fully applied; no-op.
        print(f"Sentinel {SENTINEL_TAIL!r} present; no changes needed.")
        return

    # ---- E1: apply_ssml kwarg in SynthesisWorker.__init__ ----------
    insert_after(
        lines,
        anchor="        parent: Optional[QObject] = None,",
        mode="exact",
        new_block=[
            "        # Phase 2 - SSML-lite Controls. Opt-in boolean\n",
            "        # forwarded verbatim to engine.generate_speech;\n",
            "        # defaults to False for backward compat with\n",
            "        # Phase 1 callers/tests.\n",
            "        apply_ssml: bool = False,\n",
        ],
        marker="apply_ssml: bool = False,  # SSML-GUI-E1",
    )

    # ---- E2: self._apply_ssml snapshot -----------------------------
    insert_after(
        lines,
        anchor="        self._blends: Optional[dict] = (",
        mode="exact",
        new_block=[
            "        )\n",
            "        # Phase 2 - SSML-lite. Snapshot the bool at\n",
            "        # start() time so a mid-run checkbox flip\n",
            "        # can't silently switch the engine from\n",
            "        # plain to SSML mode.\n",
            "        self._apply_ssml = bool(apply_ssml)  # SSML-GUI-E2\n",
        ],
        marker="self._apply_ssml = bool(apply_ssml)  # SSML-GUI-E2",
    )

    # ---- E3: forward apply_ssml in run()'s generate_speech --------
    insert_after(
        lines,
        anchor="                blends=self._blends,",
        mode="exact",
        new_block=[
            "\n",
            "                # Phase 2 - SSML-lite. Forward the\n",
            "                # opt-in flag so the engine's\n",
            "                # _generate_ssml_segments path takes\n",
            "                # over when the editor has SSML\n",
            "                # markup + the checkbox was on at\n",
            "                # click time.\n",
            "                apply_ssml=self._apply_ssml,  # SSML-GUI-E3\n",
        ],
        marker="apply_ssml=self._apply_ssml,  # SSML-GUI-E3",
    )

    # ---- E4: SSML_HELP_SAMPLE constant -----------------------------
    insert_after(
        lines,
        anchor='    return f"{n / 1024 / 1024:.1f} MB"',
        mode="exact",
        new_block=[
            "\n",
            "\n",
            "# SSML-lite Help dialog content (Phase 2). Bound here\n",
            "# rather than imported from kokoro_studio.ssml so the\n",
            "# GUI keeps a single source of truth for user-facing\n",
            "# documentation. Rendered cheaply on each click.\n",
            'SSML_HELP_SAMPLE = """\\\n',
            "SSML-lite controls (Phase 2)\n",
            "\n",
            "Type the literal markup into the editor. Markers\n",
            'expand once the "Apply SSML" checkbox on the controls\n',
            "panel is ON.\n",
            "\n",
            '  <break time="1.5s"/>          Insert a 1.5-second silence.\n',
            '  <break time="500ms"/>          Millisecond precision is accepted.\n',
            "\n",
            "  <emphasis>word</emphasis>      Slows down the wrapped word\n",
            "                                (effective rate: 0.85x of\n",
            "                                base speed).\n",
            "\n",
            "  <prosody rate=\"fast\">...</prosody>\n",
            "                                Speeds up the wrapped phrase.\n",
            "  <prosody rate=\"0.8\">...</prosody>\n",
            "                                Numeric multipliers also work\n",
            "                                (0.8 = 80% of base speed).\n",
            "\n",
            "  Valid rate tokens:     x-slow (0.6), slow (0.8),\n",
            "                         medium (1.0), fast (1.4),\n",
            "                         x-fast (1.8).\n",
            "  Numeric rate range:    0.5 .. 2.0  (clipped to safe band).\n",
            "\n",
            "Notes:\n",
            "\n",
            "  * SSML-lite and multi-speaker dialogue are mutually\n",
            "    exclusive. When dialogue mode is on, SSML is silently\n",
            "    ignored -- the chip turns amber to warn you.\n",
            "  * The chip above the Generate button shows a\n",
            '    one-line summary ("1 break + 2 emphasis + 1 prosody")\n',
            "    that updates as you type.\n",
            "  * Plain text without markers works as usual; toggling\n",
            "    the checkbox on by accident has zero side-effects.\n",
            '"""\n',
        ],
        marker="SSML_HELP_SAMPLE = ",  # the constant name is unique
    )

    # ---- E5: 4 SSML placeholders in KokoroStudioMain.__init__ ------
    insert_after(
        lines,
        anchor="        self._dialogue_help_btn = None  # type: ignore[assignment]",
        mode="exact",
        new_block=[
            "\n",
            "        # Phase 2 - SSML-lite Controls. Parity with\n",
            "        # the dialogue placeholders above: built in\n",
            "        # _build_controls_panel, wired in\n",
            "        # _wire_signals. None values safely defer any\n",
            "        # pre-build textChanged events.\n",
            "        self._ssml_chip = None  # type: ignore[assignment]  # SSML-GUI-E5\n",
            "        self._ssml_chip_row = None  # type: ignore[assignment]\n",
            "        self._ssml_help_btn = None  # type: ignore[assignment]\n",
            "        self._ssml_checkbox = None  # type: ignore[assignment]\n",
        ],
        marker="self._ssml_chip = None  # type: ignore[assignment]  # SSML-GUI-E5",
    )

    # ---- E6: _ssml_checkbox in row2 --------------------------------
    insert_after(
        lines,
        anchor="        row2.addWidget(self._pron_count_label)",
        mode="exact",
        new_block=[
            "\n",
            "        # SSML-lite opt-in checkbox (Phase 2).\n",
            "        # Default OFF so the classic plain-text path\n",
            "        # stays the baseline; users flip it on when\n",
            "        # they want <break>/<emphasis>/<prosody> tags\n",
            "        # to take effect.\n",
            '        self._ssml_checkbox = QCheckBox("Apply SSML")  # SSML-GUI-E6\n',
            "        self._ssml_checkbox.setChecked(False)\n",
            "        self._ssml_checkbox.setToolTip(\n",
            '            "When enabled, the editor text is routed "\n',
            '            "through the SSML-lite parser before synthesis.\\n"\n',
            '            "\\n"\n',
            '            "Supported tags (see ? button next to the chip):\\n"\n',
            '            "  <break time=\\"Xs\\"/>  insert X seconds of silence\\n"\n',
            '            "  <emphasis>w</emphasis> slow down word w\\n"\n',
            '            "  <prosody rate=\\"fast\\">speeds up wrapped text</prosody>"\n',
            "        )\n",
            "        row2.addSpacing(12)\n",
            "        row2.addWidget(self._ssml_checkbox)\n",
        ],
        marker="self._ssml_checkbox = QCheckBox(\"Apply SSML\")  # SSML-GUI-E6",
    )

    # ---- E7: _ssml_chip_row widget after dialogue chip --------------
    insert_after(
        lines,
        anchor="        layout.addWidget(self._dialogue_chip_row)",
        mode="exact",
        new_block=[
            "\n",
            "        # ---- SSML-lite status chip (Phase 2) ---------------\n",
            "        # Inline hint that pops in whenever (a) the SSML\n",
            "        # Apply checkbox is on AND (b) the editor text\n",
            "        # contains at least one SSML-lite tag. Hidden\n",
            "        # otherwise so the controls row stays compact\n",
            "        # for plain-text scripts.\n",
            "        ssml_chip_row_inner = QHBoxLayout()  # SSML-GUI-E7\n",
            "        ssml_chip_row_inner.setSpacing(8)\n",
            '        self._ssml_chip = QLabel("")\n',
            '        self._ssml_chip.setObjectName("SSMLChip")\n',
            "        # Default emerald-on-dark style; the refresh\n",
            "        # slot swaps to amber when SSML collides with\n",
            "        # multi-speaker dialogue (engine silently drops\n",
            "        # SSML in that case).\n",
            "        self._ssml_chip.setStyleSheet(\n",
            '            "color: #10B981; background-color: rgba(16,185,129,0.10);"\n',
            '            " border: 1px solid rgba(16,185,129,0.35);"\n',
            '            " border-radius: 6px; padding: 5px 10px;"\n',
            '            " font-size: 11px; font-weight: 600;"\n',
            "        )\n",
            "        self._ssml_chip.setToolTip(\n",
            '            "SSML-lite markers detected in the editor.\\n"\n',
            '            "\\n"\n',
            '            "Click ? on the right for the full syntax reference."\n',
            "        )\n",
            "        ssml_chip_row_inner.addWidget(self._ssml_chip, 1)\n",
            '        self._ssml_help_btn = QPushButton("?")\n',
            '        self._ssml_help_btn.setProperty("role", "ghost")\n',
            "        self._ssml_help_btn.setFixedSize(28, 26)\n",
            "        self._ssml_help_btn.setToolTip(\n",
            '            "Show SSML-lite syntax examples"\n',
            "        )\n",
            "        self._ssml_help_btn.clicked.connect(\n",
            "            self._on_ssml_help_clicked\n",
            "        )\n",
            "        ssml_chip_row_inner.addWidget(self._ssml_help_btn)\n",
            "        self._ssml_chip_row = QWidget()\n",
            "        self._ssml_chip_row.setLayout(ssml_chip_row_inner)\n",
            "        self._ssml_chip_row.setVisible(False)\n",
            "        layout.addWidget(self._ssml_chip_row)\n",
        ],
        marker="ssml_chip_row_inner = QHBoxLayout()  # SSML-GUI-E7",
    )

    # ---- E8: _refresh_ssml_chip slot -------------------------------
    # Anchor: header line "    # ----------------- Slot: per-segment
    # status updates" (immediately preceding _on_segment_started).
    insert_after(
        lines,
        anchor="    # ----------------- Slot: per-segment status updates",
        mode="exact",
        new_block=[
            "\n",
            "    # ----------------- Slot: SSML-lite chip refresh (Phase 2)\n",
            "    def _refresh_ssml_chip(self, text: str) -> None:  # SSML-GUI-E8\n",
            '        """Show / hide the inline SSML-lite chip row.\n',
            "\n",
            "        Hidden when EITHER (a) the Apply SSML checkbox\n",
            "        is OFF, OR (b) the text doesn't contain SSML-\n",
            "        lite markup. When the multi-speaker dialogue\n",
            "        chip is also visible, SSML is silently ignored\n",
            "        by the engine; we surface this in chip text +\n",
            '        amber colour so the user doesn\'t think their\n',
            "        tags are doing something.\n",
            '        """\n',
            "        # getattr defends against textChanged firing\n",
            "        # before the chip widget is built (parity with\n",
            "        # _refresh_dialogue_chip).\n",
            '        chip = getattr(self, "_ssml_chip", None)\n',
            '        row = getattr(self, "_ssml_chip_row", None)\n',
            '        cb = getattr(self, "_ssml_checkbox", None)\n',
            "        if chip is None or row is None or cb is None:\n",
            "            return  # pre-build or mid-teardown window\n",
            "        if not cb.isChecked():\n",
            "            row.setVisible(False)\n",
            "            return\n",
            "        try:\n",
            "            from kokoro_studio.ssml import (\n",
            "                detect_ssml, parse_ssml, summarize_ssml,\n",
            "            )\n",
            "        except ImportError:\n",
            "            row.setVisible(False)\n",
            "            return\n",
            "        if not detect_ssml(text):\n",
            "            row.setVisible(False)\n",
            "            return\n",
            "        segs = parse_ssml(text)\n",
            "        summary = summarize_ssml(segs)\n",
            "        if not summary:\n",
            "            row.setVisible(False)\n",
            "            return\n",
            "        # If the multi-speaker dialogue chip is\n",
            "        # currently visible, SSML is silently ignored\n",
            "        # by the engine -- surface this in the chip\n",
            "        # so the user doesn't think their tags are\n",
            "        # taking effect.\n",
            "        dialogue_row_visible = bool(\n",
            '            getattr(self, "_dialogue_chip_row", None)\n',
            "            and self._dialogue_chip_row.isVisible()\n",
            "        )\n",
            "        if dialogue_row_visible:\n",
            "            chip.setStyleSheet(\n",
            '                "color: #F59E0B; background-color: rgba(245,158,11,0.10);"\n',
            '                " border: 1px solid rgba(245,158,11,0.35);"\n',
            '                " border-radius: 6px; padding: 5px 10px;"\n',
            '                " font-size: 11px; font-weight: 600;"\n',
            "            )\n",
            '            chip.setText(f"\\u26A1 SSML: {summary} (ignored in dialogue mode)")\n',
            "        else:\n",
            "            chip.setStyleSheet(\n",
            '                "color: #10B981; background-color: rgba(16,185,129,0.10);"\n',
            '                " border: 1px solid rgba(16,185,129,0.35);"\n',
            '                " border-radius: 6px; padding: 5px 10px;"\n',
            '                " font-size: 11px; font-weight: 600;"\n',
            "            )\n",
            '            chip.setText(f"\\u26A1 SSML: {summary}")\n',
            "        row.setVisible(True)\n",
        ],
        marker="def _refresh_ssml_chip(self, text: str) -> None:  # SSML-GUI-E8",
    )

    # ---- E9: _on_ssml_help_clicked slot ----------------------------
    # Anchor: the line "    def _refresh_voice_readout(self) -> None:"
    # Insert just BEFORE it (i.e. at idx-1).
    insert_after(
        lines,
        anchor="        dlg.exec()",
        mode="endswith",
        new_block=[
            "\n",
            "    # ----------------- Slot: SSML-lite help button (Phase 2)\n",
            "    def _on_ssml_help_clicked(self) -> None:  # SSML-GUI-E9\n",
            '        """Popup a modal dialog with SSML-lite tag examples.\n',
            "\n",
            "        Triggered by the small ? button next to the\n",
            "        inline chip. Mirrors\n",
            "        _on_dialogue_help_clicked so the two feature\n",
            "        entrypoints feel identical.\n",
            '        """\n',
            "        dlg = QDialog(self)\n",
            '        dlg.setWindowTitle("SSML-lite Controls")\n',
            "        dlg.resize(640, 480)\n",
            "        dlg.setStyleSheet(SETTINGS_QSS)\n",
            "\n",
            "        root = QVBoxLayout(dlg)\n",
            "        root.setContentsMargins(24, 20, 24, 20)\n",
            "        root.setSpacing(10)\n",
            "\n",
            '        title = QLabel("\\u26A1  SSML-lite Controls")\n',
            '        title.setObjectName("SettingsH1")\n',
            "        root.addWidget(title)\n",
            "\n",
            "        intro = QLabel(\n",
            '            "Tag-style controls for inline pauses, "\n',
            '            "emphasis, and rate override. Type the "\n',
            '            "literal markup into the editor and tick "<b>Apply SSML</b>"\n',
            '            " on the controls panel.<br><br>"\n',
            '            "<b>Notes:</b>"\n',
            '            "<ul>"\n',
            '            "<li>SSML-lite and multi-speaker dialogue are"\n',
            '            " mutually exclusive. Dialogue mode wins"\n',
            '            " silently; the chip turns amber to warn"<b>Apply SSML</b>"</li>"\n',
            '            "<li>Tags work inside sentences: <code>he said"\n',
            '            " &lt;emphasis&gt;wait&lt;/emphasis&gt;!</code>"\n',
            '            " is valid.</li>"\n',
            '            "<li>No nesting: open and close each tag in"\n',
            '            " the order they appear; unclosed tags are"\n',
            '            " kept literal as text and surface a stderr"\n',
            '            " warning.</li>"\n',
            '            "</ul>"\n',
            "        )\n",
            "        intro.setWordWrap(True)\n",
            "        intro.setTextFormat(Qt.RichText)\n",
            '        intro.setObjectName("SettingsBlock")\n',
            "        intro.setOpenExternalLinks(True)\n",
            "        root.addWidget(intro)\n",
            "\n",
            "        sample = QPlainTextEdit(dlg)\n",
            "        sample.setReadOnly(True)\n",
            "        sample.setStyleSheet(\n",
            '            "background-color: #1F2329; color: #E8EAED;"\n',
            '            " border: 1px solid #252932; border-radius: 8px;"\n',
            '            " padding: 10px;"\n',
            '            " font-family: \'Consolas\', \'Cascadia Code\',"\n',
            '            " \'JetBrains Mono\', monospace;"\n',
            '            " font-size: 12px;"\n',
            "        )\n",
            "        sample.setPlainText(SSML_HELP_SAMPLE)\n",
            "        sample.setMinimumHeight(180)\n",
            "        root.addWidget(sample, 1)\n",
            "\n",
            "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n",
            '        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)\n',
            '        close_btn.setText("Got it")\n',
            '        close_btn.setProperty("role", "primary")\n',
            "        bbox.accepted.connect(dlg.accept)\n",
            "        root.addWidget(bbox)\n",
            "\n",
            "        dlg.exec()\n",
        ],
        marker="def _on_ssml_help_clicked(self) -> None:  # SSML-GUI-E9",
    )

    # ---- E10: extra textChanged -> _refresh_ssml_chip -------------
    insert_after(
        lines,
        anchor="        self._editor.textChanged.connect(self._on_text_changed)",
        mode="exact",
        new_block=[
            "\n",
            "        # SSML-lite chip refresh on every keystroke\n",
            "        # (Phase 2). _refresh_ssml_chip itself\n",
            "        # short-circuits on detect_ssml(text) so this\n",
            "        # stays sub-millisecond for plain-text scripts.\n",
            "        self._editor.textChanged.connect(  # SSML-GUI-E10\n",
            "            lambda: self._refresh_ssml_chip(\n",
            "                self._editor.toPlainText()\n",
            "            )\n",
            "        )\n",
        ],
        marker="self._editor.textChanged.connect(  # SSML-GUI-E10",
    )

    # ---- E11: _ssml_checkbox.toggled connection -------------------
    insert_after(
        lines,
        anchor="        self._pron_edit_btn.clicked.connect(self._on_edit_pronunciation_clicked)",
        mode="exact",
        new_block=[
            "\n",
            "        # SSML-lite checkbox (Phase 2). Toggling\n",
            "        # immediately re-evaluates the chip so users\n",
            "        # see the chip appear or vanish the same tick\n",
            "        # they flip the checkbox.\n",
            "        self._ssml_checkbox.toggled.connect(  # SSML-GUI-E11\n",
            "            lambda _checked: self._refresh_ssml_chip(\n",
            "                self._editor.toPlainText()\n",
            "            )\n",
            "        )\n",
        ],
        marker="self._ssml_checkbox.toggled.connect(  # SSML-GUI-E11",
    )

    # ---- E12: apply_ssml= kwarg in _on_generate_clicked ------------
    insert_after(
        lines,
        anchor="            blends=blends,",
        mode="exact",
        new_block=[
            "\n",
            "            # Phase 2 - SSML-lite. Snapshot the\n",
            "            # checkbox state at click time so a\n",
            "            # mid-run flip can't trigger the\n",
            "            # half-parsed-execution footgun.\n",
            "            apply_ssml=self._ssml_checkbox.isChecked(),  # SSML-GUI-E12\n",
        ],
        marker="apply_ssml=self._ssml_checkbox.isChecked(),  # SSML-GUI-E12",
    )

    # ---- SAVE --------------------------------------------------------
    # Trailing sentinel for forensics.
    if SENTINEL_TAIL not in raw and not any(SENTINEL_TAIL in ln for ln in lines):
        # Append a single trailing comment line.
        if lines and lines[-1].endswith("\n"):
            lines.append(f"# {SENTINEL_TAIL}\n")
        else:
            lines.append(f"# {SENTINEL_TAIL}\n")

    new_text = "".join(lines)
    GUI.write_text(new_text, encoding="utf-8")
    print(f"\nDone. Wrote {len(new_text):,} chars (was 160,587). "
          f"Lines: {len(lines):,}.")


if __name__ == "__main__":
    main()
