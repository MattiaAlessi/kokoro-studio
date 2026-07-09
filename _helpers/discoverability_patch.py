"""Apply 4 safer GUI patches (skipping the placeholder text which had
unicode escaping complications). Each change uses an ASCII anchor
whenever possible to avoid Python escape-sequence confusion.
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

# ---------- Patch 1: Always-visible Dialogue button (insert before stream checkbox) ----------
# Anchor: line containing '\u25b6 Stream'. Python evaluates that escape to '▶'
# at parse time, so the file's literal text contains the unicode ▶ char.
P1_OLD = '        self._stream_checkbox = QCheckBox("\u25b6 Stream")\n'
# Prepend a discoverability comment + a new QPushButton instance that
# is ALWAYS visible (not behind an auto-hide chip). Connects to the
# existing _on_dialogue_help_clicked slot which already pops the
# modal help dialog.
P1_NEW_PREPEND = (
    '        # ---- Multi-speaker Dialogue Mode (Discoverability) ----\n'
    '        # Always-visible help button in the action row. Brings the\n'
    '        # multi-speaker syntax from "hidden behind an autofocus chip"\n'
    '        # to "obvious from the moment you open the app". Clicking\n'
    '        # this pops the modal help dialog which now contains a\n'
    '        # one-click "Insert sample script" button so the user can\n'
    '        # try the feature in <5 seconds without typing markers.\n'
    '        self._dialogue_btn = QPushButton("\U0001F3AD  Dialogue")\n'
    '        self._dialogue_btn.setProperty("role", "ghost")\n'
    '        self._dialogue_btn.setToolTip(\n'
    '            "Multi-Speaker Dialogue Mode.\\n\\n"\n'
    '            "Type a [voice_name]: marker at the start of a line to\\n"\n'
    '            "switch voices mid-script mid-way through your script.\\n"\n'
    '            "Click here for the full syntax cheatsheet + one-click"\n'
    '            " sample-script insertion."\n'
    '        )\n'
    '        self._dialogue_btn.clicked.connect(self._on_dialogue_help_clicked)\n'
    '        row2.addSpacing(8)\n'
    '        row2.addWidget(self._dialogue_btn)\n'
    '\n'
)
if not verify("P1 stream-checkbox", P1_OLD, text):
    sys.exit(1)
text = text.replace(P1_OLD, P1_NEW_PREPEND + P1_OLD, 1)
print("1/4 dialogue button added")

# ---------- Patch 2: Help dialog Insert-sample button ----------
# Anchor: lines from `sample.setPlainText(DIALOGUE_HELP_SAMPLE)` through
# the closing `dlg.exec()`. We re-use ASCII-stable anchors; DIALOGUE_HELP_SAMPLE
# is ASCII so no escape ambiguity.
P2_OLD = (
    '        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n'
    '        sample.setMinimumHeight(180)\n'
    '        root.addWidget(sample, 1)\n'
    '\n'
    '        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n'
    '        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)\n'
    '        close_btn.setText("Got it")\n'
    '        close_btn.setProperty("role", "primary")\n'
    '        bbox.accepted.connect(dlg.accept)\n'
    '        root.addWidget(bbox)\n'
    '\n'
    '        dlg.exec()\n'
)
# Insert an "Insert sample script" button BEFORE the OK button so it's
# the primary action. Clicking drops the multi-speaker demo into the
# editor AND closes the dialog so user can hit Generate right after.
P2_NEW = (
    '        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n'
    '        sample.setMinimumHeight(180)\n'
    '        root.addWidget(sample, 1)\n'
    '\n'
    '        # Insert-sample button: one-click path from "what is this\n'
    '        # feature" to "oh I get it" -- drops the multi-speaker\n'
    '        # demo into the editor and closes the dialog so the user\n'
    '        # can hit Generate right away.\n'
    '        action_row = QHBoxLayout()\n'
    '        insert_btn = QPushButton("\U0001F4C4  Insert sample script")\n'
    '        insert_btn.setProperty("role", "primary")\n'
    '        def _insert_and_close() -> None:\n'
    '            self._editor.setPlainText(DIALOGUE_HELP_SAMPLE)\n'
    '            dlg.accept()\n'
    '        insert_btn.clicked.connect(_insert_and_close)\n'
    '        action_row.addWidget(insert_btn)\n'
    '        action_row.addStretch(1)\n'
    '        root.addLayout(action_row)\n'
    '\n'
    '        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n'
    '        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)\n'
    '        close_btn.setText("Got it")\n'
    '        close_btn.setProperty("role", "ghost")\n'
    '        bbox.accepted.connect(dlg.accept)\n'
    '        root.addWidget(bbox)\n'
    '\n'
    '        dlg.exec()\n'
)
if not verify("P2 help-dialog bbox", P2_OLD, text):
    sys.exit(1)
text = text.replace(P2_OLD, P2_NEW, 1)
print("2/4 help-dialog Insert-sample added")

# ---------- Patch 3: DIALOGUE_HELP_SAMPLE constant ----------
# Insert AFTER the SETTINGS_QSS triple-quoted string. Anchor: trailing
# `"""` line of SETTINGS_QSS. The very next non-blank line is the class
# decl `class SettingsDialog(QDialog):` which we'll preserve verbatim.
SAMPLE_BLOCK = (
    '\n\n# Multi-speaker script example shown in the dialogue help dialog.\n'
    '# Loaded verbatim into the editor when the user clicks "Insert\n'
    '# sample script" in the help dialog, AND shown read-only above\n'
    '# the insert button so the syntax is obvious without clicking.\n'
    'DIALOGUE_HELP_SAMPLE = (\n'
    '    "[af_heart]: Hello there! Welcome to Kokoro Studio.\\n"\n'
    '    "It is a pleasure to meet you.\\n"\n'
    '    "[am_adam]: Hi! I am Adam. Let me show you the multi-speaker mode.\\n"\n'
    '    "[af_heart]: Great! Notice how my voice changes when you see a marker like\\n"\n'
    '    "            [am_adam]: or  [af_bella]: at the start of a line.\\n"\n'
    '    "[am_adam]: Continuation lines without a marker keep the previous voice.\\n"\n'
    '    "So a single tag can cover an entire multi-line speaker turn.\\n"\n'
    '    "Click Generate and you will hear two voices alternating naturally.\\n"\n'
    ')\n'
)
if "DIALOGUE_HELP_SAMPLE = (" in text:
    print("3/4 DIALOGUE_HELP_SAMPLE already defined (skip)")
else:
    # Anchor: 'class SettingsDialog(QDialog):' is unique and ASCII.
    ANCH = 'class SettingsDialog(QDialog):\n'
    if not verify("P3 SettingsDialog", ANCH, text):
        sys.exit(1)
    # Insert SAMPLE_BLOCK BEFORE the class line, with a blank line separator.
    text = text.replace(ANCH, SAMPLE_BLOCK + '\n' + ANCH, 1)
    print("3/4 DIALOGUE_HELP_SAMPLE defined")

# ---------- Patch 4: About tab description ----------
# Anchor: the 'A free, offline, private desktop GUI for the ' line. Note
# the file has the em-dash as a 1-char unicode (Python evaluates '\u2014'
# at parse), so we use the same Python escape in our pattern.
P4_OLD = (
    "A free, offline, private desktop GUI for the "
    "<a href='https://huggingface.co/hexgrad/Kokoro-82M'>Kokoro-82M"
    "</a> neural TTS model \u2014 29 built-in voices, multi-format "
    "export (WAV / MP3 / FLAC / OGG), a pronunciation dictionary, "
    "and a growing set of audiobook / batch features.<br><br>"
)
P4_NEW = (
    "A free, offline, private desktop GUI for the "
    "<a href='https://huggingface.co/hexgrad/Kokoro-82M'>Kokoro-82M"
    "</a> neural TTS model \u2014 29 built-in voices, multi-format "
    "export (WAV / MP3 / FLAC / OGG), a pronunciation dictionary, "
    "<b>multi-speaker dialogue mode</b>, and a growing set of "
    "audiobook / batch features.<br><br>"
)
if not verify("P4 about-tab desc", P4_OLD, text):
    sys.exit(1)
text = text.replace(P4_OLD, P4_NEW, 1)
print("4/4 about-tab description updated")

write(text)
print(f"\nAll 4 patches applied. Wrote: {GUI}")
