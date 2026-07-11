#!/usr/bin/env python3
"""Follow-up discoverability-patcher for gui.py.

Applies two critical code-reviewer fixes to the already-applied patch:

  P9  Replace bare `Qt.TextInteractionFlag.TextSelectableByMouse` with a
      `getattr` fallback so the banner also works on PySide6 6.0/6.1
      (where the scoped enum doesn't exist).
  P10 Add an explicit `self._discoverability_banner.setTextFormat(Qt.RichText)`
      next to the existing setTextInteractionFlags call so the QLabel does
      not silently degrade to plain text if a future edit drops the
      `<html>...</html>` prefix from BANNER_HTML.

Atomic-batch pattern: read all, assert anchors, apply replaces in memory,
write once.
"""
import sys
from pathlib import Path

GUI = Path("kokoro_studio/gui.py")
raw = GUI.read_bytes()
crlf = raw.count(b"\r\n") > (raw.count(b"\n") / 2)
text = raw.decode("utf-8")
text_n = text.replace("\r\n", "\n") if crlf else text
import re
text_n = re.sub(r"\r\n?", "\n", text_n)
print(f"Loaded {GUI}: {len(raw):,} bytes, EOL={'CRLF' if crlf else 'LF'}")

# ---------------------------------------------------------------------------
# P9 + P10 combined into one anchor+replace (the old block has both issues)
# ---------------------------------------------------------------------------
P9_OLD = (
    "        self._discoverability_banner.setTextInteractionFlags(\n"
    "            Qt.TextInteractionFlag.TextSelectableByMouse\n"
    "        )\n"
    "        layout.addWidget(self._discoverability_banner)\n"
)
P9_NEW = (
    "        # PySide6 >= 6.2: scoped enums.  Older 6.0/6.1: only the bare\n"
    "        # name `Qt.TextSelectableByMouse` exists.  Fall back gracefully.\n"
    "        _ts_flag = getattr(\n"
    "            getattr(Qt, \"TextInteractionFlag\", Qt),\n"
    "            \"TextSelectableByMouse\",\n"
    "            Qt.TextSelectableByMouse,\n"
    "        )\n"
    "        self._discoverability_banner.setTextInteractionFlags(_ts_flag)\n"
    "        # Explicitly declare the QLabel's text format as RichText so the\n"
    "        # banner does not silently degrade to plain text if a future\n"
    "        # edit removes the <html>...</html> prefix from BANNER_HTML.\n"
    "        self._discoverability_banner.setTextFormat(Qt.RichText)\n"
    "        layout.addWidget(self._discoverability_banner)\n"
)

PATCHES = [
    ("P9/P10 Qt compat fallback + RichText", P9_OLD, P9_NEW),
]

# ---------------------------------------------------------------------------
# Verify anchors
# ---------------------------------------------------------------------------
print("\n[verify] asserting every anchor matches exactly once.")
for name, old, _new in PATCHES:
    n = text_n.count(old)
    if n != 1:
        if n == 0:
            print(f"  [FAIL] {name}: anchor NOT FOUND")
            print(f"          anchor head (60 chars): {old[:60]!r}")
        else:
            print(f"  [FAIL] {name}: matches {n} times (expected 1)")
        sys.exit(1)
    print(f"  [OK]   {name}")

# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
print("\n[patch] applying in memory.")
for name, old, new in PATCHES:
    text_n = text_n.replace(old, new, 1)
    print(f"  [OK]   {name}")

# ---------------------------------------------------------------------------
# Write once
# ---------------------------------------------------------------------------
if crlf:
    out_text = text_n.replace("\n", "\r\n")
else:
    out_text = text_n
GUI.write_bytes(out_text.encode("utf-8"))
print(f"\n[save] {GUI}: {len(out_text.encode('utf-8')):,} bytes written.")
print("Done.")
