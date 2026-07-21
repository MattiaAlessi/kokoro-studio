# -*- coding: utf-8 -*-
"""Tests for ``kokoro_studio.audio_processing``.

Pure-Python module without Qt or kokoro.  Coverage:

  * ``PostProcessingParams`` dataclass: defaults, validation, bounds.
  * Individual processors: ``trim_silence``, ``apply_volume``,
    ``fade_in``, ``fade_out``, ``normalize_peak``, ``normalize_loudness``.
  * ``apply_all``: full pipeline with various combinations.
  * Edge cases: empty array, all-silence, very short audio, already-
    normalised content, dBFS > 0 rejection.
  * ``default_processing_params``: returns sensible defaults.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kokoro_studio.audio_processing import (
    PostProcessingParams,
    apply_all,
    apply_volume,
    default_processing_params,
    fade_in,
    fade_out,
    normalize_loudness,
    normalize_peak,
    trim_silence,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def sine_audio() -> np.ndarray:
    """A 1-second sine tone at 440 Hz, float32 mono @ 24 kHz."""
    t = np.linspace(0.0, 1.0, 24000, endpoint=False, dtype=np.float32)
    return 0.5 * np.sin(2.0 * np.pi * 440.0 * t).astype(np.float32)


@pytest.fixture
def silent_audio() -> np.ndarray:
    """1 second of pure silence."""
    return np.zeros(24000, dtype=np.float32)


@pytest.fixture
def short_audio() -> np.ndarray:
    """A 10-sample array."""
    return np.array([0.1, 0.2, 0.3, 0.2, 0.1, -0.1, -0.2, -0.3, -0.2, -0.1],
                    dtype=np.float32)


# ===================================================================
# PostProcessingParams
# ===================================================================

def test_params_defaults() -> None:
    p = PostProcessingParams()
    assert p.trim_silence is True
    assert p.trim_threshold_db == -40.0
    assert p.trim_min_silence_len == 100
    assert p.volume_enabled is False
    assert p.volume_gain_db == 0.0
    assert p.fade_enabled is False
    assert p.fade_in_duration_s == pytest.approx(0.005)
    assert p.fade_out_duration_s == pytest.approx(0.005)
    assert p.normalize_enabled is False
    assert p.normalize_mode == "peak"
    assert p.normalize_target_db == pytest.approx(-1.0)


def test_params_is_frozen() -> None:
    p = PostProcessingParams()
    with pytest.raises((AttributeError, Exception)):
        p.volume_enabled = True  # type: ignore[misc]


def test_params_peak_target_must_be_non_positive() -> None:
    with pytest.raises(ValueError, match="must be <= 0"):
        PostProcessingParams(normalize_enabled=True, normalize_mode="peak",
                             normalize_target_db=6.0)


def test_params_peak_target_negative_is_ok() -> None:
    p = PostProcessingParams(normalize_enabled=True, normalize_mode="peak",
                             normalize_target_db=-3.0)
    assert p.normalize_target_db == -3.0


def test_params_peak_target_zero_is_ok() -> None:
    p = PostProcessingParams(normalize_enabled=True, normalize_mode="peak",
                             normalize_target_db=0.0)
    assert p.normalize_target_db == 0.0


def test_params_invalid_normalize_mode() -> None:
    with pytest.raises(ValueError, match="must be 'peak' or 'loudness'"):
        PostProcessingParams(normalize_enabled=True, normalize_mode="rms")


def test_params_volume_gain_bounds() -> None:
    with pytest.raises(ValueError, match="must be in"):
        PostProcessingParams(volume_enabled=True, volume_gain_db=30.0)
    with pytest.raises(ValueError, match="must be in"):
        PostProcessingParams(volume_enabled=True, volume_gain_db=-30.0)


def test_params_volume_gain_valid() -> None:
    p = PostProcessingParams(volume_enabled=True, volume_gain_db=6.0)
    assert p.volume_gain_db == 6.0


def test_params_trim_threshold_must_be_non_positive() -> None:
    with pytest.raises(ValueError, match="must be <= 0"):
        PostProcessingParams(trim_silence=True, trim_threshold_db=10.0)


def test_params_trim_min_silence_len_must_be_positive() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        PostProcessingParams(trim_silence=True, trim_min_silence_len=0)


def test_params_fade_duration_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        PostProcessingParams(fade_enabled=True, fade_in_duration_s=-0.1)


# ===================================================================
# default_processing_params
# ===================================================================

def test_default_processing_params() -> None:
    p = default_processing_params()
    assert p.trim_silence is True
    assert p.volume_enabled is False
    assert p.fade_enabled is False
    assert p.normalize_enabled is False


# ===================================================================
# Utility: _as_float32_mono (indirectly through processors)
# ===================================================================

def test_processors_accept_2d_mono(sine_audio: np.ndarray) -> None:
    """2-D shape (n, 1) must be handled transparently."""
    two_d = sine_audio.reshape(-1, 1)
    result = trim_silence(two_d)
    assert result.ndim == 1
    assert np.allclose(result, sine_audio)


def test_processors_reject_2d_stereo() -> None:
    """2-D shape (n, 2) must raise."""
    stereo = np.zeros((100, 2), dtype=np.float32)
    with pytest.raises(ValueError, match="must be 1-D"):
        trim_silence(stereo)


# ===================================================================
# trim_silence
# ===================================================================

def test_trim_silence_no_trim_needed(sine_audio: np.ndarray) -> None:
    """Audio with no leading/trailing silence should be unchanged."""
    result = trim_silence(sine_audio, threshold_db=-60)
    assert len(result) == len(sine_audio)
    assert np.allclose(result, sine_audio)


def test_trim_silence_removes_leading_zeros() -> None:
    audio = np.concatenate([
        np.zeros(500, dtype=np.float32),
        np.ones(1000, dtype=np.float32) * 0.5,
    ])
    result = trim_silence(audio, threshold_db=-60, min_silence_len=200)
    assert len(result) == 1000


def test_trim_silence_removes_trailing_zeros() -> None:
    audio = np.concatenate([
        np.ones(1000, dtype=np.float32) * 0.5,
        np.zeros(500, dtype=np.float32),
    ])
    result = trim_silence(audio, threshold_db=-60, min_silence_len=200)
    assert len(result) == 1000


def test_trim_silence_removes_both_ends() -> None:
    audio = np.concatenate([
        np.zeros(300, dtype=np.float32),
        np.ones(1000, dtype=np.float32) * 0.5,
        np.zeros(300, dtype=np.float32),
    ])
    result = trim_silence(audio, threshold_db=-60, min_silence_len=200)
    assert len(result) == 1000


def test_trim_silence_preserves_interior_silence() -> None:
    """Silence gaps in the middle must not be removed."""
    audio = np.concatenate([
        np.ones(500, dtype=np.float32) * 0.5,
        np.zeros(200, dtype=np.float32),   # interior gap
        np.ones(500, dtype=np.float32) * 0.5,
    ])
    result = trim_silence(audio, threshold_db=-60, min_silence_len=100)
    assert len(result) == 1200  # 500 + 200 + 500


def test_trim_silence_all_silence_returns_empty() -> None:
    audio = np.zeros(1000, dtype=np.float32)
    result = trim_silence(audio, threshold_db=-60, min_silence_len=10)
    assert len(result) == 0


def test_trim_silence_empty_returns_empty() -> None:
    audio = np.array([], dtype=np.float32)
    result = trim_silence(audio)
    assert len(result) == 0


def test_trim_silence_preserves_short_silence_gap_at_edge() -> None:
    """A silence gap shorter than min_silence_len at the edge must be
    preserved (don't eat into the content)."""
    audio = np.concatenate([
        np.zeros(50, dtype=np.float32),    # short leading silence
        np.ones(500, dtype=np.float32) * 0.5,
    ])
    result = trim_silence(audio, threshold_db=-60, min_silence_len=200)
    # 50 < 200, so it should NOT be trimmed
    assert len(result) == 550


# ===================================================================
# apply_volume
# ===================================================================

def test_apply_volume_zero_gain_is_identity(sine_audio: np.ndarray) -> None:
    result = apply_volume(sine_audio, gain_db=0.0)
    assert np.allclose(result, sine_audio)


def test_apply_volume_boost(sine_audio: np.ndarray) -> None:
    result = apply_volume(sine_audio, gain_db=6.0)
    expected = sine_audio * (10.0 ** (6.0 / 20.0))
    assert np.allclose(result, expected)


def test_apply_volume_cut(sine_audio: np.ndarray) -> None:
    result = apply_volume(sine_audio, gain_db=-6.0)
    expected = sine_audio * (10.0 ** (-6.0 / 20.0))
    assert np.allclose(result, expected)


def test_apply_volume_clamps_gain() -> None:
    audio = np.array([0.5], dtype=np.float32)
    result = apply_volume(audio, gain_db=50.0)  # beyond max
    expected = audio * (10.0 ** (24.0 / 20.0))  # clamped to 24 dB
    assert np.allclose(result, expected)


# ===================================================================
# fade_in
# ===================================================================

def test_fade_in_zero_duration_is_identity(sine_audio: np.ndarray) -> None:
    result = fade_in(sine_audio, duration_s=0.0)
    assert np.allclose(result, sine_audio)


def test_fade_in_shape(sine_audio: np.ndarray) -> None:
    result = fade_in(sine_audio, duration_s=0.01, sample_rate=24000)
    assert len(result) == len(sine_audio)
    # First sample should be ~0
    assert abs(result[0]) < 0.001
    # Last sample should be unchanged
    assert abs(result[-1] - sine_audio[-1]) < 0.001


def test_fade_in_exact_samples(short_audio: np.ndarray) -> None:
    """Fade first 3 samples linearly."""
    result = fade_in(short_audio, duration_s=0.001, sample_rate=24000)
    # 0.001 * 24000 = 24 samples — but our audio is only 10 samples long
    assert len(result) == 10


def test_fade_in_all_silence_returns_silence(silent_audio: np.ndarray) -> None:
    result = fade_in(silent_audio)
    assert np.allclose(result, 0.0)


# ===================================================================
# fade_out
# ===================================================================

def test_fade_out_zero_duration_is_identity(sine_audio: np.ndarray) -> None:
    result = fade_out(sine_audio, duration_s=0.0)
    assert np.allclose(result, sine_audio)


def test_fade_out_shape(sine_audio: np.ndarray) -> None:
    result = fade_out(sine_audio, duration_s=0.01, sample_rate=24000)
    assert len(result) == len(sine_audio)
    # Last sample should be ~0
    assert abs(result[-1]) < 0.001
    # First sample should be unchanged
    assert abs(result[0] - sine_audio[0]) < 0.001


def test_fade_out_exact_samples(short_audio: np.ndarray) -> None:
    result = fade_out(short_audio, duration_s=0.001, sample_rate=24000)
    assert len(result) == len(short_audio)


# ===================================================================
# normalize_peak
# ===================================================================

def test_normalize_peak_sine(sine_audio: np.ndarray) -> None:
    result = normalize_peak(sine_audio, target_db=-3.0)
    peak = float(np.max(np.abs(result)))
    peak_db = 20.0 * np.log10(peak)
    assert peak_db == pytest.approx(-3.0, abs=0.5)


def test_normalize_peak_already_at_target() -> None:
    """Peak is exactly -3 dBFS; normalise to -3 dBFS → no change."""
    peak = 10.0 ** (-3.0 / 20.0)  # ~0.7079
    audio = np.ones(1000, dtype=np.float32) * peak
    result = normalize_peak(audio, target_db=-3.0)
    assert np.allclose(result, audio)


def test_normalize_peak_silent_audio(silent_audio: np.ndarray) -> None:
    result = normalize_peak(silent_audio, target_db=-1.0)
    assert np.allclose(result, 0.0)


def test_normalize_peak_zero_target_ok(sine_audio: np.ndarray) -> None:
    """0 dBFS target means peak exactly at 1.0."""
    result = normalize_peak(sine_audio, target_db=0.0)
    assert float(np.max(np.abs(result))) == pytest.approx(1.0, abs=0.01)


# ===================================================================
# normalize_loudness
# ===================================================================

def test_normalize_loudness_sine(sine_audio: np.ndarray) -> None:
    result = normalize_loudness(sine_audio, target_dbfs=-20.0)
    rms = float(np.sqrt(np.mean(result.astype(np.float64) ** 2)))
    rms_db = 20.0 * np.log10(rms / 1.0)
    assert rms_db == pytest.approx(-20.0, abs=0.5)


def test_normalize_loudness_already_at_target() -> None:
    """RMS is exactly -16 dBFS; target -16 → no change."""
    # RMS of a constant signal = its amplitude.
    # 20 * log10(rms) = -16  →  rms = 10^(-16/20) ≈ 0.1585
    rms_target = 10.0 ** (-16.0 / 20.0)
    audio = np.ones(1000, dtype=np.float32) * rms_target
    result = normalize_loudness(audio, target_dbfs=-16.0)
    assert np.allclose(result, audio)


def test_normalize_loudness_silent_audio(silent_audio: np.ndarray) -> None:
    result = normalize_loudness(silent_audio, target_dbfs=-16.0)
    assert np.allclose(result, 0.0)


# ===================================================================
# apply_all (full pipeline)
# ===================================================================

def test_apply_all_empty_params(sine_audio: np.ndarray) -> None:
    """apply_all with all-default params (trim_silence only, which is a
    no-op on a pure tone with no silence)."""
    params = PostProcessingParams(
        trim_silence=True,
        volume_enabled=False,
        fade_enabled=False,
        normalize_enabled=False,
    )
    result = apply_all(sine_audio, params)
    assert len(result) == len(sine_audio)
    assert np.allclose(result, sine_audio)


def test_apply_all_trim_volume_normalize() -> None:
    """Test a multi-stage pipeline: trim → boost → peak-normalise."""
    audio = np.concatenate([
        np.zeros(500, dtype=np.float32),
        np.ones(1000, dtype=np.float32) * 0.25,
        np.zeros(500, dtype=np.float32),
    ])
    params = PostProcessingParams(
        trim_silence=True,
        trim_threshold_db=-60,
        trim_min_silence_len=200,
        volume_enabled=True,
        volume_gain_db=6.0,  # 6 dB boost → 0.25 * 2 = 0.5
        normalize_enabled=True,
        normalize_mode="peak",
        normalize_target_db=-3.0,
    )
    result = apply_all(audio, params)
    # After trim: 1000 samples
    assert len(result) == 1000
    # After boost: 0.5 peak; after peak normalise to -3 dBFS
    expected_peak = 10.0 ** (-3.0 / 20.0)
    assert float(np.max(np.abs(result))) == pytest.approx(expected_peak, abs=0.01)


def test_apply_all_full_pipeline() -> None:
    """Test ALL stages enabled together."""
    audio = np.concatenate([
        np.zeros(500, dtype=np.float32),
        np.ones(2000, dtype=np.float32) * 0.3,
        np.zeros(500, dtype=np.float32),
    ])
    params = PostProcessingParams(
        trim_silence=True,
        trim_threshold_db=-60,
        trim_min_silence_len=200,
        volume_enabled=True,
        volume_gain_db=3.0,
        fade_enabled=True,
        fade_in_duration_s=0.005,
        fade_out_duration_s=0.005,
        normalize_enabled=True,
        normalize_mode="peak",
        normalize_target_db=-2.0,
    )
    result = apply_all(audio, params)
    assert len(result) == 2000  # trimmed
    assert result[0] < result[500]  # fade-in ramp
    assert result[-1] < result[-500]  # fade-out ramp
    expected_peak = 10.0 ** (-2.0 / 20.0)
    assert float(np.max(np.abs(result))) == pytest.approx(expected_peak, abs=0.02)


def test_apply_all_empty_audio() -> None:
    params = PostProcessingParams(trim_silence=True)
    result = apply_all(np.array([], dtype=np.float32), params)
    assert len(result) == 0


def test_apply_all_all_silence(silent_audio: np.ndarray) -> None:
    """All-silence with trim_silence enabled should return empty."""
    params = PostProcessingParams(trim_silence=True)
    result = apply_all(silent_audio, params)
    assert len(result) == 0


def test_apply_all_volume_only(sine_audio: np.ndarray) -> None:
    params = PostProcessingParams(
        trim_silence=False,
        volume_enabled=True,
        volume_gain_db=-12.0,
    )
    result = apply_all(sine_audio, params)
    expected = sine_audio * (10.0 ** (-12.0 / 20.0))
    assert np.allclose(result, expected)


def test_apply_all_normalize_loudness() -> None:
    audio = np.ones(1000, dtype=np.float32) * 0.5
    params = PostProcessingParams(
        trim_silence=False,
        normalize_enabled=True,
        normalize_mode="loudness",
        normalize_target_db=-18.0,
    )
    result = apply_all(audio, params)
    rms = float(np.sqrt(np.mean(result.astype(np.float64) ** 2)))
    rms_db = 20.0 * np.log10(rms / 1.0)
    assert rms_db == pytest.approx(-18.0, abs=0.5)


def test_apply_all_fade_only() -> None:
    audio = np.ones(4800, dtype=np.float32)  # 0.2 s @ 24 kHz
    params = PostProcessingParams(
        trim_silence=False,
        fade_enabled=True,
        fade_in_duration_s=0.1,
        fade_out_duration_s=0.1,
    )
    result = apply_all(audio, params)
    assert len(result) == 4800
    # 0.1 s @ 24 kHz = 2400 samples for each fade
    fade_len = 2400
    # Fade in: first sample ~0, last fade-in sample < 1.0
    assert result[0] == pytest.approx(0.0, abs=0.001)
    assert result[fade_len - 1] == pytest.approx(1.0, abs=0.01)
    # Fade out: last sample ~0, first fade-out sample < 1.0
    assert result[-1] == pytest.approx(0.0, abs=0.001)
    assert result[-fade_len] == pytest.approx(1.0, abs=0.01)


# ===================================================================
# Edge cases & robustness
# ===================================================================

def test_normalize_peak_low_amplitude() -> None:
    """Very low amplitude should be boosted without NaN or Inf."""
    audio = np.array([1e-10, 2e-10, 3e-10], dtype=np.float32)
    result = normalize_peak(audio, target_db=-1.0)
    assert not np.any(np.isnan(result))
    assert not np.any(np.isinf(result))
    assert float(np.max(np.abs(result))) > 0.0


def test_trim_silence_custom_threshold() -> None:
    """Different thresholds produce different trim results."""
    audio = np.concatenate([
        np.zeros(200, dtype=np.float32),
        np.ones(500, dtype=np.float32) * 0.01,   # ~-40 dBFS
        np.ones(500, dtype=np.float32) * 0.5,     # ~-6 dBFS
    ])
    # threshold_db=-80 dBFS  →  threshold_abs = 1e-4 = 0.0001
    # 0.01 > 0.0001 → NOT silence, 0.5 > 0.0001 → NOT silence
    result_permissive = trim_silence(audio, threshold_db=-80, min_silence_len=50)
    # threshold_db=-12 dBFS  →  threshold_abs ≈ 0.251
    # 0.01 < 0.251 → silence, 0.5 > 0.251 → NOT silence
    result_aggressive = trim_silence(audio, threshold_db=-12, min_silence_len=50)
    # Permissive: only trims the 200 zeros → length = 1000
    assert len(result_permissive) == 1000
    # Aggressive: trims zeros (200) + 0.01 region (500) → length = 500
    assert len(result_aggressive) == 500


def test_fade_in_longer_than_audio() -> None:
    """Fade duration longer than audio should clip to audio length."""
    audio = np.ones(100, dtype=np.float32)
    result = fade_in(audio, duration_s=1.0, sample_rate=100)
    assert len(result) == 100
    # Last sample should be close to 1.0 (fade clipped to audio length)
    assert result[-1] == pytest.approx(1.0, abs=0.01)


def test_fade_out_longer_than_audio() -> None:
    """Fade duration longer than audio should clip to audio length."""
    audio = np.ones(100, dtype=np.float32)
    result = fade_out(audio, duration_s=1.0, sample_rate=100)
    assert len(result) == 100
    assert result[0] == pytest.approx(1.0, abs=0.01)


def test_apply_all_custom_sample_rate() -> None:
    """apply_all should accept and forward sample_rate for fade calcs."""
    audio = np.ones(4800, dtype=np.float32)  # 0.1 s @ 48 kHz
    params = PostProcessingParams(
        trim_silence=False,
        fade_enabled=True,
        fade_in_duration_s=0.05,
    )
    result = apply_all(audio, params, sample_rate=48000)
    # 0.05 s * 48000 = 2400 samples
    assert len(result) == 4800
    assert result[0] < 0.01
    assert result[2400] > 0.99
