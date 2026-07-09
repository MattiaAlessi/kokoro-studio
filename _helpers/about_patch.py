"""P4: About-tab description — use ASCII-only split anchor."""
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

# Use a small ASCII-only anchor fragment + sed-style replacement.
# The exact substring "and a growing set of audiobook / batch features.<br><br>"
# is unique and ASCII-only.
OK_ANCHOR = "and a growing set of audiobook / batch features.<br><br>"
if OK_ANCHOR not in text:
    print("ERROR: about-tab anchor not found", file=sys.stderr); sys.exit(1)
text = text.replace(
    OK_ANCHOR,
    "<b>multi-speaker dialogue mode</b>, and a growing set of audiobook / batch features.<br><br>",
    1,
)
print("P4: about-tab description updated (multi-speaker mode mentioned)")

write(text)
print(f"Wrote: {GUI}")
