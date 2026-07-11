#!/usr/bin/env python3
"""Apply remaining 3 edits (E4-E7) and verify."""
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

# E4: SSML_HELP_TTS_SAMPLE
if 'SSML_HELP_TTS_SAMPLE = (' not in text:
    # Find the SSML_HELP_SAMPLE definition, locate the closing """\\n
    # variant. The exact close of this triple-quoted string is in the file.
    # Iterate to find the close marker.
    open_anch = 'SSML_HELP_SAMPLE = """\n'
    if open_anch not in text:
        print('  [FAIL] E4 cannot find SSML_HELP_SAMPLE def opening')
        sys.exit(1)
    s = text.index(open_anch)
    # Try common closing patterns:
    close_pats = ['""\n', '"""\\n', '"""\n']
    end = -1
    found = None
    for pat in close_pats:
        e = text.find(pat, s)
        if e > end:
            end = e
            found = pat
    if end < 0 or found is None:
        print('  [FAIL] E4 cannot find SSML_HELP_SAMPLE close')
        sys.exit(1)
    insert_at = end + len(found)
    e4_block = (
        '\n\n# Short runnable SSML sample used by the help dialog Insert\n'
        '# button. Distinct from SSML_HELP_SAMPLE (prose doc) so the TTS\n'
        '# engine reads demo content rather than the cheat-sheet aloud.\n'
        'SSML_HELP_TTS_SAMPLE = (\n'
        '    "Welcome <break time=\\"300ms\\"/> to the SSML-lite demo.\n"\n'
        '    "Notice how this <emphasis>word</emphasis> is spoken a bit slower.\n"\n'
        '    "<prosody rate=\\"fast\\">And this whole sentence is sped up.</prosody>\n"\n'
        '    "Finally <break time=\\"1s\\"/> a one-second silence, then normal pace.\n"\n'
        ')\n'
    )
    text = text[:insert_at] + e4_block + text[insert_at:]
    print('  [OK]   E4 SSML_HELP_TTS_SAMPLE (close pattern: ' + found + ')')
    save()
else:
    print('  [SKIP] E4 already applied')

# E5: dialogue dialog Insert button. Anchor: existing 5-line block in
# _on_dialogue_help_clicked that ends with `bbox = QDialogButtonBox`.
e5_old = (
    '        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n'
    '        sample.setMinimumHeight(180)\n'
    '        root.addWidget(sample, 1)\n'
    '\n'
    '        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n'
)
e5_new = e5_old[:e5_old.index('        bbox')] + (
    '        dialogue_action_row = QHBoxLayout()\n'
    '        dialogue_insert_btn = QPushButton("\U0001F4C4  Insert sample script")\n'
    '        dialogue_insert_btn.setProperty("role", "primary")\n'
    '        dialogue_insert_btn.setToolTip(\n'
    '            "Load the dialogue demo into the editor and close. "\n'
    '            "Ctrl+Z undoes the insert."\n'
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

# E6: SSML dialog Insert button. Uses SSML_HELP_TTS_SAMPLE + ticks checkbox.
e6_old = (
    '        sample.setPlainText(SSML_HELP_SAMPLE)\n'
    '        sample.setMinimumHeight(180)\n'
    '        root.addWidget(sample, 1)\n'
    '\n'
    '        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n'
)
e6_new = e6_old[:e6_old.index('        bbox')] + (
    '        ssml_action_row = QHBoxLayout()\n'
    '        ssml_insert_btn = QPushButton("\U0001F4C4  Insert sample + enable SSML")\n'
    '        ssml_insert_btn.setProperty("role", "primary")\n'
    '        ssml_insert_btn.setToolTip(\n'
    '            "Load the SSML demo into the editor, tick Apply SSML "\n'
    '            "and close. Ctrl+Z undoes the insert."\n'
    '        )\n'
    '\n'
    '        def _ssml_insert_and_enable() -> None:\n'
    '            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n'
    '            if self._ssml_checkbox is not None:\n'
    '                self._ssml_checkbox.setChecked(True)\n'
    '            dlg.accept()\n'
    '\n'
    '        ssml_insert_btn.clicked.connect(_ssml_insert_and_enable)\n'
    '        ssml_action_row.addWidget(ssml_insert_btn)\n'
    '        ssml_action_row.addStretch(1)\n'
    '        root.addLayout(ssml_action_row)\n'
    '\n'
    '        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n'
)
patch('E6 SSML dialog Insert', '_ssml_insert_and_enable', e6_old, e6_new)

# E7: About tab SSML-lite mention.
e7_old = (
    '<b>multi-speaker dialogue mode</b>, and a growing set of '
    'audiobook / batch features.<br><br>'
)
e7_new = (
    '<b>multi-speaker dialogue mode</b>, <b>SSML-lite controls</b>, '
    'and a growing set of audiobook / batch features.<br><br>'
)
patch('E7 About tab SSML mention', 'SSML-lite controls</b>', e7_old, e7_new)

print('\nAll remaining edits complete.')
