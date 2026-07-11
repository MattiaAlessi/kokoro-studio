# -*- coding: utf-8 -*-
"""Application entry point for the Kokoro Studio GUI."""

from __future__ import annotations

import sys

try:
    from PySide6.QtWidgets import QApplication
    _HAS_PYSIDE6 = True
except ImportError as _e:
    _HAS_PYSIDE6 = False
    _PYSIDE_IMPORT_ERR = str(_e)


def main() -> int:
    if not _HAS_PYSIDE6:
        sys.stderr.write(
            "\nKokoro Studio requires PySide6.\n\n"
            "    pip install PySide6\n\n"
            f"Import error: {_PYSIDE_IMPORT_ERR}\n"
        )
        return 1

    # Defer these imports so the install-hint path above can run without
    # PySide6 installed.
    from kokoro_studio.gui.main_window import KokoroStudioMain
    from kokoro_studio.gui.theme import QSS

    app = QApplication(sys.argv)
    app.setApplicationName("Kokoro Studio")
    app.setOrganizationName("Kokoro Studio")
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    window = KokoroStudioMain()
    window.show()
    return app.exec()
