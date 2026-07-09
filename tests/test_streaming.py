# -*- coding: utf-8 -*-
"""Tests for `kokoro_studio.streaming` (Phase 2 real-time playback).

The bulk of the suite tests `PcmRingBuffer` directly because it's a
pure-Python thread-safe buffer with no Qt dep. The Qt-touching tests
for `StreamingPcmDevice`, `make_kokoro_audio_format`, and
`default_audio_output_is_available` are gated behind a skip-if-missing
guard so the suite runs cleanly on CI images without PySide6.
"""

from __future__ import annotations

import threading
import time

import pytest

from kokoro_studio.streaming import PcmRingBuffer


# ===========================================================================
# PcmRingBuffer — pure Python, no Qt
# ===========================================================================

def test_push_then_pop_returns_pushed_bytes():
    rb = PcmRingBuffer()
    rb.push(b"abc")
    assert rb.pop(10) == b"abc"
    # Cumulative counters reflect the push.
    assert rb.bytes_pushed() == 3
    assert rb.bytes_consumed() == 3


def test_pop_splits_chunk_across_two_reads():
    rb = PcmRingBuffer()
    rb.push(b"hello world")
    assert rb.pop(5) == b"hello"
    assert rb.pop(6) == b" world"
    assert rb.pop(5) == b"\x00" * 5   # underrun → silence (eos not set)


def test_pop_pads_silence_on_underrun_not_eos():
    """Empty buffer + eos NOT set → returns `maxlen` silence bytes.

    Returning silence (not empty bytes) is the contract that keeps
    QAudioSink alive mid-stream. An empty pop would prematurely end
    playback on a normal underrun.
    """
    rb = PcmRingBuffer()
    assert rb.pop(8) == b"\x00" * 8
    rb.push(b"X")
    # 5-byte request, 1 byte available, 4 bytes of silence pad.
    assert rb.pop(5) == b"X" + b"\x00" * 4


def test_pop_zero_maxlen_returns_empty():
    rb = PcmRingBuffer()
    rb.push(b"abc")
    assert rb.pop(0) == b""


def test_negative_maxlen_treated_like_zero():
    rb = PcmRingBuffer()
    rb.push(b"abc")
    assert rb.pop(-3) == b""


def test_mark_eos_then_drained_returns_empty():
    """Empty buffer + eos SET → returns b''. Signals EOF to QAudioSink."""
    rb = PcmRingBuffer()
    rb.mark_eos()
    assert rb.pop(100) == b""


def test_eos_drains_data_then_signals_eof():
    rb = PcmRingBuffer()
    rb.push(b"final word")
    rb.mark_eos()
    # Data still queued → first pop returns it.
    assert rb.pop(20) == b"final word"
    # Buffer drained → next pop signals EOF.
    assert rb.pop(20) == b""


def test_reset_clears_buffer_and_eos():
    rb = PcmRingBuffer()
    rb.push(b"abc")
    rb.mark_eos()
    rb.reset()
    assert rb.bytes_buffered() == 0
    # After reset, EOS is OFF → underrun returns silence (not EOF).
    assert rb.pop(5) == b"\x00" * 5


def test_push_empty_bytes_is_no_op():
    rb = PcmRingBuffer()
    rb.push(b"")
    assert rb.bytes_buffered() == 0
    assert rb.bytes_pushed() == 0


def test_push_then_peek_buffered():
    rb = PcmRingBuffer()
    assert rb.bytes_buffered() == 0
    rb.push(b"abc")
    assert rb.bytes_buffered() == 3
    rb.push(b"wx")
    assert rb.bytes_buffered() == 5
    rb.pop(4)
    assert rb.bytes_buffered() == 1


def test_is_eos_reflects_state():
    rb = PcmRingBuffer()
    assert rb.is_eos() is False
    rb.mark_eos()
    assert rb.is_eos() is True
    rb.reset()
    assert rb.is_eos() is False


def test_mark_eos_is_idempotent():
    rb = PcmRingBuffer()
    rb.mark_eos()
    rb.mark_eos()
    assert rb.is_eos() is True


def test_large_chunks_dont_drop_bytes():
    """Push a big chunk, pop in small chunks; total bytes must match."""
    rb = PcmRingBuffer()
    payload = bytes(range(256)) * 100   # 25.6 kB
    rb.push(payload)
    out = bytearray()
    while True:
        chunk = rb.pop(137)             # awkward read size to exercise splitting
        if not chunk and rb.is_eos():
            break
        if not chunk:
            # Not eos; underrun (shouldn't happen here, but be safe).
            break
        out.extend(chunk)
    assert bytes(out) == payload


# ----- Thread-safety -----------------------------------------------------

def test_concurrent_push_and_pop_balanced():
    """500 push + 500 pop operations on different threads must not lose bytes.

    Each push is a 64-byte payload, each pop a 32-byte request. We start
    a writer thread and two reader threads, then join with a small
    timeout. The invariant we care about is: total consumed ≤ total
    pushed AND no exception is raised. Bytes that haven't been consumed
    are still in the buffer (we don't assert pop() == N bytes total
    because timing matters).
    """
    rb = PcmRingBuffer()
    PUSH_COUNT = 500
    payload = b"A" * 64
    push_done = threading.Event()
    stop_readers = threading.Event()
    exceptions: list = []

    def writer():
        try:
            for _ in range(PUSH_COUNT):
                rb.push(payload)
        except Exception as e:  # noqa: BLE001
            exceptions.append(("writer", e))

    def reader():
        try:
            while not push_done.is_set() or rb.bytes_buffered() > 0:
                if stop_readers.is_set() and rb.bytes_buffered() == 0:
                    break
                rb.pop(32)
        except Exception as e:  # noqa: BLE001
            exceptions.append(("reader", e))

    writer_t = threading.Thread(target=writer)
    reader1 = threading.Thread(target=reader)
    reader2 = threading.Thread(target=reader)
    writer_t.start()
    reader1.start()
    reader2.start()
    writer_t.join(timeout=2.0)
    push_done.set()
    reader1.join(timeout=2.0)
    reader2.join(timeout=2.0)

    assert not exceptions, exceptions
    assert not writer_t.is_alive()
    assert not reader1.is_alive()
    assert not reader2.is_alive()
    assert rb.bytes_pushed() == PUSH_COUNT * 64
    # Consumed never exceeds pushed, and the remainder is what's
    # left in the buffer.
    assert rb.bytes_consumed() <= rb.bytes_pushed()
    assert rb.bytes_consumed() + rb.bytes_buffered() == rb.bytes_pushed()


# ===========================================================================
# PySide6-touching components — guarded by skip
# ===========================================================================

@pytest.fixture
def qio_or_skip():
    try:
        from PySide6.QtCore import QIODevice  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed; Qt-binding tests skipped.")
    yield


def test_streaming_device_is_sequential(qio_or_skip):
    """QAudioSink requires a sequential device for push-mode streaming."""
    from kokoro_studio.streaming import StreamingPcmDevice
    rb = PcmRingBuffer()
    dev = StreamingPcmDevice(rb)
    assert dev.isSequential() is True


def test_streaming_device_readdata_routes_to_ring(qio_or_skip):
    from kokoro_studio.streaming import StreamingPcmDevice
    rb = PcmRingBuffer()
    rb.push(b"abcdef")
    dev = StreamingPcmDevice(rb)
    # Split from middle.
    assert dev.readData(3) == b"abc"
    assert dev.readData(3) == b"def"
    # Empty pop on underrun → silence (NOT empty, would end QAudioSink).
    assert dev.readData(4) == b"\x00" * 4


def test_streaming_device_readdata_signals_eof(qio_or_skip):
    from kokoro_studio.streaming import StreamingPcmDevice
    rb = PcmRingBuffer()
    rb.push(b"end")
    rb.mark_eos()
    dev = StreamingPcmDevice(rb)
    assert dev.readData(10) == b"end"
    # Drained + EOS → empty bytes signals end of file.
    assert dev.readData(10) == b""


def test_make_kokoro_audio_format(qio_or_skip):
    from PySide6.QtMultimedia import QAudioFormat
    from kokoro_studio.streaming import make_kokoro_audio_format
    fmt = make_kokoro_audio_format()
    assert fmt is not None
    assert fmt.sampleRate() == 24000
    assert fmt.channelCount() == 1
    # Int16 (not Float) — Qt6's WASAPI/MediaFoundation backend won't
    # negotiate Float32 PCM with most Windows audio endpoints, so the
    # streaming sink uses the universally-supported Int16 PCM contract.
    assert fmt.sampleFormat() == QAudioFormat.SampleFormat.Int16


def test_make_audio_format_custom_args(qio_or_skip):
    from kokoro_studio.streaming import make_kokoro_audio_format
    # Build an exotic 48 kHz stereo format for testing argument plumbing.
    fmt = make_kokoro_audio_format(sample_rate=48000, channels=2)
    assert fmt is not None
    assert fmt.sampleRate() == 48000
    assert fmt.channelCount() == 2




def test_audio_availability_is_at_least_callable(qio_or_skip):
    """`default_audio_output_is_available` must run without crashing.

    On a real desktop QtMultimedia is present and the function returns
    True/False depending on the hardware. On CI without audio
    hardware, it gracefully returns False (or True with a stub
    device). We only assert the call completed.
    """
    from kokoro_studio.streaming import default_audio_output_is_available
    result = default_audio_output_is_available()
    assert isinstance(result, bool)
