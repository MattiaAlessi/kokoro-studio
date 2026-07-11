"""Verify all 9 discoverability edits are present in gui.py."""
from pathlib import Path

GUI = Path(r"C:\Users\matti\OneDrive\Desktop\Programmazione\Miei_prog\TTs\kokoro_studio\gui.py")

raw = GUI.read_bytes().decode("utf-8")
text = raw.replace("\r\n", "\n")

checks = [
    ("discoverability banner widget", "self._discoverability_banner = QLabel("),
    ("banner inserted in editor panel", "Discoverability banner (Phase 2 power features)"),
    ("banner attr pre-declared", "self._discoverability_banner = None  # parity init"),
    ("banner auto-hide wired", "_maybe_hide_banner"),
    ("always-visible Dialogue button", "self._dialogue_help_action_btn"),
    ("SSML help ? button in row2", "self._ssml_help_action_btn"),
    ("SSML_HELP_TTS_SAMPLE defined", "SSML_HELP_TTS_SAMPLE = ("),
    ("dialogue Insert button", "Insert sample script"),
    ("SSML Insert button", "Insert sample + enable SSML"),
    ("SSML Insert uses TTS sample (not prose)", "self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)"),
    ("About tab mentions SSML-lite", "<b>SSML-lite controls</b>"),
]

fail = 0
for label, needle in checks:
    ok = needle in text
    print(("OK   " if ok else "MISS ") + " " + label)
    if not ok:
        fail += 1

print(f"\n{len(checks) - fail}/{len(checks)} checks passed.")
