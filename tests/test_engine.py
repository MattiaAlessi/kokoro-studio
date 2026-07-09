# -*- coding: utf-8 -*-
"""Smoke tests for `kokoro_studio.engine`.

These tests intentionally do NOT load the Kokoro acoustic model (which
would download ~300 MB on first run). They cover:

  * The public surface (`list_voices`, `get_voice_info`, `generate_speech`)
    is importable and signature-correct.
  * `save_audio` writes all four supported formats with sensible
    sizes and valid MP3 frame sync / ID3 magic.

For tests that actually synthesise audio, see `tests/test_synth.py`
(marked `slow` — not run by default).
"""

from __future__ import annotations

import importlib
import inspect
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    return importlib.import_module("kokoro_studio.engine")


@pytest.fixture
def sine_24k() -> np.ndarray:
    """0.3 s, 440 Hz float32 mono at 24 kHz — deterministic test signal."""
    sr = 24000
    t = np.linspace(0.0, 0.3, int(sr * 0.3), endpoint=False)
    rng = np.random.default_rng(0)
    audio = np.sin(2 * np.pi * 440 * t) + 0.01 * rng.standard_normal(t.shape)
    return audio.astype(np.float32)


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def test_engine_importable(engine):
    assert hasattr(engine, "list_voices")
    assert hasattr(engine, "get_voice_info")
    assert hasattr(engine, "generate_speech")
    assert hasattr(engine, "save_audio")


def test_constants_present(engine):
    assert engine.DEFAULT_VOICE == "af_heart"
    assert engine.SAMPLE_RATE == 24000
    assert engine.OUTPUT_FORMATS == ("wav", "mp3", "flac", "ogg")
    assert engine.MP3_BITRATE_KBPS == 192


def test_list_voices_returns_29_english_voices(engine):
    voices = engine.list_voices()
    assert len(voices) == 29
    assert engine.DEFAULT_VOICE in voices


def test_list_voices_filters_by_language(engine):
    assert engine.list_voices(lang="a")           # American English
    assert engine.list_voices(lang="b")           # British English
    assert engine.list_voices(lang="j") == []     # Japanese (no bundled voices)
    assert engine.list_voices(lang="z") == []     # Mandarin  (no bundled voices)
    assert engine.list_voices(lang="e") == []     # Spanish   (espeak-ng only)


def test_get_voice_info_known_voice(engine):
    info = engine.get_voice_info("af_heart")
    assert info["voice"]   == "af_heart"
    assert info["lang"]    == "a"
    assert info["gender"]  == "f"
    assert info["grade"]   == "A"


def test_get_voice_info_unknown_raises(engine):
    with pytest.raises(ValueError, match="not recognized"):
        engine.get_voice_info("xx_ghost")


# ---------------------------------------------------------------------------
# Signature stability
# ---------------------------------------------------------------------------

def test_generate_speech_signature_preserves_positional_compat(engine):
    """All historical positional args must remain positional-or-keyword."""
    params = list(inspect.signature(engine.generate_speech).parameters)
    # Critical: pronunciation_rules is the LAST parameter, after output_format.
    # This preserves positional backwards compat for any external caller
    # that may have used positional args.
    assert params[-1] == "pronunciation_rules", f"last param: {params[-1]}"
    assert params[-2] == "output_format", f"second-to-last: {params[-2]}"


def test_generate_speech_rejects_empty_text(engine):
    with pytest.raises(ValueError, match="non-empty"):
        engine.generate_speech(text="   ")


def test_generate_speech_rejects_bad_speed(engine):
    with pytest.raises(ValueError, match="speed"):
        engine.generate_speech(text="hi", speed=10.0)


# ---------------------------------------------------------------------------
# save_audio (multi-format export)
# ---------------------------------------------------------------------------

def test_save_audio_wav(engine, sine_24k):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.wav")
        engine.save_audio(sine_24k, path, output_format="wav")
        size = os.path.getsize(path)
        # 0.3 s @ 24 kHz float32 = 28800 bytes payload + 44-byte header.
        assert 28_000 < size < 30_000, f"unexpected WAV size: {size}"


def test_save_audio_flac(engine, sine_24k):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.flac")
        engine.save_audio(sine_24k, path, output_format="flac")
        size = os.path.getsize(path)
        # FLAC compresses to roughly 1/3 of float32.
        assert 1_000 < size < 20_000, f"unexpected FLAC size: {size}"


def test_save_audio_ogg(engine, sine_24k):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.ogg")
        engine.save_audio(sine_24k, path, output_format="ogg")
        size = os.path.getsize(path)
        # Vorbis is the most efficient of the bunch.
        assert 1_000 < size < 15_000, f"unexpected OGG size: {size}"


def test_save_audio_mp3(engine, sine_24k):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.mp3")
        engine.save_audio(sine_24k, path, output_format="mp3")
        size = os.path.getsize(path)
        data = Path(path).read_bytes()
        # MP3 must either start with an ID3v2 tag (`b'ID3'`) or a valid
        # MPEG audio frame sync (first byte 0xFF, second byte 0xE0+).
        is_id3 = data.startswith(b"ID3")
        is_sync = data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        assert is_id3 or is_sync, "MP3 file lacks valid signature"
        # 0.3 s @ 192 kbps ≈ 7200 bytes.
        assert 4_000 < size < 12_000, f"unexpected MP3 size: {size}"


def test_save_audio_format_inferred_from_extension(engine, sine_24k):
    """With output_format=None, the format should be inferred from the
    suffix. This is the legacy behaviour we promised not to break."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "inferred.ogg")
        engine.save_audio(sine_24k, path, output_format=None)
        # If this didn't crash AND the file is non-empty, inference worked.
        assert os.path.getsize(path) > 0


def test_save_audio_rejects_unknown_format(engine, sine_24k):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.xyz")
        with pytest.raises(ValueError, match="Unsupported"):
            engine.save_audio(sine_24k, path, output_format="xyz")


def test_save_audio_rejects_bad_shape(engine):
    """Non-mono audio should fail loudly, not silently flatten."""
    bad = np.zeros((2, 100), dtype=np.float32)  # 2 channels
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.wav")
        with pytest.raises(ValueError, match="1-D mono"):
            engine.save_audio(bad, path, output_format="wav")
