#!/usr/bin/env python3
"""Atomic fix for the QDialogButtonBox.clickedButton() AttributeError.

The previous E7/E8 patcher wired a post-exec `if bbox.clickedButton() is
insert_btn:` check, but QDialogButtonBox has no `clickedButton()` method.
This script applies 4 surgical replaces to fix both E7 and E8 handlers.

Strategy: closure-based dispatch.  The click handler does the insert +
accept itself, so no post-exec "which button was clicked" check is needed.
"""
import sys
from pathlib import Path

GUI = Path("kokoro_studio/gui.py")
raw = GUI.read_bytes()
text = raw.decode("utf-8")
text_lf = text.replace("\r\n", "\n")
import re
text_lf = re.sub(r"\r\n?", "\n", text_lf)
print(f"Loaded {GUI}: {len(raw):,} bytes")

# ---------------------------------------------------------------------------
# A. E7 click handler (Insert sample script) - 5-line block, uniquely E7
#    Replace auto-close wire with closure that does insert + accept.
# ---------------------------------------------------------------------------
A_OLD = (
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample script",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(dlg.accept)\n"
)
A_NEW = (
    "        # ActionRole buttons don't auto-close.  Do the insert + accept\n"
    "        # in the click handler itself (QDialogButtonBox has no\n"
    "        # clickedButton() API, so closure-based dispatch is the\n"
    "        # idiomatic PySide approach).\n"
    "        def _handle_dialogue_insert():\n"
    "            self._editor.setPlainText(DIALOGUE_HELP_TTS_SAMPLE)\n"
    "            dlg.accept()\n"
    "\n"
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample script",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(_handle_dialogue_insert)\n"
)

# ---------------------------------------------------------------------------
# B. E7 broken post-exec check - 2-line block, uniquely E7
# ---------------------------------------------------------------------------
B_OLD = (
    "        if bbox.clickedButton() is insert_btn:\n"
    "            self._editor.setPlainText(DIALOGUE_HELP_TTS_SAMPLE)\n"
)
B_NEW = (
    "        # (Insert button now does the work in its click handler closure.)\n"
)

# ---------------------------------------------------------------------------
# C. E8 click handler (Insert sample + enable SSML) - 5-line block, uniquely E8
# ---------------------------------------------------------------------------
C_OLD = (
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample + enable SSML",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(dlg.accept)\n"
)
C_NEW = (
    "        # Same closure-based insert+accept pattern as the dialogue handler.\n"
    "        def _handle_ssml_insert():\n"
    "            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n"
    "            self._ssml_checkbox.setChecked(True)\n"
    "            dlg.accept()\n"
    "\n"
    "        insert_btn = bbox.addButton(\n"
    '            "Insert sample + enable SSML",\n'
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(_handle_ssml_insert)\n"
)

# ---------------------------------------------------------------------------
# D. E8 broken post-exec check - 3-line block, uniquely E8
# ---------------------------------------------------------------------------
D_OLD = (
    "        if bbox.clickedButton() is insert_btn:\n"
    "            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n"
    "            self._ssml_checkbox.setChecked(True)\n"
)
D_NEW = (
    "        # (Insert button now does the work in its click handler closure.)\n"
)

PATCHES = [
    ("A E7 click handler closure", A_OLD, A_NEW),
    ("B E7 broken post-exec check", B_OLD, B_NEW),
    ("C E8 click handler closure", C_OLD, C_NEW),
    ("D E8 broken post-exec check", D_OLD, D_NEW),
]

# ---------------------------------------------------------------------------
# Verify each anchor matches exactly once.
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
print("\n[patch] applying 4 replaces in memory.")
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
