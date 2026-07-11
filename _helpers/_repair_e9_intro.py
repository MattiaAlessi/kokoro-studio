#!/usr/bin/env python3
"""Repair the E9 string-literal corruption in kokoro_studio/gui.py.

Background
----------
The earlier line-anchored SSML hooks script injected E9
(`_on_ssml_help_clicked`) into gui.py, but a few lines in the
``intro = QLabel(...)`` block accidentally embedded ``"<b>Apply
SSML</b>"`` as a quoted string literal *between* adjacent string
literals (the line ``"...tick \"<b>Apply SSML</b>\""`` produces
``"...tick " <identifier> "<b>Apply SSML</b>"`` in the file, which
is invalid Python).

The fix replaces the entire broken E9 method with a clean version
that uses Python's adjacent-string-literal concatenation pattern,
where each line is a complete ``"..."`` string and the next line
opens with another ``"`` so the lexer concatenates them.

Idempotent: the script logs and no-ops when called twice.
"""

from pathlib import Path

GUI = Path(r"C:\Users\matti\OneDrive\Desktop\Programmazione\Miei_prog\TTs\kokoro_studio\gui.py")


# The entire broken E9 region. Marker-start to the LAST E9 line
# (the final ``        dlg.exec()`` before ``    def
# _refresh_voice_readout(self) -> None:``).
#
# This string is used as the OLD-side of ``text.replace``. It's
# broken on purpose: we don't care about its parseability, only that
# it matches the file exactly.
BROKEN_E9 = """    # ----------------- Slot: SSML-lite help button (Phase 2)
    def _on_ssml_help_clicked(self) -> None:  # SSML-GUI-E9
        \"\"\"Popup a modal dialog with SSML-lite tag examples.

        Triggered by the small ? button next to the inline
        chip. Mirrors _on_dialogue_help_clicked so the two
        feature entrypoints feel identical.
        \"\"\"
        dlg = QDialog(self)
        dlg.setWindowTitle("SSML-lite Controls")
        dlg.resize(640, 480)
        dlg.setStyleSheet(SETTINGS_QSS)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        title = QLabel("\\u26A1  SSML-lite Controls")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "Tag-style controls for inline pauses, "
            "emphasis, and rate override. Type the literal "
            "markup into the editor and tick "<b>Apply SSML</b>"
            " on the controls panel.<br><br>"
            "<b>Notes:</b>"
            "<ul>"
            "<li>SSML-lite and multi-speaker dialogue are"
            " mutually exclusive. Dialogue mode wins"
            " silently; the chip turns amber to warn"<b>Apply SSML</b>"</li>"
            "<li>Tags work inside sentences: <code>he said"
            " &lt;emphasis&gt;wait&lt;/emphasis&gt;!</code>"
            " is valid.</li>"
            "<li>No nesting: open and close each tag in"
            " the order they appear; unclosed tags are"
            " kept literal as text and surface a stderr"
            " warning.</li>"
            "</ul>"
        )
"""


if True:
    # NEW E9 region. Triple-SINGLE-quote delimiters (''')
    # so internal double-quotes don't need escaping. Each line
    # is a complete "..." string so adjacent literals concatenate
    # cleanly at parse time. NOT a raw string so \u26A1 etc.
    # are interpreted as the actual unicode codepoints (⚡).
    NEW_E9 = '''    # ----------------- Slot: SSML-lite help button (Phase 2)
    def _on_ssml_help_clicked(self) -> None:  # SSML-GUI-E9
        """Popup a modal dialog with SSML-lite tag examples.

        Triggered by the small ? button next to the inline
        chip. Mirrors _on_dialogue_help_clicked so the two
        feature entrypoints feel identical.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("SSML-lite Controls")
        dlg.resize(640, 480)
        dlg.setStyleSheet(SETTINGS_QSS)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        title = QLabel("\u26A1  SSML-lite Controls")
        title.setObjectName("SettingsH1")
        root.addWidget(title)

        intro = QLabel(
            "Tag-style controls for inline pauses, "
            "emphasis, and rate override. Type the literal "
            "markup into the editor and tick "
            "<b>Apply SSML</b>"
            " on the controls panel.<br><br>"
            "<b>Notes:</b>"
            "<ul>"
            "<li>SSML-lite and multi-speaker dialogue are "
            "mutually exclusive. Dialogue mode wins silently; "
            "the chip turns amber to warn you.</li>"
            "<li>Tags work inside sentences: <code>he said "
            "&lt;emphasis&gt;wait&lt;/emphasis&gt;!</code> "
            "is valid.</li>"
            "<li>No nesting: open and close each tag in "
            "the order they appear; unclosed tags are kept "
            "literal as text and surface a stderr "
            "warning.</li>"
            "</ul>"
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setObjectName("SettingsBlock")
        intro.setOpenExternalLinks(True)
        root.addWidget(intro)

        sample = QPlainTextEdit(dlg)
        sample.setReadOnly(True)
        sample.setStyleSheet(
            "background-color: #1F2329; color: #E8EAED;"
            " border: 1px solid #252932; border-radius: 8px;"
            " padding: 10px;"
            " font-family: 'Consolas', 'Cascadia Code',"
            " 'JetBrains Mono', monospace;"
            " font-size: 12px;"
        )
        sample.setPlainText(SSML_HELP_SAMPLE)
        sample.setMinimumHeight(180)
        root.addWidget(sample, 1)

        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)
        close_btn.setText("Got it")
        close_btn.setProperty("role", "primary")
        bbox.accepted.connect(dlg.accept)
        root.addWidget(bbox)

        dlg.exec()
'''.replace("\\u26A1", "\u26A1")


def main() -> None:
    text = GUI.read_text(encoding="utf-8")

    # Drop the brittle early-return heuristic — the BROKEN_E9 in-text
    # check below already serves as a precise idempotency gate (if the
    # pattern isn't there, the repair has already been applied; do
    # nothing). The previous heuristic matched the broken region's
    # substring `Tag-style controls for inline pauses, ` (a substring
    # of the broken code too), so it incorrectly reported no-op on a
    # still-broken file.

    if BROKEN_E9 not in text:
        print("BROKEN_E9 pattern not present; repair already applied or file shape differs.")
        return

    occurrences = text.count(BROKEN_E9)
    if occurrences > 1:
        raise SystemExit(
            f"BROKEN_E9 pattern occurs {occurrences} times; expected 1."
        )

    new_text = text.replace(BROKEN_E9, NEW_E9, 1)
    GUI.write_text(new_text, encoding="utf-8")
    print(f"Repaired. Wrote {len(new_text):,} chars "
          f"(was {len(text):,}).")


if __name__ == "__main__":
    main()
