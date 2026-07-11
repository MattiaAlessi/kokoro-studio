#!/usr/bin/env python3
"""Byte-exact fix for the QDialogButtonBox.clickedButton() AttributeError.

Anchors were confirmed against the actual file content (E7 region around
line 2590, E8 region around line 2673) so the match count is reliable.

Fix: closure-based insert+accept.  ActionRole buttons don't auto-close, so
the click handler does the insert AND calls dlg.accept() itself.  No more
post-exec "which button was clicked" check.
"""
import sys
from pathlib import Path

GUI = Path("kokoro_studio/gui.py")
raw = GUI.read_bytes()
text = raw.decode("utf-8")
import re
text_lf = re.sub(r"\r\n?", "\n", text)
print(f"Loaded {GUI}: {len(raw):,} bytes")

# ---------------------------------------------------------------------------
# E7 anchor: 14-line block at line 2590..2603 (byte-exact)
# ---------------------------------------------------------------------------
E7_OLD = (
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample script",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        # ActionRole buttons don't auto-close the modal dialog, so\n"
    "        # wire clicked -> dlg.accept().  This keeps the post-exec\n"
    "        # `clickedButton() is insert_btn` check working correctly.\n"
    "        insert_btn.clicked.connect(dlg.accept)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
    "        if bbox.clickedButton() is insert_btn:\n"
    "            self._editor.setPlainText(DIALOGUE_HELP_TTS_SAMPLE)\n"
)
E7_NEW = (
    "        # ActionRole buttons don't auto-close.  Closure-based\n"
    "        # insert+accept (QDialogButtonBox has no clickedButton() API).\n"
    "        def _handle_dialogue_insert():\n"
    "            # setPlainText MUST run before dlg.accept() or the\n"
    "            # editor update is lost on modal event-loop return.\n"
    "            self._editor.setPlainText(DIALOGUE_HELP_TTS_SAMPLE)\n"
    "            dlg.accept()\n"
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample script",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(_handle_dialogue_insert)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
)

# ---------------------------------------------------------------------------
# E8 anchor: 11-line block at line 2673..2683 (byte-exact)
# ---------------------------------------------------------------------------
E8_OLD = (
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample + enable SSML",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(dlg.accept)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
    "        if bbox.clickedButton() is insert_btn:\n"
    "            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n"
    "            self._ssml_checkbox.setChecked(True)\n"
)
E8_NEW = (
    "        # Same closure-based insert+accept pattern as the dialogue handler.\n"
    "        def _handle_ssml_insert():\n"
    "            # setPlainText + setChecked MUST run before dlg.accept()\n"
    "            # or the editor / checkbox updates are lost on return.\n"
    "            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n"
    "            self._ssml_checkbox.setChecked(True)\n"
    "            dlg.accept()\n"
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample + enable SSML",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(_handle_ssml_insert)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
)

PATCHES = [
    ("E7 dialogue Insert closure", E7_OLD, E7_NEW),
    ("E8 SSML Insert closure", E8_OLD, E8_NEW),
]

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
print("\n[verify] asserting every anchor matches exactly once.")
for name, old, _new in PATCHES:
    n = text_lf.count(old)
    if n != 1:
        if n == 0:
            print(f"  [FAIL] {name}: anchor NOT FOUND")
            print(f"          anchor head (60 chars): {old[:60]!r}")
        else:
            print(f"  [FAIL] {name}: matches {n} times (expected 1)")
        sys.exit(1)
    print(f"  [OK]   {name}: count={n}")

# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
print("\n[patch] applying 2 replaces in memory.")
for name, old, new in PATCHES:
    text_lf = text_lf.replace(old, new, 1)
    print(f"  [OK]   {name}")

# ---------------------------------------------------------------------------
# Re-stamp CRLF
# ---------------------------------------------------------------------------
if "\r\n" in text:
    out = text_lf.replace("\n", "\r\n")
else:
    out = text_lf
GUI.write_bytes(out.encode("utf-8"))
print(f"\n[save] {GUI}: {len(out.encode('utf-8')):,} bytes written.")
print("Done.")
