# -*- coding: utf-8 -*-
"""Background synthesis worker for the Kokoro Studio GUI."""

from __future__ import annotations

import time
from typing import Mapping, Optional

import numpy as np

from PySide6.QtCore import QObject, QThread, Signal

from kokoro_studio.blending import VoiceBlend
from kokoro_studio.engine import SAMPLE_RATE, generate_speech


class SynthesisWorker(QThread):
    """Runs `generate_speech()` off the GUI thread.

    Signals (consumed on the GUI thread):
        progress(int, int, float, float)
            Emitted after every chunk Kokoro produces.
        chunk_ready(int, int, object)
            Carries (segment_idx, chunk_idx, audio_chunk).
        segment_started(int)
            Fired once per segment transition.
        finished_ok(str path, float duration_seconds, object audio_array)
            Final audio has been written to `path`.
        failed(str error_msg)
            Engine raised; nothing was written.

    Set `request_stop()` (from any thread) to cancel cleanly.
    """

    progress = Signal(int, int, float, float)
    chunk_ready = Signal(int, int, object)
    segment_started = Signal(int)
    finished_ok = Signal(str, float, object)
    failed = Signal(str)

    _EMPIRICAL_CHARS_PER_AUDIO_SEC = 13.0
    _ETA_MIN_WARMUP_S = 0.5
    _ETA_MIN_CHUNKS = 2

    def __init__(
        self,
        text: str,
        voice: str,
        speed: float,
        output_path: str,
        output_format: str,
        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        blends: Optional[Mapping[str, VoiceBlend]] = None,
        parent: Optional[QObject] = None,
        apply_ssml: bool = False,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._voice = voice
        self._speed = speed
        self._output_path = output_path
        self._output_format = output_format
        self._pronunciation_rules = (
            dict(pronunciation_rules) if pronunciation_rules else None
        )
        self._multi_speaker = multi_speaker
        self._speaker_gap_s = speaker_gap_s
        self._blends: Optional[dict] = (
            dict(blends) if blends else None
        )
        self._apply_ssml = bool(apply_ssml)
        self._last_seg_idx: int = -1
        self._cumulative_chunk_count: int = 0
        self._stop_requested = False
        self._cumulative_samples = 0
        self._synth_start_time: Optional[float] = None

    def request_stop(self) -> None:
        self._stop_requested = True

    def _stop_check(self) -> bool:
        return self._stop_requested

    def _on_chunk(self, seg_idx: int, chunk_idx: int, audio_chunk: np.ndarray) -> None:
        self._cumulative_samples += len(audio_chunk)
        cum_seconds = self._cumulative_samples / SAMPLE_RATE

        now = time.monotonic()
        if self._synth_start_time is None:
            self._synth_start_time = now
        elapsed_wallclock = now - self._synth_start_time

        eta_seconds = -1.0
        if (elapsed_wallclock >= self._ETA_MIN_WARMUP_S
                and (self._cumulative_chunk_count + 1) >= self._ETA_MIN_CHUNKS):
            rate = cum_seconds / elapsed_wallclock
            if rate > 0.0:
                est_total_audio = len(self._text) / self._EMPIRICAL_CHARS_PER_AUDIO_SEC
                remaining_audio = max(0.0, est_total_audio - cum_seconds)
                eta_seconds = remaining_audio / rate

        self._cumulative_chunk_count += 1
        self.progress.emit(
            self._cumulative_chunk_count,
            self._cumulative_chunk_count,
            cum_seconds,
            eta_seconds,
        )
        if seg_idx != self._last_seg_idx:
            self._last_seg_idx = seg_idx
            self.segment_started.emit(seg_idx)
        self.chunk_ready.emit(seg_idx, chunk_idx, audio_chunk)

    def run(self) -> None:
        self._cumulative_samples = 0
        self._cumulative_chunk_count = 0
        self._last_seg_idx = -1
        try:
            audio = generate_speech(
                text=self._text,
                voice=self._voice,
                speed=self._speed,
                output_path=self._output_path,
                output_format=self._output_format,
                pronunciation_rules=self._pronunciation_rules,
                multi_speaker=self._multi_speaker,
                speaker_gap_s=self._speaker_gap_s,
                on_chunk=self._on_chunk,
                stop_check=self._stop_check,
                blends=self._blends,
                apply_ssml=self._apply_ssml,
            )
            if self._stop_requested:
                self.failed.emit("Generation stopped by user (no file written).")
                return
            duration = len(audio) / SAMPLE_RATE
            self.finished_ok.emit(self._output_path, duration, audio)
        except ImportError as e:
            msg = str(e).strip() or "Unknown import."
            missing = getattr(e, "name", "") or ""
            if "lameenc" in missing or "lameenc" in msg.lower():
                install_hint = "pip install lameenc"
            else:
                install_hint = "pip install kokoro soundfile numpy"
            self.failed.emit(
                f"Missing dependency: {msg}\n\nRun:  {install_hint}"
            )
        except RuntimeError as e:
            if "cancelled" in str(e).lower():
                self.failed.emit("Generation cancelled.")
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
