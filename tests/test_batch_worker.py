# -*- coding: utf-8 -*-
"""Tests for `kokoro_studio.gui.batch_worker`.

These tests cover the dataclasses and worker logic in isolation.
The BatchWorker spawns a real QThread so it needs PySide6; for pure-data
tests we skip the worker and test the dataclasses directly.

Coverage:

  * `BatchQueueItem` dataclass: fields, defaults.
  * `BatchItemResult` dataclass: success / failure shapes.
  * `BatchSummary` dataclass: aggregation fields.
  * `BatchWorker` construction (no actual synthesis — the worker is
    meant to be run with a real kokoro backend on the user's machine).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kokoro_studio.gui.batch_worker import (
    BatchItemResult,
    BatchQueueItem,
    BatchSummary,
)


# ===================================================================
# BatchQueueItem
# ===================================================================

def test_batch_queue_item_all_fields() -> None:
    item = BatchQueueItem(
        text="Hello world",
        voice="af_heart",
        speed=1.0,
        output_path="/tmp/test.wav",
        output_format="wav",
        label="my label",
    )
    assert item.text == "Hello world"
    assert item.voice == "af_heart"
    assert item.speed == 1.0
    assert item.output_path == "/tmp/test.wav"
    assert item.output_format == "wav"
    assert item.label == "my label"


def test_batch_queue_item_default_label_is_empty() -> None:
    item = BatchQueueItem(
        text="test",
        voice="af_bella",
        speed=0.8,
        output_path="/tmp/x.wav",
        output_format="wav",
    )
    assert item.label == ""


def test_batch_queue_item_is_frozen() -> None:
    item = BatchQueueItem(
        text="t", voice="v", speed=1.0,
        output_path="/t.wav", output_format="wav",
    )
    with pytest.raises((AttributeError, Exception)):
        item.text = "changed"  # type: ignore[misc]


def test_batch_queue_item_speed_zero_point_five() -> None:
    """Confirm that low speed values are accepted (engine validates)."""
    item = BatchQueueItem(
        text="slow", voice="af_heart", speed=0.5,
        output_path="/s.wav", output_format="wav",
    )
    assert item.speed == 0.5


def test_batch_queue_item_non_wav_format() -> None:
    item = BatchQueueItem(
        text="test", voice="v", speed=1.0,
        output_path="/x.mp3", output_format="mp3",
    )
    assert item.output_format == "mp3"
    assert item.output_path.endswith(".mp3")


# ===================================================================
# BatchItemResult
# ===================================================================

def test_batch_item_result_success() -> None:
    item = BatchQueueItem(
        text="test", voice="v", speed=1.0,
        output_path="/t.wav", output_format="wav",
    )
    result = BatchItemResult(item=item, duration_s=3.5, success=True)
    assert result.item is item
    assert result.duration_s == 3.5
    assert result.success is True
    assert result.error_msg == ""


def test_batch_item_result_failure() -> None:
    item = BatchQueueItem(
        text="test", voice="v", speed=1.0,
        output_path="/t.wav", output_format="wav",
    )
    result = BatchItemResult(
        item=item, duration_s=0.0, success=False,
        error_msg="Synthesis error: something broke",
    )
    assert result.success is False
    assert result.duration_s == 0.0
    assert "something broke" in result.error_msg


def test_batch_item_result_is_frozen() -> None:
    item = BatchQueueItem(
        text="t", voice="v", speed=1.0,
        output_path="/t.wav", output_format="wav",
    )
    result = BatchItemResult(item=item, duration_s=1.0, success=True)
    with pytest.raises((AttributeError, Exception)):
        result.duration_s = 2.0  # type: ignore[misc]


# ===================================================================
# BatchSummary
# ===================================================================

def test_batch_summary_all_zero() -> None:
    s = BatchSummary(
        total=0, succeeded=0, failed=0,
        total_audio_duration_s=0.0, elapsed_s=0.0,
    )
    assert s.total == 0
    assert s.succeeded == 0
    assert s.failed == 0
    assert s.total_audio_duration_s == 0.0
    assert s.elapsed_s == 0.0


def test_batch_summary_mixed() -> None:
    s = BatchSummary(
        total=10, succeeded=7, failed=3,
        total_audio_duration_s=45.2, elapsed_s=120.5,
    )
    assert s.succeeded == 7
    assert s.failed == 3
    assert s.succeeded + s.failed == s.total
    assert s.total_audio_duration_s == 45.2
    assert s.elapsed_s == 120.5


def test_batch_summary_is_frozen() -> None:
    s = BatchSummary(
        total=1, succeeded=1, failed=0,
        total_audio_duration_s=5.0, elapsed_s=10.0,
    )
    with pytest.raises((AttributeError, Exception)):
        s.total = 2  # type: ignore[misc]


# ===================================================================
# Construction examples (no actual synthesis run)
# ===================================================================

def test_empty_item_list_allows_construction() -> None:
    """A BatchWorker with an empty item list should build without error."""
    pytest.importorskip("PySide6")
    from kokoro_studio.gui.batch_worker import BatchWorker
    worker = BatchWorker(items=[])
    assert worker is not None
    assert not worker.isRunning()


def test_batch_worker_default_params() -> None:
    """Default parameters should be sensible."""
    pytest.importorskip("PySide6")
    from kokoro_studio.gui.batch_worker import BatchWorker
    item = BatchQueueItem(
        text="hello", voice="af_heart", speed=1.0,
        output_path="/t.wav", output_format="wav",
    )
    worker = BatchWorker(items=[item])
    assert worker._multi_speaker is False
    assert worker._speaker_gap_s == 0.25
    assert worker._apply_ssml is False
    assert worker._pronunciation_rules is None
    assert worker._blends is None


def test_batch_worker_request_stop_sets_flag() -> None:
    """Calling request_stop() before start() should set the flag."""
    pytest.importorskip("PySide6")
    from kokoro_studio.gui.batch_worker import BatchWorker
    worker = BatchWorker(items=[])
    assert worker._stop_requested is False
    worker.request_stop()
    assert worker._stop_requested is True
