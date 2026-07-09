# -*- coding: utf-8 -*-
"""`python -m kokoro_studio` entry point.

Forwards to `kokoro_studio.gui.main()` which constructs a `QApplication`,
wires up the main window, and runs the event loop. Module-level PySide6
imports are deferred to the gui module so `python -m kokoro_studio` exits
with a clean install-hint message if the dep is missing.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Console-script entry point declared in pyproject.toml."""
    # Lazy import so the install-hint check in gui.main() runs.
    from kokoro_studio.gui import main as _gui_main
    return _gui_main()


if __name__ == "__main__":
    sys.exit(main())
