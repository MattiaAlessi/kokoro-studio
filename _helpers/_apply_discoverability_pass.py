#!/usr/bin/env python3
"""Apply the full discoverability pass to kokoro_studio/gui.py.

Idempotent: each edit has a unique marker; if the marker is already
present, the edit skips. Run from the project root:

    python _helpers/_apply_discoverability_pass.py

Edits (revised to be safe against CRLF-vs-LF and Unicode-escape edge cases):
  E1  Insert a compact discoverability banner widget above the
      `_editor` in `_build_editor_panel`. Replaces the previous plan of
      overwriting `setPlaceholderText(...)` whose multi-line literal
      was tripping on the `\\\n` line-continuation sequence in the
      file. A persistent visible banner is also better discoverability
      than a placeholder hint that disappears on first keystroke.
  E2  action row: always-visible "🎭 Dialogue" button + a 28x26 "?"
      button next to the Apply SSML checkbox.
  E3  SSML_HELP_TTS_SAMPLE constant (short runnable TTS sample).
  E4  _on_dialogue_help_clicked: "Insert sample script" button
      that drops DIALOGUE_HELP_SAMPLE into the editor.
  E5  _on_ssml_help_clicked: "Insert sample + enable SSML" button
      that drops the NEW SSML_HELP_TTS_SAMPLE (not the prose doc)
      into the editor and ticks Apply SSML.
  E6  About tab: add "SSML-lite controls" mention.
"""
from pathlib import Path

GUI = Path(r"C:\Users\matti\OneDrive\Desktop\Programmazione\Miei_prog\TTs\kokoro_studio\gui.py")

EM_DASH = "\u2014"
LDQ = "\u201c"
RDQ = "\u201d"
HELLIP = "\u2026"


def main() -> None:
    raw = GUI.read_bytes().decode("utf-8")
    EOL_CRLF = "\r\n" in raw and raw.count("\r\n") >= 3000
    text = raw.replace("\r\n", "\n")
    print(
        f"Loaded {len(raw):,} chars "
        f"({'CRLF' if EOL_CRLF else 'LF'}) line endings."
    )

    # ----------------- E1 discoverability banner widget -----------------
    # Anchor: the line `layout.addWidget(self._editor, 1)` inside
    # `_build_editor_panel`. We PREPEND a compact banner widget so
    # the user sees the discoverability text at first paint even
    # after they've typed content into the editor (which is when
    # QPlainTextEdit's placeholder disappears).
    E1_OLD = "        layout.addWidget(self._editor, 1)\n"
    E1_NEW = (
        "\n"
        "        # Discoverability banner (Phase 2 power features).\n"
        "        # Persistent: stays visible after the editor gains\n"
        "        # content (unlike QPlainTextEdit's placeholderText\n"
        "        # which disappears on first keystroke). Compact, dark-\n"
        "        # panel styled so it doesn't compete with the editor.\n"
        "        self._discoverability_banner = QLabel(\n"
        f"            \"{EM_DASH} {LDQ}\U0001F3AD Multi-Speaker Dialogue{RDQ}: start a line with <code>[voice_name]:</code> to switch voices.\\n\"\n"
        f"            \"{EM_DASH} {LDQ}\u26A1 SSML-lite Controls{RDQ}: use <code>&lt;break&gt;</code>, <code>&lt;emphasis&gt;</code>, <code>&lt;prosody&gt;</code> with {LDQ}Apply SSML{RDQ} on the right.\"\n"
        "        )\n"
        "        self._discoverability_banner.setObjectName(\"SettingsBlock\")\n"
        "        # Slightly muted VS the editor text so the editor\n"
        "        itself stays the focal point for typing.\n"
        "        self._discoverability_banner.setStyleSheet(\n"
        "            \"background-color: rgba(123,97,255,0.06);\"\n"
        "            \"color: #9DA0A8;\"\n"
        "            \"padding: 8px 12px;\"\n"
        "            \"border: 1px solid rgba(123,97,255,0.20);\"\n"
        "            \"border-radius: 8px;\"\n"
        "            \"font-size: 11px;\"\n"
        "        )\n"
        "        self._discoverability_banner.setTextFormat(Qt.RichText)\n"
        "        self._discoverability_banner.setWordWrap(True)\n"
        # Banner goes ABOVE the editor so first paint surfaces it.
        "        layout.addWidget(self._discoverability_banner)\n"
        "        layout.addWidget(self._editor, 1)\n"
    )
    E1_MARK = "Discoverability banner (Phase 2 power features)."
    if E1_MARK in text:
        print("  [SKIP] E1 banner already added")
    elif E1_OLD not in text:
        raise SystemExit("E1 anchor not found; editor insert line drifted")
    else:
        # Replace ONLY the FIRST occurrence (inside _build_editor_panel),
        # not the similar-looking line at end of file.
        idx = text.index(E1_OLD)
        # Confirm it's in _build_editor_panel by looking backwards
        # for the `_editor = DocumentDropEditor()` marker.
        if "_editor = DocumentDropEditor" not in text[:idx]:
            raise SystemExit(
                "E1 anchor matched but not inside _build_editor_panel"
            )
        text = text.replace(E1_OLD, E1_NEW, 1)
        print("  [OK]   E1 discoverability banner added")

    # ----------------- E2 action row buttons -----------------
    E2_OLD = (
        "        row2.addSpacing(12)\n"
        "        row2.addWidget(self._ssml_checkbox)\n"
    )
    E2_NEW = (
        "        # Discoverability: always-visible \"Dialogue\" ghost\n"
        "        # button. Click opens the same syntax modal as the\n"
        "        # tiny \"?\" next to the chip; positioned in the\n"
        # prominent action row so users see Phase 2's headline\n"
        "        # feature on first paint.\n"
        "        row2.addSpacing(12)\n"
        "        self._dialogue_help_action_btn = QPushButton(\"\\U0001F3AD  Dialogue\")\n"
        "        self._dialogue_help_action_btn.setProperty(\"role\", \"ghost\")\n"
        "        self._dialogue_help_action_btn.setToolTip(\n"
        "            \"Multi-Speaker Dialogue Mode.\\n\"\n"
        "            \"\\n\"\n"
        "            \"Switch voices mid-script by typing a [voice_name]: \"\n"
        "            \"marker at the start of a line:\\n\"\n"
        "            \"  [af_heart]: Hello!\\n\"\n"
        "            \"  [am_adam]:  Hi there.\\n\"\n"
        "            \"\\n\"\n"
        "            \"Click for the full syntax cheatsheet + \"\n"
        "            \"one-click sample-script insertion.\"\n"
        "        )\n"
        "        self._dialogue_help_action_btn.clicked.connect(\n"
        "            self._on_dialogue_help_clicked\n"
        "        )\n"
        "        row2.addWidget(self._dialogue_help_action_btn)\n"
        "        row2.addSpacing(12)\n"
        "        row2.addWidget(self._ssml_checkbox)\n"
        # Tiny "?" help button next to Apply SSML mirrors the
        # dialogue chip's "?". Default-OFF checkbox + visible help
        # button + tooltip = a first-time user can find the syntax
        # in one click.
        "        self._ssml_help_action_btn = QPushButton(\"?\")\n"
        "        self._ssml_help_action_btn.setProperty(\"role\", \"ghost\")\n"
        "        self._ssml_help_action_btn.setFixedSize(28, 26)\n"
        "        self._ssml_help_action_btn.setToolTip(\n"
        "            \"Show SSML-lite syntax examples\"\n"
        "        )\n"
        "        self._ssml_help_action_btn.clicked.connect(\n"
        "            self._on_ssml_help_clicked\n"
        "        )\n"
        "        row2.addWidget(self._ssml_help_action_btn)\n"
    )
    E2_MARK = "Always-visible \\\"Dialogue\\\" ghost"  # noqa: RUF001
    if E2_MARK in text:
        print("  [SKIP] E2 action-row buttons already added")
    elif E2_OLD not in text:
        raise SystemExit("E2 anchor not found; row2 may have drifted")
    else:
        text = text.replace(E2_OLD, E2_NEW, 1)
        print("  [OK]   E2 action-row buttons added")

    # ----------------- E3 SSML_HELP_TTS_SAMPLE constant -----------------
    # Anchor: the closing `"""\n` of SSML_HELP_SAMPLE (it's a
    # triple-quoted string ending with `"""\\\n`). Insert a new
    # SSML_HELP_TTS_SAMPLE block immediately AFTER the SSML doc block.
    E3_ANCHOR_START = 'SSML_HELP_SAMPLE = """\\\n'
    E3_MARK = "SSML_HELP_TTS_SAMPLE = ("
    if E3_MARK in text:
        print("  [SKIP] E3 SSML_HELP_TTS_SAMPLE already defined")
    elif E3_ANCHOR_START not in text:
        raise SystemExit("E3 anchor (SSML_HELP_SAMPLE def) not found")
    else:
        ssml_start = text.index(E3_ANCHOR_START)
        # Find closing `"""\n` from there.
        tail = '"""\\\n'
        end_idx = text.find(tail, ssml_start)
        if end_idx < 0:
            raise SystemExit(
                "E3: SSML_HELP_SAMPLE closing triple-quote not found"
            )
        insert_at = end_idx + len(tail)
        E3_BLOCK = (
            "\n"
            "# Short, runnable SSML-lite sample used as the payload of\n"
            "# the help dialog's \"Insert sample + enable SSML\" button.\n"
            "# Distinct from SSML_HELP_SAMPLE (the prose doc shown\n"
            "# read-only in the dialog) so Generate synthesises demo\n"
            "# content rather than reading the cheat-sheet aloud.\n"
            "# Demonstrates <break>, <emphasis>, and <prosody> in\n"
            "# one short 4-line script.\n"
            "SSML_HELP_TTS_SAMPLE = (\n"
            "    \"Welcome <break time=\\\"300ms\\\"/> to the SSML-lite demo.\\n\"\n"
            "    \"Notice how this <emphasis>word</emphasis> is spoken a bit slower.\\n\"\n"
            "    \"<prosody rate=\\\"fast\\\">And this whole sentence is sped up.</prosody>\\n\"\n"
            "    \"Finally <break time=\\\"1s\\\"/> a one-second silence, then normal pace.\\n\"\n"
            ")\n"
        )
        text = text[:insert_at] + E3_BLOCK + text[insert_at:]
        print("  [OK]   E3 SSML_HELP_TTS_SAMPLE defined")

    # ----------------- E4 dialogue help dialog: Insert button -----------------
    E4_OLD = (
        "        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    )
    E4_NEW = (
        "        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        # One-click discoverability: dump the dialogue demo into
        # the editor and close the dialog so the user can hit
        # Generate immediately. Ctrl+Z undoes the text insert.
        "        action_row = QHBoxLayout()\n"
        "        insert_btn = QPushButton(\"\\U0001F4C4  Insert sample script\")\n"
        "        insert_btn.setProperty(\"role\", \"primary\")\n"
        "        insert_btn.setToolTip(\n"
        "            \"Load the sample script above into the editor so \"\n"
        "            \"you can hit Generate right away. Ctrl+Z undoes it.\"\n"
        "        )\n"
        "\n"
        "        def _insert_and_close() -> None:\n"
        "            self._editor.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
        "            dlg.accept()\n"
        "\n"
        "        insert_btn.clicked.connect(_insert_and_close)\n"
        "        action_row.addWidget(insert_btn)\n"
        "        action_row.addStretch(1)\n"
        "        root.addLayout(action_row)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    )
    E4_MARK = 'insert_btn = QPushButton("\\U0001F4C4  Insert sample script")'
    if E4_MARK in text:
        print("  [SKIP] E4 dialogue dialog already has Insert button")
    elif E4_OLD not in text:
        raise SystemExit("E4 anchor not found in _on_dialogue_help_clicked")
    else:
        text = text.replace(E4_OLD, E4_NEW, 1)
        print("  [OK]   E4 dialogue dialog Insert button added")

    # ----------------- E5 SSML help dialog: Insert button -----------------
    E5_OLD = (
        "        sample.setPlainText(SSML_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    )
    E5_NEW = (
        "        sample.setPlainText(SSML_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        # Companion to the dialogue Insert button. Uses the SHORT
        # TTS_SAMPLE \u2014 NOT the prose doc \u2014 so Generate actually
        # reads demo SSML aloud. Also ticks the Apply SSML checkbox
        # so the inserted tags are parsed instead of read as text.
        "        ssml_action_row = QHBoxLayout()\n"
        "        ssml_insert_btn = QPushButton(\n"
        "            \"\\U0001F4C4  Insert sample + enable SSML\"\n"
        "        )\n"
        "        ssml_insert_btn.setProperty(\"role\", \"primary\")\n"
        "        ssml_insert_btn.setToolTip(\n"
        "            \"Load a short SSML demo into the editor and tick \"\n"
        "            \"\\\"Apply SSML\\\" so the next Generate run uses it. \"\n"
        "            \"Ctrl+Z undoes the text insert.\"\n"
        "        )\n"
        "\n"
        "        def _insert_and_enable_ssml() -> None:\n"
        "            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n"
        "            if self._ssml_checkbox is not None:\n"
        "                self._ssml_checkbox.setChecked(True)\n"
        "            dlg.accept()\n"
        "\n"
        "        ssml_insert_btn.clicked.connect(_insert_and_enable_ssml)\n"
        "        ssml_action_row.addWidget(ssml_insert_btn)\n"
        "        ssml_action_row.addStretch(1)\n"
        "        root.addLayout(ssml_action_row)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    )
    E5_MARK = "self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)"
    if E5_MARK in text:
        print("  [SKIP] E5 SSML dialog already has Insert button")
    elif E5_OLD not in text:
        raise SystemExit("E5 anchor not found in _on_ssml_help_clicked")
    else:
        text = text.replace(E5_OLD, E5_NEW, 1)
        print("  [OK]   E5 SSML dialog Insert button added")

    # ----------------- E6 About tab: add SSML mention -----------------
    E6_OLD = (
        '" export (WAV / MP3 / FLAC / OGG), a pronunciation dictionary, "\n'
        '"<b>multi-speaker dialogue mode</b>, and a growing set of '
        'audiobook / batch features.<br><br>"\n'
    )
    E6_NEW = (
        '" export (WAV / MP3 / FLAC / OGG), a pronunciation dictionary, "\n'
        '"<b>multi-speaker dialogue mode</b>, <b>SSML-lite controls</b>, "\n'
        '"and a growing set of audiobook / batch features.<br><br>"\n'
    )
    E6_MARK = "<b>SSML-lite controls</b>"
    if E6_MARK in text:
        print("  [SKIP] E6 About-tab already mentions SSML-lite")
    elif E6_OLD not in text:
        raise SystemExit("E6 anchor not found; About tab description drifted")
    else:
        text = text.replace(E6_OLD, E6_NEW, 1)
        print("  [OK]   E6 About-tab updated to mention SSML-lite")

    # ----------------- Save -----------------
    if EOL_CRLF:
        text = text.replace("\n", "\r\n")
    GUI.write_text(text, encoding="utf-8", newline="")
    print(
        f"\nWrote {len(text):,} chars ({'CRLF' if EOL_CRLF else 'LF'}). "
        "Run `python -m compileall kokoro_studio/gui.py` to verify."
    )


if __name__ == "__main__":
    main()
