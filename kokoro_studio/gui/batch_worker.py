# -*- coding: utf-8 -*-
"""Background batch-queue worker for Kokoro Studio.

Phase 3 — "Batch Generation Queue". Processes a list of synthesis items
sequentially in a background thread, emitting progress signals so the GUI
can show per-item status and a final summary report.

Public API:
    BatchQueueItem
        Dataclass representing a single item in the batch queue.
    BatchItemResult
        Outcome of processing a single queue item.
    BatchSummary
        Aggregated result of a full batch run.
    BatchWorker
        QThread subclass that processes items sequentially and emits
        progress / result signals on the GUI thread.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional

from kokoro_studio.blending import VoiceBlend
from kokoro_studio.engine import SAMPLE_RATE, generate_speech


# ---------------------------------------------------------------------------
# Conditional Qt imports  (module stays importable without PySide6)
# ---------------------------------------------------------------------------

_HAS_PYSIDE6: bool
try:
    from PySide6.QtCore import QObject, QThread, Signal
    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False

    # Minimal stubs so the class definitions below don't fail at import
    # time.  BatchWorker.__init__ raises ImportError with a clear message
    # if PySide6 is absent.

    class QThread:  # type: ignore[no-redef]
        """Stub — real QThread from PySide6.QtCore."""
        def __init__(self, parent=None):  # type: ignore[no-untyped-def]
            self._parent = parent

    class QObject:  # type: ignore[no-redef]
        """Stub — real QObject from PySide6.QtCore."""
        pass

    class Signal:  # type: ignore[no-redef]
        """Stub — real Signal from PySide6.QtCore."""
        def __init__(self, *args: object, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
            pass
        def __get__(self, obj: object, objtype: object = None) -> object:  # type: ignore[no-untyped-def]
            return self
        def emit(self, *args: object, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
            pass


# ---------------------------------------------------------------------------
# Batch item
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BatchQueueItem:
    """A single unit of work in the batch queue.

    Fields:
        text:           Text to synthesise.
        voice:          Voice / blend name.
        speed:          Speed multiplier.
        output_path:    Full path where the resulting audio will be saved.
        output_format:  Format extension ('wav', 'mp3', 'flac', 'ogg').
        label:          Optional short label shown in the UI (default: filename stem).
    """

    text: str
    voice: str
    speed: float
    output_path: str
    output_format: str
    label: str = ""


# ---------------------------------------------------------------------------
# Batch status
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BatchItemResult:
    """Outcome of processing a single BatchQueueItem.

    Fields:
        item:        The item that was processed.
        duration_s:  Audio duration in seconds (0.0 on failure).
        success:     True if synthesis completed without error.
        error_msg:   Human-readable error text (empty on success).
    """

    item: BatchQueueItem
    duration_s: float
    success: bool
    error_msg: str = ""


@dataclass(frozen=True)
class BatchSummary:
    """Aggregated result of a full batch run.

    Fields:
        total:       Number of items in the batch.
        succeeded:   Number of items that completed successfully.
        failed:      Number of items that errored.
        total_audio_duration_s:  Sum of all successful audio durations.
        elapsed_s:   Wall-clock seconds the batch took to run.
    """

    total: int
    succeeded: int
    failed: int
    total_audio_duration_s: float
    elapsed_s: float


# ---------------------------------------------------------------------------
# Batch worker
# ---------------------------------------------------------------------------

class BatchWorker(QThread):
    """Processes a list of BatchQueueItem values sequentially.

    Signals (all emitted on the GUI thread):
        item_progress(int current, int total, str label)
            Fired when starting a new item — ``current`` is 1‑based.

        item_done(int index, BatchItemResult result)
            Fired after each item finishes (success or failure).

        finished_ok(BatchSummary summary)
            All items processed; ``summary.failed`` may be > 0.

        failed(str error_msg)
            A fatal error that aborted the entire batch (e.g. missing
            kokoro dependency).

    Usage:
        worker = BatchWorker(items)
        worker.item_done.connect(self._on_batch_item_done)
        worker.finished_ok.connect(self._on_batch_finished)
        worker.start()
    """

    item_progress = Signal(int, int, str)
    item_done = Signal(int, object)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        items: List[BatchQueueItem],
        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        blends: Optional[Mapping[str, VoiceBlend]] = None,
        apply_ssml: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        if not _HAS_PYSIDE6:
            raise ImportError(
                "BatchWorker requires PySide6.\n\nRun:  pip install PySide6"
            )
        super().__init__(parent)
        self._items = list(items)
        self._pronunciation_rules = (
            dict(pronunciation_rules) if pronunciation_rules else None
        )
        self._multi_speaker = multi_speaker
        self._speaker_gap_s = speaker_gap_s
        self._blends: Optional[dict] = dict(blends) if blends else None
        self._apply_ssml = bool(apply_ssml)
        self._stop_requested = False

    def request_stop(self) -> None:
        """Request graceful cancellation after the current item finishes."""
        self._stop_requested = True

    def run(self) -> None:
        start_wall = time.time()
        results: List[BatchItemResult] = []
        n_total = len(self._items)

        try:
            for idx, item in enumerate(self._items):
                if self._stop_requested:
                    break

                label = item.label or Path(item.output_path).stem
                self.item_progress.emit(idx + 1, n_total, label)

                try:
                    audio = generate_speech(
                        text=item.text,
                        voice=item.voice,
                        speed=item.speed,
                        output_path=item.output_path,
                        output_format=item.output_format,
                        pronunciation_rules=self._pronunciation_rules,
                        multi_speaker=self._multi_speaker,
                        speaker_gap_s=self._speaker_gap_s,
                        blends=self._blends,
                        apply_ssml=self._apply_ssml,
                        on_chunk=None,
                        stop_check=self._stop_check,
                    )
                    duration_s = len(audio) / SAMPLE_RATE
                    results.append(BatchItemResult(
                        item=item, duration_s=duration_s, success=True,
                    ))
                except RuntimeError as e:
                    if "cancelled" in str(e).lower():
                        results.append(BatchItemResult(
                            item=item, duration_s=0.0, success=False,
                            error_msg="Cancelled.",
                        ))
                        # Emit BEFORE break so the UI row updates
                        self.item_done.emit(idx, results[-1])
                        break
                    results.append(BatchItemResult(
                        item=item, duration_s=0.0, success=False,
                        error_msg=f"{type(e).__name__}: {e}",
                    ))
                except Exception as e:
                    results.append(BatchItemResult(
                        item=item, duration_s=0.0, success=False,
                        error_msg=f"{type(e).__name__}: {e}",
                    ))

                self.item_done.emit(idx, results[-1])
        except ImportError as e:
            self.failed.emit(
                f"Missing dependency: {e}\nRun: pip install kokoro soundfile numpy"
            )
            return

        elapsed = time.time() - start_wall
        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded
        total_audio = sum(r.duration_s for r in results if r.success)

        summary = BatchSummary(
            total=n_total,
            succeeded=succeeded,
            failed=failed,
            total_audio_duration_s=total_audio,
            elapsed_s=elapsed,
        )
        self.finished_ok.emit(summary)

    def _stop_check(self) -> bool:
        return self._stop_requested
