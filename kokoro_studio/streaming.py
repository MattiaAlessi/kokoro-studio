# -*- coding: utf-8 -*-
"""Real-time audio streaming helper for Kokoro Studio.

Phase 2 — "Real-Time Streaming Playback". Streams Kokoro's lazy per-chunk
output into a `QAudioSink` so users hear audio ~200 ms after clicking
Generate, instead of waiting for the whole synthesis to finish.

Public API:
    PcmRingBuffer
        Pure-Python, thread-safe ring buffer for float32 mono PCM bytes.
        The Qt-free core lets us test push/pop/EOS semantics in isolation
        (see `tests/test_streaming.py`).
    StreamingPcmDevice
        `QIODevice` subclass that backs onto a `PcmRingBuffer` and is
        "sequential" so `QAudioSink.start()` will pull from it.
    make_kokoro_audio_format
        Convenience builder that returns a `QAudioFormat` matching the
        engine's float32 mono @ 24 kHz output, or `None` if QtMultimedia
        isn't importable.
    is_streaming_available
        True if `QMediaDevices.defaultAudioOutput()` reports a real
        audio device. Callers should fall back to file-based playback
        when this returns False (headless CI, RDP, etc.).

Threading:
    `PcmRingBuffer.push()` is called from the synthesis `QThread` (worker).
    `StreamingPcmDevice.readData()` is called by Qt's C++ audio thread
    (no GIL, *very* performance-sensitive). Both paths are guarded by a
    single `threading.Lock` — short critical sections keep the C++ thread
    happy while still keeping Python overhead low on the producer.

PySide6 GC warning (important):
   `QAudioSink.start(my_qio_device)` does NOT take ownership of the
   Python-side device. If the only Python reference is destroyed while
   Qt is still playing, PySide6 will segfault. The GUI keeps
   `self._streaming_device` and `self._audio_sink` as long-lived
   members of `KokoroStudioMain` to prevent this.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Deque, Optional

try:
    import numpy as np
    from PySide6.QtCore import QIODevice
    _HAS_QT_CORE = True
except ImportError:  # pragma: no cover — fallback for headless import
    np = None  # type: ignore[assignment]
    QIODevice = object  # type: ignore[assignment,misc]
    _HAS_QT_CORE = False

try:
    from PySide6.QtMultimedia import (
        QAudioFormat, QAudioSink, QMediaDevices,
    )
    _HAS_QT_MM = True
except ImportError:  # pragma: no cover
    QAudioFormat = None  # type: ignore[assignment]
    QAudioSink = None    # type: ignore[assignment]
    QMediaDevices = None # type: ignore[assignment]
    _HAS_QT_MM = False


# ----------------------------------------------------------------------------
# Pure-Python ring buffer (Qt-free, testable)
# ----------------------------------------------------------------------------

class PcmRingBuffer:
    """Thread-safe ring buffer of PCM bytes for streaming playback.

    The buffer distinguishes between three states when ``pop(maxlen)`` is
    called against an empty buffer:

        * Empty buffer, EOS NOT set → return silence
          (``b'\x00' * maxlen``). The Qt audio backend treats this as a
          brief underrun: it plays silence for a few ms, then tries to
          read again. Stream stays "alive".
        * Empty buffer, EOS set     → return ``b''``. This is the EOF
          contract Qt's audio backend looks for — it transitions the
          sink to ``IdleState``.

    Without this two-state contract, ``readData`` returning ``b''`` mid-
    stream (a normal underrun) would prematurely end the playback.

    Thread-safety: a single `threading.Lock` guards both ``push`` and
    ``pop``. Critical sections are short (deque ops + byte slicing),
    so producer + consumer can run concurrently without contention
    cost being measurable in the TTS hot path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunks: Deque[bytes] = deque()
        self._eos: bool = False
        # Cumulative counters (read while the lock is held). Used by
        # status bars / tests; never reset by `pop()`.
        self._bytes_pushed: int = 0
        self._bytes_consumed: int = 0

    # ---- Producer side --------------------------------------------------
    def push(self, data: bytes) -> None:
        """Append `data` to the buffer. Skips empty payloads (no-op)."""
        if not data:
            return
        with self._lock:
            self._chunks.append(bytes(data))
            self._bytes_pushed += len(data)

    def mark_eos(self) -> None:
        """Flag end-of-stream. Once set, the next pop on an empty buffer
        returns ``b''`` (signalling EOF to the audio backend).

        Idempotent — calling it twice is safe.
        """
        with self._lock:
            self._eos = True

    def reset(self) -> None:
        """Drop the buffer *and* clear the EOS flag.

        Used between syntheses to make sure no stale audio survives from
        a previous run. Cumulative counters are NOT reset."""
        with self._lock:
            self._chunks.clear()
            self._eos = False

    # ---- Consumer side --------------------------------------------------
    def pop(self, maxlen: int) -> bytes:
        """Return up to `maxlen` bytes.

        Returns:
            * Up to ``maxlen`` bytes of PCM data if available.
            * ``b'\x00' * maxlen`` (silence) if the buffer is empty and
              EOS has not been reached (underrun).
            * ``b''`` if the buffer is empty AND EOS has been reached
              (end of file).
        """
        if maxlen <= 0:
            return b""

        with self._lock:
            # Underrun / EOF contract:
            if not self._chunks:
                return b"" if self._eos else b"\x00" * maxlen
            out = bytearray()
            while len(out) < maxlen and self._chunks:
                chunk = self._chunks.popleft()
                space = maxlen - len(out)
                if len(chunk) <= space:
                    out.extend(chunk)
                else:
                    out.extend(chunk[:space])
                    # Remaining bytes go back at the front — the next
                    # pop will pick them up where the audio backend
                    # left off. Without this, partial-chunk reads
                    # would lose audio at the join.
                    self._chunks.appendleft(chunk[space:])
                    break
            self._bytes_consumed += len(out)
            return bytes(out)

    # ---- Inspection (always lock-guarded) ------------------------------
    def bytes_buffered(self) -> int:
        with self._lock:
            return sum(len(c) for c in self._chunks)

    def bytes_pushed(self) -> int:
        with self._lock:
            return self._bytes_pushed

    def bytes_consumed(self) -> int:
        with self._lock:
            return self._bytes_consumed

    def is_eos(self) -> bool:
        with self._lock:
            return self._eos


# ----------------------------------------------------------------------------
# Qt QIODevice wrapper for QAudioSink (pull-mode)
# ----------------------------------------------------------------------------

class StreamingPcmDevice(QIODevice):  # type: ignore[misc]
    """Sequential QIODevice backed by a `PcmRingBuffer`.

    Used as the sink device for `QAudioSink.start()`. Qt's C++ audio
    thread repeatedly calls ``readData(maxlen)`` here; we delegate to
    the (thread-safe) ring buffer so the consumer side stays trivially
    fast — no allocations, no lists, no copying beyond ``bytes()``.

    Why not `QBuffer`? `QBuffer` is a random-access device (its
    ``isSequential()`` returns False), and `QAudioSink` in push mode
    needs a sequential device. Hence the subclass.
    """

    def __init__(self, ring: PcmRingBuffer, parent=None) -> None:
        super().__init__(parent)
        self._ring = ring

    def isSequential(self) -> bool:  # noqa: N802 — Qt naming
        return True

    def readData(self, maxlen: int) -> bytes:  # noqa: N802 — Qt naming
        # MUST stay ultra-fast: this runs on Qt's C++ audio thread
        # without the GIL. The ring buffer's pop already keeps the
        # critical section short, so we're fine.
        if maxlen <= 0:
            return b""
        return self._ring.pop(maxlen)

    def writeData(self, data: bytes) -> int:  # noqa: N802 — Qt naming
        # Read-only device — synthesis writes audio chunks to the ring
        # buffer directly, not into the QIODevice.
        return 0


# ----------------------------------------------------------------------------
# QAudioFormat helpers
# ----------------------------------------------------------------------------

# Kokoro-82M native PCM output (float32, mono, 24 kHz). The streaming path
# DOWNCONVERTS this to 16-bit signed integer PCM before pushing bytes into
# the ring buffer — see `make_kokoro_audio_format` below for why.
KOKORO_SAMPLE_RATE = 24000
KOKORO_CHANNELS = 1
KOKORO_SAMPLE_FORMAT = "float32"  # informational; the engine produces this


def make_kokoro_audio_format(
    sample_rate: int = KOKORO_SAMPLE_RATE,
    channels: int = KOKORO_CHANNELS,
) -> Optional[object]:
    """Build a `QAudioFormat` for streaming playback of Kokoro's audio.

    Returns `None` if `PySide6.QtMultimedia` is not importable, so callers
    can degrade gracefully on a Python install without the `QtMultimedia`
    bindings (rare, but possible in slim CI images).

    Why Int16 and NOT Float32
    -------------------------
    Kokoro produces float32 mono @ 24 kHz, so the natural choice would be
    `QAudioFormat.SampleFormat.Float`. In practice that fails silently on
    Windows: Qt6's QAudioSink delegates to MediaFoundation, which refuses
    to negotiate float32 PCM with most WASAPI endpoints. The sink then
    sits in an inactive state, `error()` raises an IOError that the GUI
    never sees, and `readData()` keeps returning silence — the user hears
    nothing at all.

    Int16 (16-bit signed little-endian PCM) is supported by every audio
    backend Qt6 ships with (WASAPI/MediaFoundation on Windows, CoreAudio
    on macOS, ALSA/PulseAudio/PipeWire on Linux). We pay the downconversion
    cost once per chunk in `_on_streaming_chunk` and the audio path is
    zero-cost after that.
    """
    if not _HAS_QT_MM or QAudioFormat is None:
        return None
    fmt = QAudioFormat()
    fmt.setSampleRate(sample_rate)
    fmt.setChannelCount(channels)
    # Int16 = 16-bit signed integer PCM, native order on every supported
    # backend. Internally Qt (or the underlying backend) treats this as
    # two's-complement little-endian on x86/ARM, which is exactly what
    # numpy's `.astype(np.int16).tobytes()` emits.
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return fmt


def default_audio_output_is_available() -> bool:
    """Return True iff the platform exposes at least one audio output.

    Qt returns a null `QAudioOutput` device on systems without a working
    audio backend (Linux containers without PulseAudio/PipeWire, RDP
    sessions without sound redirection, etc.). When that's the case,
    streaming would fail silently — callers should detect it and fall
    back to file-based playback + `QMediaPlayer`.

    Returns False if QtMultimedia isn't importable.
    """
    if not _HAS_QT_MM or QMediaDevices is None:
        return False
    try:
        default = QMediaDevices.defaultAudioOutput()
    except Exception:  # pragma: no cover — defensive
        return False
    if default is None:
        return False
    # `isNull()` is the canonical check on a QAudioDevice.
    try:
        return not default.isNull()
    except AttributeError:  # pragma: no cover — non-Qt binding shim
        return default is not None


# Public symbols re-exported for `from kokoro_studio.streaming import …`
__all__ = [
    "PcmRingBuffer",
    "StreamingPcmDevice",
    "make_kokoro_audio_format",
    "default_audio_output_is_available",
    "KOKORO_SAMPLE_RATE",
    "KOKORO_CHANNELS",
    "KOKORO_SAMPLE_FORMAT",
]
