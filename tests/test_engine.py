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
    """All historical positional args must remain in their original positions.

    New params (multi_speaker, speaker_gap_s for Phase 2 Multi-Speaker
    Dialogue Mode) are appended AFTER pronunciation_rules and don't
    shift any existing positional index — calling code that uses the
    original 10 positional args keeps working unchanged.
    """
    params = list(inspect.signature(engine.generate_speech).parameters)
    expected_historical = [
        "text", "voice", "lang_code", "output_path", "speed",
        "split_pattern", "on_chunk", "stop_check", "output_format",
        "pronunciation_rules",
    ]
    assert params[:len(expected_historical)] == expected_historical
    # New phase-2 additions (last in the signature).
    assert "multi_speaker" in params, "multi_speaker kwarg missing"
    assert "speaker_gap_s" in params, "speaker_gap_s kwarg missing"
    assert params[params.index("multi_speaker")] == "multi_speaker"
    assert params.index("multi_speaker") > params.index("pronunciation_rules")


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


# ---------------------------------------------------------------------------
# _prime_voice_into_pipeline (Phase 2 - Voice Blending lazy-load workaround)
# ---------------------------------------------------------------------------
#
# Kokoro's KPipeline.voices dict is populated lazily on the first synthesis
# call. Without these priming helpers, `compute_blend_tensor` would raise
# "voice_a 'af_heart' is not loaded in the current pipeline" when the user
# creates a blend using a voice that hasn't been synthesised yet. We mock
# the pipeline here so these tests don't depend on the ~300 MB Kokoro
# acoustic model being installed.

from typing import Dict, Iterator, Tuple  # noqa: E402


class _FakeKokoroPipe:
    """Minimal stand-in for `kokoro.KPipeline` used by the prime tests.

    Mirrors Kokoro's lazy-voice contract:
      * `.voices` starts empty.
      * Each successful call (`__call__(text='a', voice=X)`) adds `X`
        to `.voices` (mirrors `KPipeline.load_voice`).
      * Yields at least one chunk so the prime-helper's
        `for _ in pipe(...): break` iterates without hanging.
    """

    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.voices: Dict[str, object] = {}
        self._raise = raise_on_call
        self.call_count = 0

    def __call__(
        self,
        text: str,
        *,
        voice: str,
        **kwargs: object,
    ) -> Iterator[Tuple[str, str, str]]:
        self.call_count += 1
        if self._raise:
            raise RuntimeError(f"Fake pipeline error for voice {voice!r}")
        if voice not in self.voices:
            self.voices[voice] = object()  # stand-in tensor; tests only check presence
        yield ("graphemes", "phonemes", "audio")


class _NoVoicesPipe:
    """Pipeline that doesn't expose `.voices` at all (defensive code path)."""

    def __call__(
        self,
        text: str,
        *,
        voice: str,
        **kwargs: object,
    ) -> Iterator[Tuple[str, str, str]]:
        yield ("g", "p", "a")


@pytest.fixture
def fake_pipe(engine):
    """Inject a clean FakeKokoroPipe for lang='a'; reset `_pipelines` after."""
    saved = dict(engine._pipelines)
    engine._pipelines.clear()
    pipe = _FakeKokoroPipe()
    engine._pipelines["a"] = pipe
    try:
        yield pipe
    finally:
        engine._pipelines.clear()
        engine._pipelines.update(saved)


def test_prime_voice_into_pipeline_no_op_when_already_loaded(engine, fake_pipe):
    """Idempotent: an already-loaded voice short-circuits without synthesis."""
    fake_pipe.voices["af_heart"] = "preloaded-tensor"
    ok = engine._prime_voice_into_pipeline("a", "af_heart")
    assert ok is True
    assert fake_pipe.voices["af_heart"] == "preloaded-tensor"
    assert fake_pipe.call_count == 0, "prime must not synthesise for loaded voices"


def test_prime_voice_into_pipeline_lazy_loads_missing_voice(engine, fake_pipe):
    """A voice NOT in `.voices` is materialised by a one-tick synthesis."""
    assert "af_heart" not in fake_pipe.voices
    ok = engine._prime_voice_into_pipeline("a", "af_heart")
    assert ok is True
    assert "af_heart" in fake_pipe.voices
    assert fake_pipe.call_count == 1, "expected exactly one pipe() invocation"


def test_prime_voice_into_pipeline_is_idempotent_across_calls(engine, fake_pipe):
    """Two consecutive prime calls should only synthesise once total."""
    engine._prime_voice_into_pipeline("a", "af_heart")
    engine._prime_voice_into_pipeline("a", "af_heart")
    assert fake_pipe.call_count == 1


def test_prime_voice_into_pipeline_returns_false_on_synth_failure(engine):
    """When pipe() raises (e.g. unknown voice), prime returns False cleanly
    so the caller's downstream KeyError surfaces the precise reason."""
    saved = dict(engine._pipelines)
    engine._pipelines.clear()
    pipe = _FakeKokoroPipe(raise_on_call=True)
    engine._pipelines["a"] = pipe
    try:
        ok = engine._prime_voice_into_pipeline("a", "af_heart")
        assert ok is False
        assert pipe.call_count == 1
    finally:
        engine._pipelines.clear()
        engine._pipelines.update(saved)


def test_prime_voice_into_pipeline_returns_false_without_voices_attr(engine):
    """Pipeline that doesn't expose `.voices` (defensive path) returns False
    instead of crashing on the membership check."""
    saved = dict(engine._pipelines)
    engine._pipelines.clear()
    engine._pipelines["a"] = _NoVoicesPipe()
    try:
        ok = engine._prime_voice_into_pipeline("a", "af_heart")
        assert ok is False
    finally:
        engine._pipelines.clear()
        engine._pipelines.update(saved)


def test_prime_voice_into_pipeline_invalid_lang_raises(engine):
    """Unknown `lang_code` propagates the canonical ValueError from
    `_get_pipeline`, since we can't prime what we can't look up."""
    with pytest.raises(ValueError, match="lang_code"):
        engine._prime_voice_into_pipeline("zz", "af_heart")
