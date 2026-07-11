# -*- coding: utf-8 -*-
"""Kokoro Studio GUI package.

This package splits the formerly monolithic `kokoro_studio.gui` module
into focused sub-modules:

* `theme`      – shared QSS / styling and helper constants
* `workers`    – background synthesis worker
* `editor`     – drag-and-drop aware text editor
* `dialogs`    – feature windows (blend, history, pronunciation, help, settings)
* `main_window`– the primary application window
* `app`        – entry point / QApplication bootstrap

`kokoro_studio.gui` (the old module) is kept as a thin compatibility shim
that re-exports `main()` so existing launchers keep working.
"""

from __future__ import annotations

from kokoro_studio.gui.app import main

__all__ = ["main"]
