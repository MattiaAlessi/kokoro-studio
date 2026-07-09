"""Diagnostic: dump exact byte content of suspected mismatched lines to a file."""
data = open("kokoro_studio/gui.py", "rb").read().decode("utf-8")
data = data.replace("\r\n", "\n")

# Test each of the 6 P_OLD lines individually + joined
lines = [
    'self._editor.setPlaceholderText(',
    '            "Type or paste your text here.\\n\\n"',
    "            \"Tip: long inputs are split automatically by Kokoro's tokenizer \u2014\\n\"",
    '            "you can paste entire chapters without performance concerns.\\n\\n"',
    '            "Or drop a .txt / .pdf / .epub file here, or click \u201cOpen\u2026\u201d."',
    '        )',
]

joined = "\n".join(lines)
output = []
output.append(f"Joined length: {len(joined)}")
output.append(f"Joined found at: {data.find(joined)}")
output.append("")

for i, line in enumerate(lines):
    pos = data.find(line)
    output.append(f"--- line {i} ---")
    output.append(f"  Pattern: {line!r}")
    output.append(f"  Pattern length: {len(line)}")
    output.append(f"  Found at: {pos}")
    # Print pattern's chars 0..N as a sequence of code points for debugging
    cplist = [f"U+{ord(c):04X}" for c in line[60:80] if 60 < 60+len(line)]
    output.append(f"  Pattern codepoints (chars 60-80): " + ", ".join(f"U+{ord(c):04X}({c!r})" for c in line[60:80]))
    if pos > 0:
        # Print the actual file content at that position for the same length
        actual = data[pos:pos+len(line)]
        output.append(f"  Actual chars 60-80: " + ", ".join(f"U+{ord(c):04X}({c!r})" for c in actual[60:80]))
        output.append(f"  Match: {line == actual}")

# Also dump the exact bytes around "Open" line
pos = data.find("Or drop a .txt")
output.append(f"\n\nBytes around 'Or drop' (position {pos}):")
output.append(repr(data[pos-5:pos+90]))
output.append("\nCodepoint diversity:")
around = data[pos:pos+90]
for c in around:
    if ord(c) > 127:
        output.append(f"  Non-ASCII char: U+{ord(c):04X} {c!r}")

with open("_helpers/_diag_output.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))
print("Wrote diagnostic to _helpers/_diag_output.txt")
