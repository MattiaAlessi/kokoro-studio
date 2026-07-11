# -*- coding: utf-8 -*-
"""Drag-and-drop aware text editor for the Kokoro Studio GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class DocumentDropEditor(QPlainTextEdit):
    """`QPlainTextEdit` that intercepts dropped files.

    Default `QPlainTextEdit.dropEvent` only handles in-app text drags.
    We override both `dragEnterEvent` and `dropEvent` so that files
    dragged from the OS whose extension matches our supported document
    set are accepted. A `fileDropped(str)` signal then bubbles the
    absolute path back to the main window.
    """

    fileDropped = Signal(str)
    multiDropRejected = Signal(int)

    _SUPPORTED_DROP_EXTS = (".txt", ".pdf", ".epub")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if self._supported_file_count(event) == 1:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._supported_file_count(event) == 1:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        supported = self._supported_file_url(event)
        if supported is None:
            super().dropEvent(event)
            return
        if isinstance(supported, list):
            self.multiDropRejected.emit(len(supported))
            event.ignore()
            return
        self.fileDropped.emit(supported)
        event.acceptProposedAction()

    def _supported_file_count(self, event) -> int:
        if not event.mimeData().hasUrls():
            return 0
        n = 0
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            ext = Path(url.toLocalFile()).suffix.lower()
            if ext in self._SUPPORTED_DROP_EXTS:
                n += 1
        return n

    def _supported_file_url(self, event):
        if not event.mimeData().hasUrls():
            return None
        found = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            local = url.toLocalFile()
            if Path(local).suffix.lower() in self._SUPPORTED_DROP_EXTS:
                found.append(local)
        if not found:
            return None
        if len(found) == 1:
            return found[0]
        return found
