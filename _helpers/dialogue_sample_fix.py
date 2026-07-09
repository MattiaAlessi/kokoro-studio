"""Targeted fixes from code review:
1. DIALOGUE_HELP_SAMPLE contained a real [am_adam]: marker INSIDE the
   explanatory text which would have been parsed as a voice-change. Fix:
   reword that line so the example markers are shown as quoted explanatory
   text rather than real marker syntax.
2. Pre-declare `self._dialogue_btn = None` in __init__ for consistency
   with the other dialogue-related widget attributes.
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

# ---------- Fix 1: DIALOGUE_HELP_SAMPLE — escape the explanatory marker ----------
SAMPLE_OLD_LINE = (
    '    "[af_heart]: Great! Notice how my voice changes when you see a marker like\\n"\n'
    '    "            [am_adam]: or  [af_bella]: at the start of a line.\\n"\n'
)
# New version shows the marker syntax in a way the parser cannot misread:
# uses backticks-with-spaces so the line doesn't start with a [token]:
SAMPLE_NEW_LINE = (
    '    "[af_heart]: Great! Notice how my voice changes when you see a marker like\\n"\n'
    '    "            e.g. an [am_adam] tag, or an [af_bella] tag, at the start of a line.\\n"\n'
)
if not verify("SAMPLE_OLD", SAMPLE_OLD_LINE, text):
    sys.exit(1)
text = text.replace(SAMPLE_OLD_LINE, SAMPLE_NEW_LINE, 1)
print("1/2 DIALOGUE_HELP_SAMPLE fixed (no real markers in explanatory text)")

# ---------- Fix 2: Pre-declare _dialogue_btn in __init__ ----------
# Anchor: the existing pre-declaration of _dialogue_chip_row / _dialogue_help_btn.
# We add `self._dialogue_btn = None  # type: ignore[assignment]` next to them.
PRE_DECL_BLOCK_NEW = (
    '        # Phase 2 — Multi-Speaker Dialogue Mode.\n'
    '        # `self._dialogue_chip` is the inline label that shows a live\n'
    '        # "N speakers detected: voice1, voice2, ..." hint as soon as\n'
    '        # the user types the first [voice]: marker. It\'s hidden when\n'
    '        # no markers are present so single-speaker scripts don\'t clutter\n'
    '        # the controls panel.\n'
    '        self._dialogue_chip = None  # type: ignore[assignment]\n'
    '        # `_dialogue_chip_row` wraps the chip + help button in a\n'
    '        # single QWidget so they can be hidden together by\n'
    '        # `_refresh_dialogue_chip`. Set to None here; the actual\n'
    '        # widget is built by `_build_controls_panel` after this\n'
    '        # __init__ returns. The `getattr` defensive read in\n'
    '        # `_refresh_dialogue_chip` covers the pre-build window.\n'
    '        self._dialogue_chip_row = None  # type: ignore[assignment]\n'
    '        self._dialogue_help_btn = None  # type: ignore[assignment]\n'
    # NEW attribute pre-declaration:
    '        # `self._dialogue_btn` is the always-visible "Dialogue"\n'
    '        # QPushButton built in `_build_controls_panel` and wired\n'
    '        # in `_wire_signals` (Discoverability). Pre-declared here\n'
    '        # so any pre-build reads (rare but possible via\n'
    '        # setPlainText / eventFilter paths) return None cleanly.\n'
    '        self._dialogue_btn = None  # type: ignore[assignment]\n'
)
PRE_DECL_BLOCK_OLD = (
    '        # Phase 2 — Multi-Speaker Dialogue Mode (Phase 2 next-up).\n'
    '        # `self._dialogue_chip` is the inline label that shows a\n'
    '        # live "🎭 N speakers detected: voice1, voice2, …" hint as\n'
    '        # soon as the user types the first `[voice]:` marker. It\'s\n'
    '        # hidden when no markers are present so single-speaker\n'
    '        # scripts don\'t clutter the controls panel.\n'
    '        self._dialogue_chip = None  # type: ignore[assignment]\n'
    '        # `_dialogue_chip_row` wraps the chip + help button in a\n'
    '        # single QWidget so they can be hidden together by\n'
    '        # `_refresh_dialogue_chip`. Set to None here; the actual\n'
    '        # widget is built by `_build_controls_panel` after this\n'
    '        # __init__ returns. The `getattr` defensive read in\n'
    '        # `_refresh_dialogue_chip` covers the pre-build window.\n'
    '        self._dialogue_chip_row = None  # type: ignore[assignment]\n'
    '        self._dialogue_help_btn = None  # type: ignore[assignment]\n'
)
if not verify("PRE_DECL_BLOCK", PRE_DECL_BLOCK_OLD, text):
    sys.exit(1)
text = text.replace(PRE_DECL_BLOCK_OLD, PRE_DECL_BLOCK_NEW, 1)
print("2/2 _dialogue_btn pre-declared in __init__ (consistency fix)")

write(text)
print(f"\nFixes applied. Wrote: {GUI}")
