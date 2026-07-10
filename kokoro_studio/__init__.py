# -*- coding: utf-8 -*-
"""Kokoro Studio — a PySide6 desktop GUI for Kokoro-82M TTS.

Local, free, fast, private neural text-to-speech. See README.md for an
overview, PLAN.md for the feature roadmap, and LICENSE for usage terms.

The package is organised as follows:

  * `kokoro_studio.engine`          Kokoro-82M wrapper + multi-format audio writer
  * `kokoro_studio.document_loader` TXT / PDF / EPUB parsers
  * `kokoro_studio.pronunciation`   pronunciation dictionary (load / save / apply)
  * `kokoro_studio.streaming`       real-time PCM streaming (Phase 2)
  * `kokoro_studio.blending`        voice blend presets (Phase 2 - Voice Blending)
  * `kokoro_studio.gui`             PySide6 main window
"""

from __future__ import annotations

# Eager submodule imports so that `import kokoro_studio; kokoro_studio.engine`
# works (otherwise `__all__` alone is just a hint for `from kokoro_studio
# import *` and the actual symbols stay unbound on the package). All
# submodules import their heavy deps lazily, so the cost at import time
# is just the (tiny) Python module load.
from kokoro_studio import (
    engine,
    document_loader,
    pronunciation,
    streaming,
    blending,
    gui,
)

__version__ = "0.1.0"
__author__ = "Matti"
__license__ = "Kokoro Studio Source-Available License v1.0"
__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "engine",
    "document_loader",
    "pronunciation",
    "streaming",
    "blending",
    "gui",
]
