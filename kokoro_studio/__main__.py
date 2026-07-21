# -*- coding: utf-8 -*-
"""`python -m kokoro_studio` entry point.

Without arguments (or with ``gui`` subcommand) launches the desktop GUI.
Use the ``batch`` subcommand for headless batch generation:

    python -m kokoro_studio batch input.txt --voice af_heart
    kokoro-studio batch input.txt --speed 1.2 --format mp3

For full help:
    kokoro-studio batch --help
"""

from __future__ import annotations

import sys


def main() -> int:
    """Console-script entry point declared in pyproject.toml.

    Dispatches to the GUI by default, or to the CLI batch subcommand when
    the ``batch`` argument is detected.
    """
    # Check if the first CLI argument is a CLI subcommand — if so,
    # skip the GUI and dispatch to the CLI.
    if len(sys.argv) >= 2 and sys.argv[1] in ("batch", "serve"):
        # Defer import so headless systems without PySide6 can still
        # use the CLI (kokoro_studio.cli has no Qt dependency).
        from kokoro_studio.cli import main as _cli_main
        return _cli_main(sys.argv[1:])

    # Default: launch the desktop GUI.
    # Lazy import so the install-hint check in gui.main() runs.
    from kokoro_studio.gui import main as _gui_main
    return _gui_main()


if __name__ == "__main__":
    sys.exit(main())
