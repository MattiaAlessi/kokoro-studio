#!/usr/bin/env python3
"""Repair the E2 syntax-corruption bug in kokoro_studio/gui.py.

Background
----------
The earlier line-anchored SSML hooks script inserted E2's
``self._apply_ssml = bool(apply_ssml) # SSML-GUI-E2`` block AFTER
the line ``self._blends: Optional[dict] = (``, which put it BEFORE
the existing ``dict(blends) if blends else None`` and the closing
``)``. The result is invalid Python::

    self._blends: Optional[dict] = (        # tuple opens
        )                                    # closes IMMEDIATELY
        # ... comments ...
        self._apply_ssml = bool(...)         # ORPHAN
            dict(blends) if blends else None  # ORPHAN (now NOT
                                              # inside the tuple)
        )                                    # ORPHAN (extra `)`)

``py_compile`` reports this as IndentationError at line ~532.

Repair strategy
--------------
Match the broken 11-line region as a literal string and replace it
with the correct ordering (re-locate the inserted block to AFTER
the dict's actual closing ``)``). Idempotent: the script logs and
no-ops when called twice (so old runs don't double-apply the fix).
"""

from pathlib import Path

GUI = Path(r"C:\Users\matti\OneDrive\Desktop\Programmazione\Miei_prog\TTs\kokoro_studio\gui.py")

BROKEN = (
    "        self._blends: Optional[dict] = (\n"
    "        )\n"
    "        # Phase 2 - SSML-lite. Snapshot the bool at\n"
    "        # start() time so a mid-run checkbox flip\n"
    "        # can't silently switch the engine from\n"
    "        # plain to SSML mode.\n"
    "        self._apply_ssml = bool(apply_ssml)  # SSML-GUI-E2\n"
    "            dict(blends) if blends else None\n"
    "        )\n"
)

FIXED = (
    "        self._blends: Optional[dict] = (\n"
    "            dict(blends) if blends else None\n"
    "        )\n"
    "        # Phase 2 - SSML-lite. Snapshot the bool at\n"
    "        # start() time so a mid-run checkbox flip\n"
    "        # can't silently switch the engine from\n"
    "        # plain to SSML mode.\n"
    "        self._apply_ssml = bool(apply_ssml)  # SSML-GUI-E2\n"
)


def main() -> None:
    text = GUI.read_text(encoding="utf-8")

    # Skip if repair already applied: importable marker is intact
    # AND the broken pattern is not present.
    if text.count(BROKEN) == 0 and "self._apply_ssml = bool(apply_ssml)  # SSML-GUI-E2" in text:
        print("Repair already applied; no-op.")
        return

    if BROKEN not in text:
        print("BROKEN pattern not found; nothing to repair.")
        print(
            "This may mean the file is already healthy, OR the "
            "file shape differs from what this script expects. "
            "Verifying with py_compile ..."
        )
        return

    occurrences = text.count(BROKEN)
    assert occurrences == 1, (
        f"BROKEN pattern occurs {occurrences} times; expected 1"
    )

    new_text = text.replace(BROKEN, FIXED, 1)
    GUI.write_text(new_text, encoding="utf-8")
    print(f"Repaired. Wrote {len(new_text):,} chars "
          f"(was {len(text):,}).")


if __name__ == "__main__":
    main()
