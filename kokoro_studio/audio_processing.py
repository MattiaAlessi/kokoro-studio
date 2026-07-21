# -*- coding: utf-8 -*-
"""Audio Post-Processing for Kokoro Studio.

Phase 3 — "Audio Post-Processing".  Pure-DSP operations applied to the
final float32 mono audio array *before* it is written to disk or handed
to the streaming sink.  All functions operate on ``np.ndarray`` with
dtype ``float32`` and shape ``(n,)`` (mono) — the engine normalises its
output to this shape before calling any processor.

Processing order (applied by ``apply_all``):
    1. ✂️ Silence trim (leading + trailing)
    2. 📈 Volume boost/cut  (dB)
    3. 🌀 Fade in
    4. 🌅 Fade out
    5. ⚡ Normalization (peak or loudness, whichever is enabled)

Public API:
    PostProcessingParams
        Frozen dataclass carrying all post-processing knobs.  Boolean
        flags enable/disable each stage; the ``apply_all`` helper checks
        them in the order above.

    trim_silence(audio, threshold_db, min_silence_len)        -> np.ndarray
    apply_volume(audio, gain_db)                              -> np.ndarray
    fade_in(audio, duration_s, sample_rate)                   -> np.ndarray
    fade_out(audio, duration_s, sample_rate)                  -> np.ndarray
    normalize_peak(audio, target_db)                          -> np.ndarray
    normalize_loudness(audio, target_dbfs)                    -> np.ndarray
    apply_all(audio, params, sample_rate=24000)               -> np.ndarray

This module has ZERO PySide6 / Kokoro dependencies, so it can be
unit-tested in CI and reused from CLI / batch mode without Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default sample rate for Kokoro output (24 kHz).  Used as fallback when
# the caller doesn't pass an explicit sample_rate to ``apply_all``.
_DEFAULT_SAMPLE_RATE: int = 24000

# Hard floor to avoid log(0) in dB conversions.  Keeps silent regions
# from producing -inf dBFS.
_EPSILON: float = 1e-10

# Default silence threshold (dBFS).  Samples below this level are
# considered silence for trimming purposes.  -40 dBFS is aggressive
# enough to remove quiet hiss without chewing into the speech.
_DEFAULT_TRIM_THRESHOLD_DB: float = -40.0

# Minimum silence run length (in samples) for trimming.  Shorter runs
# are preserved to avoid erasing natural pauses within speech.
_DEFAULT_TRIM_MIN_SAMPLES: int = 100

# Default fade duration (seconds).  5 ms is imperceptible at 24 kHz
# but prevents click/pop transients on loop boundaries.
_DEFAULT_FADE_S: float = 0.005

# Default target peak (dBFS) for peak normalisation.
# -1.0 dBFS leaves a 1 dB headroom margin to avoid hard clipping in
# downstream codecs (MP3 / OGG Vorbis can overshoot on reconstruction).
_DEFAULT_PEAK_TARGET_DB: float = -1.0

# Default target level (dBFS) for simple RMS loudness normalisation.
# -16 dBFS is a reasonable level for speech content (ITU-R BS.1770-4
# integrated LUFS target for dialogue is around -16 LKFS).
_DEFAULT_LOUDNESS_TARGET_DBFS: float = -16.0

# Clamp gain to ±24 dB to prevent accidental deafening / silence.
_GAIN_DB_MIN: float = -24.0
_GAIN_DB_MAX: float = 24.0


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PostProcessingParams:
    """All knobs for the audio post-processing pipeline.

    Attributes:
        trim_silence:        If True, remove silence below
                             ``trim_threshold_db`` from the start and end
                             of the audio.  Default True.
        trim_threshold_db:   Silence threshold in dBFS.  Only meaningful
                             when ``trim_silence=True``.  Default -40.
        trim_min_silence_len: Minimum silence run (samples) to remove.
                             Default 100 (~4 ms @ 24 kHz).

        volume_enabled:      If True, apply a fixed gain boost/cut.
                             Default False.
        volume_gain_db:      Gain in dB (-24 .. +24).  Default 0.

        fade_enabled:        If True, apply fade-in and/or fade-out.
                             Default False.
        fade_in_duration_s:  Fade-in duration in seconds.  Default 0.005.
        fade_out_duration_s: Fade-out duration in seconds.  Default 0.005.

        normalize_enabled:   If True, normalise the audio after all other
                             processing.  Default False.
        normalize_mode:      ``'peak'`` (default) or ``'loudness'``.
        normalize_target_db: Target level in dBFS (peak) or dBFS (RMS).
                             Default -1.0 for peak, -16.0 for loudness.
    """

    # Silence trimming
    trim_silence: bool = True
    trim_threshold_db: float = _DEFAULT_TRIM_THRESHOLD_DB
    trim_min_silence_len: int = _DEFAULT_TRIM_MIN_SAMPLES

    # Volume boost / cut
    volume_enabled: bool = False
    volume_gain_db: float = 0.0

    # Fade in / out
    fade_enabled: bool = False
    fade_in_duration_s: float = _DEFAULT_FADE_S
    fade_out_duration_s: float = _DEFAULT_FADE_S

    # Normalisation (peak or loudness)
    normalize_enabled: bool = False
    normalize_mode: str = "peak"  # "peak" | "loudness"
    normalize_target_db: float = _DEFAULT_PEAK_TARGET_DB

    def __post_init__(self) -> None:
        """Validate bounds on initialisation."""
        # Trim threshold
        if self.trim_silence:
            if not isinstance(self.trim_threshold_db, (int, float)):
                raise ValueError(
                    f"trim_threshold_db must be a number, "
                    f"got {self.trim_threshold_db!r}"
                )
            if self.trim_threshold_db > 0.0:
                raise ValueError(
                    f"trim_threshold_db must be <= 0 dBFS, "
                    f"got {self.trim_threshold_db}"
                )
            if not isinstance(self.trim_min_silence_len, int) or self.trim_min_silence_len < 1:
                raise ValueError(
                    f"trim_min_silence_len must be >= 1, "
                    f"got {self.trim_min_silence_len!r}"
                )

        # Volume gain
        if self.volume_enabled:
            if not isinstance(self.volume_gain_db, (int, float)):
                raise ValueError(
                    f"volume_gain_db must be a number, "
                    f"got {self.volume_gain_db!r}"
                )
            if not (_GAIN_DB_MIN <= self.volume_gain_db <= _GAIN_DB_MAX):
                raise ValueError(
                    f"volume_gain_db must be in [{_GAIN_DB_MIN}, {_GAIN_DB_MAX}], "
                    f"got {self.volume_gain_db}"
                )

        # Fade durations
        if self.fade_enabled:
            for name, val in [
                ("fade_in_duration_s", self.fade_in_duration_s),
                ("fade_out_duration_s", self.fade_out_duration_s),
            ]:
                if not isinstance(val, (int, float)) or val < 0.0:
                    raise ValueError(
                        f"{name} must be >= 0, got {val!r}"
                    )

        # Normalisation
        if self.normalize_enabled:
            if self.normalize_mode not in ("peak", "loudness"):
                raise ValueError(
                    f"normalize_mode must be 'peak' or 'loudness', "
                    f"got {self.normalize_mode!r}"
                )
            if not isinstance(self.normalize_target_db, (int, float)):
                raise ValueError(
                    f"normalize_target_db must be a number, "
                    f"got {self.normalize_target_db!r}"
                )
            if self.normalize_mode == "peak" and self.normalize_target_db > 0.0:
                raise ValueError(
                    f"Peak normalize_target_db must be <= 0 dBFS, "
                    f"got {self.normalize_target_db}"
                )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _as_float32_mono(audio: np.ndarray) -> np.ndarray:
    """Coerce *audio* to 1-D float32 mono."""
    a = np.asarray(audio, dtype=np.float32)
    if a.ndim == 2 and a.shape[1] == 1:
        a = a.reshape(-1)
    elif a.ndim == 2 and a.shape[0] == 1:
        a = a.reshape(-1)
    elif a.ndim != 1:
        raise ValueError(
            f"audio must be 1-D mono (got shape {a.shape})"
        )
    return a


def _rms_db(audio: np.ndarray) -> float:
    """Return the RMS level of *audio* in dBFS."""
    rms = np.sqrt(np.mean(audio.astype(np.float64) ** 2))
    if rms < _EPSILON:
        return -96.0  # practical noise floor
    return float(20.0 * np.log10(rms / 1.0))


def _peak_db(audio: np.ndarray) -> float:
    """Return the peak level of *audio* in dBFS."""
    peak = float(np.max(np.abs(audio)))
    if peak < _EPSILON:
        return -96.0
    return float(20.0 * np.log10(peak / 1.0))


# ---------------------------------------------------------------------------
# Individual processors
# ---------------------------------------------------------------------------

def trim_silence(
    audio: np.ndarray,
    threshold_db: float = _DEFAULT_TRIM_THRESHOLD_DB,
    min_silence_len: int = _DEFAULT_TRIM_MIN_SAMPLES,
) -> np.ndarray:
    """Remove leading and trailing silence from *audio*.

    A sample is considered silence if its absolute value (converted to
    dBFS) is below *threshold_db*.  Only runs of at least
    *min_silence_len* contiguous silence samples at the start or end
    are removed; interior silence is preserved to keep natural pauses.

    Args:
        audio:           1-D float32 audio array.
        threshold_db:    Silence threshold in dBFS (e.g. -40).
        min_silence_len: Minimum number of contiguous samples to treat
                         as silence for trimming.

    Returns:
        Trimmed copy of *audio* (always a new array, never a view).
    """
    a = _as_float32_mono(audio)
    if len(a) == 0:
        return a.copy()

    threshold_abs = 10.0 ** (threshold_db / 20.0)
    above = np.abs(a) > threshold_abs

    # Handle all-silence: return empty.
    if not np.any(above):
        return np.array([], dtype=np.float32)

    # Find first non-silent index.
    first_nonzero = int(np.argmax(above))
    # Find last non-silent index (search from end).
    rev_above = above[::-1]
    last_nonzero = len(a) - int(np.argmax(rev_above))

    # Only trim if the gap is >= min_silence_len.
    start = first_nonzero if first_nonzero >= min_silence_len else 0
    end = last_nonzero if (len(a) - last_nonzero) >= min_silence_len else len(a)

    return a[start:end].copy()


def apply_volume(
    audio: np.ndarray,
    gain_db: float = 0.0,
) -> np.ndarray:
    """Apply a fixed gain to *audio*.

    Args:
        audio:   1-D float32 audio array.
        gain_db: Gain in dB.  Positive = boost, negative = cut.
                 Clamped to [-24, +24] dB.

    Returns:
        Gain-scaled copy of *audio*.
    """
    a = _as_float32_mono(audio)
    gain_linear = 10.0 ** (float(np.clip(gain_db, _GAIN_DB_MIN, _GAIN_DB_MAX)) / 20.0)
    return (a.astype(np.float64) * gain_linear).astype(np.float32)


def fade_in(
    audio: np.ndarray,
    duration_s: float = _DEFAULT_FADE_S,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Apply a linear fade-in at the start of *audio*.

    Args:
        audio:       1-D float32 audio array.
        duration_s:  Fade duration in seconds.  Clipped to the audio
                     length.  Zero = no-op.
        sample_rate: Sample rate in Hz (default 24000).

    Returns:
        Faded copy of *audio*.
    """
    a = _as_float32_mono(audio)
    n_samples = min(len(a), max(0, int(round(duration_s * sample_rate))))
    if n_samples <= 0:
        return a.copy()
    window = np.linspace(0.0, 1.0, n_samples, dtype=np.float32)
    out = a.copy()
    out[:n_samples] *= window
    return out


def fade_out(
    audio: np.ndarray,
    duration_s: float = _DEFAULT_FADE_S,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Apply a linear fade-out at the end of *audio*.

    Args:
        audio:       1-D float32 audio array.
        duration_s:  Fade duration in seconds.  Clipped to the audio
                     length.  Zero = no-op.
        sample_rate: Sample rate in Hz (default 24000).

    Returns:
        Faded copy of *audio*.
    """
    a = _as_float32_mono(audio)
    n_samples = min(len(a), max(0, int(round(duration_s * sample_rate))))
    if n_samples <= 0:
        return a.copy()
    window = np.linspace(1.0, 0.0, n_samples, dtype=np.float32)
    out = a.copy()
    out[-n_samples:] *= window
    return out


def normalize_peak(
    audio: np.ndarray,
    target_db: float = _DEFAULT_PEAK_TARGET_DB,
) -> np.ndarray:
    """Peak-normalise *audio* so its maximum absolute value hits
    *target_db* dBFS.

    Args:
        audio:     1-D float32 audio array.
        target_db: Target peak level in dBFS (must be <= 0).  Default
                   -1.0 dBFS (1 dB headroom).

    Returns:
        Normalised copy of *audio*.  If the audio is completely silent,
        returns a copy unchanged.
    """
    a = _as_float32_mono(audio)
    peak = float(np.max(np.abs(a)))
    if peak < _EPSILON:
        return a.copy()
    current_db = 20.0 * np.log10(peak)
    gain_db = float(target_db) - current_db
    gain_linear = 10.0 ** (gain_db / 20.0)
    return (a.astype(np.float64) * gain_linear).astype(np.float32)


def normalize_loudness(
    audio: np.ndarray,
    target_dbfs: float = _DEFAULT_LOUDNESS_TARGET_DBFS,
) -> np.ndarray:
    """Simple RMS-based loudness normalisation.

    NOTE: This is NOT a full ITU-R BS.1770-4 LUFS measurement (no
    pre-filter, no gating).  It applies a broadband RMS gain to match
    *target_dbfs*.  This is acceptable for speech TTS output because
    the content is already relatively uniform (no extreme dynamic
    range like a Hollywood movie).  For a future phase we can replace
    this with ``pyloudnorm`` or ``scipy``-based gated loudness.

    Args:
        audio:       1-D float32 audio array.
        target_dbfs: Target RMS level in dBFS.  Default -16.0 dBFS.

    Returns:
        Loudness-normalised copy of *audio*.  Silent audio returns
        a copy unchanged.
    """
    a = _as_float32_mono(audio)
    rms = np.sqrt(np.mean(a.astype(np.float64) ** 2))
    if rms < _EPSILON:
        return a.copy()
    current_dbfs = 20.0 * np.log10(rms)
    gain_db = float(target_dbfs) - current_dbfs
    gain_linear = 10.0 ** (gain_db / 20.0)
    return (a.astype(np.float64) * gain_linear).astype(np.float32)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def apply_all(
    audio: np.ndarray,
    params: PostProcessingParams,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Run *audio* through the post-processing pipeline.

    Processing order:
        1. ✂️  Trim silence (leading / trailing)
        2. 📈  Volume boost / cut
        3. 🌀  Fade in
        4. 🌅  Fade out
        5. ⚡  Normalisation (peak or loudness, whichever is enabled)

    Args:
        audio:       1-D float32 mono audio array.
        params:      ``PostProcessingParams`` dataclass instance.
        sample_rate: Sample rate in Hz (default 24000).  Used by
                     fade-in / fade-out calculations.

    Returns:
        Processed copy of *audio* (always a fresh array).
    """
    a = _as_float32_mono(audio)
    if len(a) == 0:
        return a.copy()

    # 1. Trim silence
    if params.trim_silence:
        a = trim_silence(
            a,
            threshold_db=params.trim_threshold_db,
            min_silence_len=params.trim_min_silence_len,
        )
        if len(a) == 0:
            return a.copy()

    # 2. Volume boost / cut
    if params.volume_enabled:
        a = apply_volume(a, gain_db=params.volume_gain_db)

    # 3. Fade in
    if params.fade_enabled and params.fade_in_duration_s > 0.0:
        a = fade_in(a, duration_s=params.fade_in_duration_s, sample_rate=sample_rate)

    # 4. Fade out
    if params.fade_enabled and params.fade_out_duration_s > 0.0:
        a = fade_out(a, duration_s=params.fade_out_duration_s, sample_rate=sample_rate)

    # 5. Normalisation (peak or loudness)
    if params.normalize_enabled:
        if params.normalize_mode == "peak":
            a = normalize_peak(a, target_db=params.normalize_target_db)
        else:
            a = normalize_loudness(a, target_dbfs=params.normalize_target_db)

    return a


def default_processing_params() -> PostProcessingParams:
    """Return the default ``PostProcessingParams`` (trim silence only).

    This is a convenience factory so the GUI can instantiate one clean
    default and mutate it through the dialog.
    """
    return PostProcessingParams(
        trim_silence=True,
        trim_threshold_db=_DEFAULT_TRIM_THRESHOLD_DB,
        trim_min_silence_len=_DEFAULT_TRIM_MIN_SAMPLES,
        volume_enabled=False,
        volume_gain_db=0.0,
        fade_enabled=False,
        fade_in_duration_s=_DEFAULT_FADE_S,
        fade_out_duration_s=_DEFAULT_FADE_S,
        normalize_enabled=False,
        normalize_mode="peak",
        normalize_target_db=_DEFAULT_PEAK_TARGET_DB,
    )


# ---------------------------------------------------------------------------
# Public symbols
# ---------------------------------------------------------------------------

__all__ = [
    "PostProcessingParams",
    "trim_silence",
    "apply_volume",
    "fade_in",
    "fade_out",
    "normalize_peak",
    "normalize_loudness",
    "apply_all",
    "default_processing_params",
]
