#!/usr/bin/env python3
"""Apply discoverability pass to gui.py - one-shot inline-via-basher."""
from pathlib import Path
import sys

GUI = Path(r"C:\Users\matti\OneDrive\Desktop\Programmazione\Miei_prog\TTs\kokoro_studio\gui.py")


def load():
    raw = GUI.read_bytes().decode("utf-8")
    eol = "\r\n" in raw and raw.count("\r\n") >= 3000
    return raw.replace("\r\n", "\n"), eol


def save(text, eol):
    out = text.replace("\n", "\r\n") if eol else text
    GUI.write_text(out, encoding="utf-8", newline="")


def patch(name, text, marker, old, new):
    if marker in text:
        print(f"  [SKIP] {name}")
        return text, True
    if old not in text:
        print(f"  [FAIL] {name}")
        idx = text.find(marker.split(" (")[0]) if "(" in marker else -1
        return text, False
    text = text.replace(old, new, 1)
    print(f"  [OK]   {name}")
    return text, True


text, eol = load()
print(f"Loaded ({'CRLF' if eol else 'LF'})")

# E1: discoverability banner above editor
E1_MARK = "Discoverability banner (Phase 2 power features)."
E1_NEW_PRE = (
    "        # Discoverability banner (Phase 2 power features).\n"
    "        # Persistent label above the editor so first-time users\n"
    "        # see the headline features even after typing (QPlainTextEdit's\n"
    "        # placeholderText disappears on first keystroke).\n"
    "        self._discoverability_banner = QLabel(\n"
    '            "\u2014 \U0001F3AD Multi-Speaker Dialogue: start a line with <code>[voice_name]:</code> to switch voices.<br>"\n'
    '            "\u2014 \u26A1 SSML-lite Controls: use <code>&lt;break&gt;</code>, <code>&lt;emphasis&gt;</code>, <code>&lt;prosody&gt;</code> with <b>Apply SSML</b> on the right."\n'
    "        )\n"
    '        self._discoverability_banner.setObjectName("SettingsBlock")\n'
    "        self._discoverability_banner.setStyleSheet(\n"
    '            "background-color: rgba(123,97,255,0.06);"\n'
    '            "color: #9DA0A8;"\n'
    '            "padding: 8px 12px;"\n'
    '            "border: 1px solid rgba(123,97,255,0.20);"\n'
    '            "border-radius: 8px;"\n'
    '            "font-size: 11px;"\n'
    "        )\n"
    "        self._discoverability_banner.setTextFormat(Qt.RichText)\n"
    "        self._discoverability_banner.setWordWrap(True)\n"
    "        self._discoverability_banner.setToolTip(\n"
    '            "Type these SSML tags verbatim into the editor below and tick'\n'
    " \"Apply SSML\\\" to use them. Multi-Speaker Dialogue uses [voice_name]:\"\n"
    '            " markers at the start of a line."\n'
    "        )\n"
)
text, ok = patch(
    "E1 banner",
    text,
    E1_MARK,
    "        layout.addWidget(self._editor, 1)\n",
    E1_NEW_PRE + "        layout.addWidget(self._editor, 1)\n",
)
if not ok: sys.exit(1)
save(text, eol); text, eol = load()

# E2a: pre-declare banner attr in __init__
E2A_MARK = "self._discoverability_banner = None  # parity init"
text, ok = patch(
    "E2a banner pre-decl",
    text,
    E2A_MARK,
    "        self._ssml_checkbox = None  # type: ignore[assignment]\n",
    "        self._ssml_checkbox = None  # type: ignore[assignment]\n"
    "\n"
    "        # Discoverability banner: built in _build_editor_panel,\n"
    "        # auto-hidden by _maybe_hide_banner after substantial\n"
    "        # editor content is typed.\n"
    "        self._discoverability_banner = None  # parity init\n",
)
if not ok: sys.exit(1)
save(text, eol); text, eol = load()

# E2b: wire _maybe_hide_banner in _wire_signals
E2B_MARK = "and len(self._editor.toPlainText()) > 30"
text, ok = patch(
    "E2b banner auto-hide",
    text,
    E2B_MARK,
    (
        "        self._ssml_checkbox.toggled.connect(  # SSML-GUI-E11\n"
        "            lambda _checked: self._refresh_ssml_chip(\n"
        "                self._editor.toPlainText()\n"
        "            )\n"
        "        )\n"
    ),
    (
        "        self._ssml_checkbox.toggled.connect(  # SSML-GUI-E11\n"
        "            lambda _checked: self._refresh_ssml_chip(\n"
        "                self._editor.toPlainText()\n"
        "            )\n"
        "        )\n"
        "\n"
        "        # Discoverability banner auto-hide: once the user has\n"
        "        # typed substantial text, the hint above the editor\n"
        "        # has served its purpose. Cheap O(1) check.\n"
        "        def _maybe_hide_banner() -> None:\n"
        '            disc_banner = getattr(self, "_discoverability_banner", None)\n'
        "            if (\n"
        "                disc_banner is not None\n"
        "                and disc_banner.isVisible()\n"
        "                and len(self._editor.toPlainText()) > 30\n"
        "            ):\n"
        "                disc_banner.hide()\n"
        "\n"
        "        self._editor.textChanged.connect(_maybe_hide_banner)\n"
    ),
)
if not ok: sys.exit(1)
save(text, eol); text, eol = load()

# E3: action row buttons
E3_MARK = 'self._dialogue_help_action_btn = QPushButton('
text, ok = patch(
    "E3 action row",
    text,
    E3_MARK,
    (
        "        row2.addSpacing(12)\n"
        "        row2.addWidget(self._ssml_checkbox)\n"
    ),
    (
        "        # Discoverability: always-visible Dialogue button +\n"
        "        # tiny SSML help '?' in the prominent action row.\n"
        "        row2.addSpacing(12)\n"
        '        self._dialogue_help_action_btn = QPushButton("\\U0001F3AD  Dialogue")\n'
        '        self._dialogue_help_action_btn.setProperty("role", "ghost")\n'
        "        self._dialogue_help_action_btn.setToolTip(\n"
        '            "Multi-Speaker Dialogue Mode.\\n"\n'
        '            "\\n"\n'
        "            \"Switch voices mid-script by typing a [voice_name]:\""
        ' " marker at the start of a line:\\n"\n'
        '            "  [af_heart]: Hello!\\n"\n'
        '            "  [am_adam]:  Hi there.\\n"\n'
        '            "\\n"\n'
        "            \"Click for the full syntax cheatsheet +\""
        ' " one-click sample-script insertion."\n'
        "        )\n"
        "        self._dialogue_help_action_btn.clicked.connect(\n"
        "            self._on_dialogue_help_clicked\n"
        "        )\n"
        "        row2.addWidget(self._dialogue_help_action_btn)\n"
        "        row2.addSpacing(12)\n"
        "        row2.addWidget(self._ssml_checkbox)\n"
        '        self._ssml_help_action_btn = QPushButton("?")\n'
        '        self._ssml_help_action_btn.setProperty("role", "ghost")\n'
        "        self._ssml_help_action_btn.setFixedSize(28, 26)\n"
        "        self._ssml_help_action_btn.setToolTip(\n"
        '            "Show SSML-lite syntax examples"\n'
        "        )\n"
        "        self._ssml_help_action_btn.clicked.connect(\n"
        "            self._on_ssml_help_clicked\n"
        "        )\n"
        "        row2.addWidget(self._ssml_help_action_btn)\n"
    ),
)
if not ok: sys.exit(1)
save(text, eol); text, eol = load()

# E4: SSML_HELP_TTS_SAMPLE constant
E4_MARK = "SSML_HELP_TTS_SAMPLE = ("
if E4_MARK in text:
    print("  [SKIP] E4 SSML_HELP_TTS_SAMPLE")
else:
    e4_open = 'SSML_HELP_SAMPLE = """\\\n'
    if e4_open not in text:
        print("  [FAIL] E4 SSML_HELP_SAMPLE def missing"); sys.exit(1)
    start = text.index(e4_open)
    tail = '"""\\\n'
    end = text.find(tail, start)
    if end < 0:
        print("  [FAIL] E4 closing triple-quote missing"); sys.exit(1)
    insert_at = end + len(tail)
    e4_block = (
        "\n"
        "# Short, runnable SSML-lite sample used as the payload of\n"
        "# the help dialog's 'Insert sample + enable SSML' button.\n"
        "# Distinct from SSML_HELP_SAMPLE (the prose documentation)\n"
        "# so Generate synthesises demo content rather than reading\n"
        "# the cheat-sheet aloud. Demonstrates <break>, <emphasis>,\n"
        "# and <prosody> in one short 4-line script.\n"
        "SSML_HELP_TTS_SAMPLE = (\n"
        '    "Welcome <break time=\\"300ms\\"/> to the SSML-lite demo.\\n"\n'
        '    "Notice how this <emphasis>word</emphasis> is spoken a bit slower.\\n"\n'
        '    "<prosody rate=\\"fast\\">And this whole sentence is sped up.</prosody>\\n"\n'
        '    "Finally <break time=\\"1s\\"/> a one-second silence, then normal pace.\\n"\n'
        ")\n"
    )
    text = text[:insert_at] + e4_block + text[insert_at:]
    print("  [OK]   E4 SSML_HELP_TTS_SAMPLE defined")
save(text, eol); text, eol = load()

# E5: dialogue dialog Insert button
E5_MARK = "_dialogue_insert_and_close"
text, ok = patch(
    "E5 dialogue Insert",
    text,
    E5_MARK,
    (
        "        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    ),
    (
        "        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        "        dialogue_action_row = QHBoxLayout()\n"
        '        insert_btn = QPushButton("\\U0001F4C4  Insert sample script")\n'
        '        insert_btn.setProperty("role", "primary")\n'
        "        insert_btn.setToolTip(\n"
        '            "Load the sample script above into the editor so"\n'
        ' " you can hit Generate right away. Ctrl+Z undoes it."\n'
        "        )\n"
        "\n"
        "        def _dialogue_insert_and_close() -> None:\n"
        "            self._editor.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
        "            dlg.accept()\n"
        "\n"
        "        insert_btn.clicked.connect(_dialogue_insert_and_close)\n"
        "        dialogue_action_row.addWidget(insert_btn)\n"
        "        dialogue_action_row.addStretch(1)\n"
        "        root.addLayout(dialogue_action_row)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    ),
)
if not ok: sys.exit(1)
save(text, eol); text, eol = load()

# E6: SSML dialog Insert button (uses TTS sample, ticks Apply SSML)
E6_MARK = "_ssml_insert_and_enable"
text, ok = patch(
    "E6 SSML Insert",
    text,
    E6_MARK,
    (
        "        sample.setPlainText(SSML_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    ),
    (
        "        sample.setPlainText(SSML_HELP_SAMPLE)\n"
        "        sample.setMinimumHeight(180)\n"
        "        root.addWidget(sample, 1)\n"
        "\n"
        "        ssml_action_row = QHBoxLayout()\n"
        '        ssml_insert_btn = QPushButton("\\U0001F4C4  Insert sample + enable SSML")\n'
        '        ssml_insert_btn.setProperty("role", "primary")\n'
        "        ssml_insert_btn.setToolTip(\n"
        '            "Load a short SSML demo into the editor and tick"\n'
        ' " \\"Apply SSML\\" so the next Generate run uses it. Ctrl+Z"\n'
        ' " undoes the text insert."\n'
        "        )\n"
        "\n"
        "        def _ssml_insert_and_enable() -> None:\n"
        "            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n"
        "            if self._ssml_checkbox is not None:\n"
        "                self._ssml_checkbox.setChecked(True)\n"
        "            dlg.accept()\n"
        "\n"
        "        ssml_insert_btn.clicked.connect(_ssml_insert_and_enable)\n"
        "        ssml_action_row.addWidget(ssml_insert_btn)\n"
        "        ssml_action_row.addStretch(1)\n"
        "        root.addLayout(ssml_action_row)\n"
        "\n"
        "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    ),
)
if not ok: sys.exit(1)
save(text, eol); text, eol = load()

# E7: About tab SSML mention
E7_MARK = "<b>SSML-lite controls</b>"
text, ok = patch(
    "E7 About tab",
    text,
    E7_MARK,
    "<b>multi-speaker dialogue mode</b>, and a growing set of audiobook / batch features.<br><br>",
    "<b>multi-speaker dialogue mode</b>, <b>SSML-lite controls</b>, and a growing set of audiobook / batch features.<br><br>",
)
if not ok: sys.exit(1)
save(text, eol)

print("\nAll edits applied.")
