#!/usr/bin/env python3
"""Single-file atomic applier for the discoverability patch.
Reads the previous patcher file if present, otherwise writes a fresh
incrementally-committing patch inline via heredoc. Kept intentionally
short: no string-literal concatenation tricks, no complex escapes.
"""
from pathlib import Path
import sys

GUI = Path('kokoro_studio/gui.py')

raw = GUI.read_bytes().decode('utf-8')
EOL_CRLF = '\r\n' in raw and raw.count('\r\n') >= 3000
text = raw.replace('\r\n', '\n')
print(f'Loaded {len(raw):,} chars ({'CRLF' if EOL_CRLF else 'LF'})')

def save():
    out = text.replace('\n', '\r\n') if EOL_CRLF else text
    GUI.write_text(out, encoding='utf-8', newline='')
    print(f'  [save] {len(out):,} chars')

def patch(name, marker, old, new):
    global text
    if marker in text:
        print(f'  [SKIP] {name}')
        return
    if old not in text:
        print(f'  [FAIL] {name}: anchor not found')
        sys.exit(1)
    text = text.replace(old, new, 1)
    print(f'  [OK]   {name}')
    save()

# E1: discoverability banner above the editor.
# Anchor: the `_editor = DocumentDropEditor()` line in `_build_editor_panel`.
e1_old = '        self._editor = DocumentDropEditor()'
EM = '\u2014'
LDQ = '\u201c'
RDQ = '\u201d'
HELLIP = '\u2026'
e1_new = (
    '        # Discoverability banner (Phase 2 power features).\n'
    '        # Persistent label above the editor so first-time users see\n'
    '        # the headline features even after typing (QPlainTextEdit\'s\n'
    '        # placeholderText disappears on first keystroke).\n'
    '        self._discoverability_banner = QLabel(\n'
    '            \"' + EM + ' \U0001F3AD Multi-Speaker Dialogue: start a line with <code>[voice_name]:</code> to switch voices.<br>\"\n'
    '            \"' + EM + ' \u26A1 SSML-lite Controls: use <code>&lt;break&gt;</code>, <code>&lt;emphasis&gt;</code>, <code>&lt;prosody&gt;</code> with <b>Apply SSML</b> on the right.\"\n'
    '        )\n'
    "        self._discoverability_banner.setObjectName('SettingsBlock')\n"
    '        self._discoverability_banner.setStyleSheet(\n'
    '            "background-color: rgba(123,97,255,0.06);"\n'
    '            "color: #9DA0A8;"\n'
    '            "padding: 8px 12px;"\n'
    '            "border: 1px solid rgba(123,97,255,0.20);"\n'
    '            "border-radius: 8px;"\n'
    '            "font-size: 11px;"\n'
    '        )\n'
    '        self._discoverability_banner.setTextFormat(Qt.RichText)\n'
    '        self._discoverability_banner.setWordWrap(True)\n'
    + e1_old + '\n'
)
patch('E1 banner', 'self._discoverability_banner = QLabel(', e1_old, e1_new)

# E2a: pre-declare banner attr in __init__ next to SSML placeholders.
e2a_old = '        self._ssml_checkbox = None  # type: ignore[assignment]'
e2a_new = (
    e2a_old + '\n'
    '\n'
    '        # Discoverability banner: built in _build_editor_panel,\n'
    '        # auto-hides by _wire_signals wiring.\n'
    '        self._discoverability_banner = None\n'
)
patch('E2a banner pre-decl', 'Discoverability banner: built in _build_editor_panel', e2a_old, e2a_new)

# E2b: wire _maybe_hide_banner. Anchor: SSML chip toggled lambda.
e2b_old = (
    '        self._ssml_checkbox.toggled.connect(  # SSML-GUI-E11\n'
    '            lambda _checked: self._refresh_ssml_chip(\n'
    '                self._editor.toPlainText()\n'
    '            )\n'
    '        )\n'
)
e2b_new = e2b_old + (
    '\n'
    '        # Discoverability banner auto-hide: once the user\n'
    '        # has typed substantial text, the hint above the\n'
    '        # editor has served its purpose.\n'
    '        def _maybe_hide_banner() -> None:\n'
    '            db = getattr(self, "_discoverability_banner", None)\n'
    '            if db is not None and db.isVisible() and len(self._editor.toPlainText()) > 30:\n'
    '                db.hide()\n'
    '\n'
    '        self._editor.textChanged.connect(_maybe_hide_banner)\n'
)
patch('E2b auto-hide', 'def _maybe_hide_banner', e2b_old, e2b_new)

# E3: action row buttons (Dialogue ghost + SSML ?).
e3_old = '        row2.addSpacing(12)\n        row2.addWidget(self._ssml_checkbox)\n'
e3_new = (
    '        # Discoverability: always-visible Dialogue button +\n'
    '        # a small ? help button next to the Apply SSML checkbox.\n'
    '        row2.addSpacing(12)\n'
    '        self._dialogue_help_action_btn = QPushButton("\U0001F3AD  Dialogue")\n'
    "        self._dialogue_help_action_btn.setProperty('role', 'ghost')\n"
    '        self._dialogue_help_action_btn.setToolTip(\n'
    '            "Multi-Speaker Dialogue Mode.\n\n"'
    '            "Switch voices mid-script by typing a [voice_name]: marker\n"'
    '            "at the start of a line. Click for the syntax cheatsheet\n"'
    '            "and one-click sample-script insertion."\n'
    '        )\n'
    '        self._dialogue_help_action_btn.clicked.connect(self._on_dialogue_help_clicked)\n'
    '        row2.addWidget(self._dialogue_help_action_btn)\n'
    '        row2.addSpacing(12)\n'
    '        row2.addWidget(self._ssml_checkbox)\n'
    '        self._ssml_help_action_btn = QPushButton("?")\n'
    "        self._ssml_help_action_btn.setProperty('role', 'ghost')\n"
    '        self._ssml_help_action_btn.setFixedSize(28, 26)\n'
    '        self._ssml_help_action_btn.setToolTip("Show SSML-lite syntax examples")\n'
    '        self._ssml_help_action_btn.clicked.connect(self._on_ssml_help_clicked)\n'
    '        row2.addWidget(self._ssml_help_action_btn)\n'
)
patch('E3 action-row buttons', 'self._dialogue_help_action_btn', e3_old, e3_new)

# E4: SSML_HELP_TTS_SAMPLE constant — INSERT after SSML_HELP_SAMPLE.
if 'SSML_HELP_TTS_SAMPLE = (' not in text:
    open_anch = 'SSML_HELP_SAMPLE = """\n'
    if open_anch not in text:
        print('  [FAIL] E4 SSML_HELP_SAMPLE def missing'); sys.exit(1)
    s = text.index(open_anch)
    tail = '"""\n'
    e = text.find(tail, s)
    if e < 0:
        print('  [FAIL] E4 SSML_HELP_SAMPLE closing triple-quote'); sys.exit(1)
    insert_at = e + len(tail)
    e4_block = '\n\n# Short runnable SSML sample used by the help dialog Insert\n# button. Distinct from SSML_HELP_SAMPLE (prose doc) so the TTS\n# engine reads demo content rather than the cheat-sheet aloud.\nSSML_HELP_TTS_SAMPLE = (\n    \'Welcome <break time="300ms"/> to the SSML-lite demo.\n\'\n    \'Notice how this <emphasis>word</emphasis> is spoken a bit slower.\n\'\n    \'<prosody rate="fast">And this whole sentence is sped up.</prosody>\n\'\n    \'Finally <break time="1s"/> a one-second silence, then normal pace.\n\'\n)\n'
    text = text[:insert_at] + e4_block + text[insert_at:]
    print('  [OK]   E4 SSML_HELP_TTS_SAMPLE')
    save()
else:
    print('  [SKIP] E4')

# E5: dialogue dialog Insert-sample button.
e5_old = (
    '        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n'
    '        sample.setMinimumHeight(180)\n'
    '        root.addWidget(sample, 1)\n'
    '\n'
    '        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n'
)
e5_new = (
    e5_old[:e5_old.index('bbox')] +
    '        dialogue_action_row = QHBoxLayout()\n'
    '        dialogue_insert_btn = QPushButton("\U0001F4C4  Insert sample script")\n'
    "        dialogue_insert_btn.setProperty('role', 'primary')\n"
    '        dialogue_insert_btn.setToolTip(\n'
    '            "Load the dialogue demo into the editor and close. "'
    'Ctrl+Z undoes."\n'
    '        )\n'
    '\n'
    '        def _dialogue_insert_and_close() -> None:\n'
    '            self._editor.setPlainText(DIALOGUE_HELP_SAMPLE)\n'
    '            dlg.accept()\n'
    '\n'
    '        dialogue_insert_btn.clicked.connect(_dialogue_insert_and_close)\n'
    '        dialogue_action_row.addWidget(dialogue_insert_btn)\n'
    '        dialogue_action_row.addStretch(1)\n'
    '        root.addLayout(dialogue_action_row)\n'
    '\n'
    '        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n'
)
patch('E5 dialogue dialog Insert', '_dialogue_insert_and_close', e5_old, e5_new)

# E6: SSML dialog 
