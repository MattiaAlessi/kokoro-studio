# -*- coding: utf-8 -*-
"""Unit tests for the Kokoro Studio API server module.

These tests cover:

1.  ``_resolve_voice()`` — resolution order, OpenAI aliases, case-insensitive,
    unknown voice errors.
2.  ``_resolve_format()`` — valid / invalid format mapping.
3.  ``_build_audio_response()`` — PCM path (no file I/O), metadata headers.
4.  GET endpoints — ``/health``, ``/v1/voices``, ``/v1/models`` (all
    lightweight, no model loading required beyond import).
5.  POST ``/v1/audio/speech`` — validation errors only (bad voice, bad format,
    missing input, long text, bad speed, unknown model).  Actual synthesis
    requires the Kokoro model and is tested via the separate integration test
    (``test_api_server.py`` at the project root).

All tests in this file are **fast** — they import but do NOT run the Kokoro
model.  The ``app`` fixture uses ``TestClient`` from FastAPI.
"""

from __future__ import annotations

from typing import Generator

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# A small valid numpy array (float32, mono, ~0.25 s at 24 kHz) for
# _build_audio_response tests.  We use a real-looking WAV-sized array so
# the PCM path returns plausible content.
_SAMPLE_AUDIO = np.zeros(6000, dtype=np.float32)
_SAMPLE_AUDIO[::100] = 0.5  # Add some non-zero content
_SAMPLE_AUDIO[::101] = -0.3


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """Return a TestClient for the FastAPI app.

    The app is imported here (not at module level) so that test collection
    doesn't trigger the Kokoro import cascade.
    """
    from kokoro_studio.api_server import app
    with TestClient(app) as c:
        yield c


# ===================================================================
# _resolve_voice tests
# ===================================================================


def test_resolve_voice_direct_builtin() -> None:
    """A direct Kokoro voice name is returned as-is."""
    from kokoro_studio.api_server import _resolve_voice
    assert _resolve_voice("af_heart") == "af_heart"
    assert _resolve_voice("am_onyx") == "am_onyx"
    assert _resolve_voice("bm_fable") == "bm_fable"


def test_resolve_voice_openai_alias() -> None:
    """OpenAI-compatible voice names map to Kokoro built-ins."""
    from kokoro_studio.api_server import _resolve_voice
    assert _resolve_voice("alloy") == "af_alloy"
    assert _resolve_voice("echo") == "am_echo"
    assert _resolve_voice("fable") == "bm_fable"
    assert _resolve_voice("nova") == "af_nova"
    assert _resolve_voice("onyx") == "am_onyx"
    assert _resolve_voice("shimmer") == "af_sky"


def test_resolve_voice_openai_alias_case_insensitive() -> None:
    """OpenAI aliases are case-insensitive."""
    from kokoro_studio.api_server import _resolve_voice
    assert _resolve_voice("ALLOY") == "af_alloy"
    assert _resolve_voice("Echo") == "am_echo"
    assert _resolve_voice("ONYX") == "am_onyx"


def test_resolve_voice_builtin_case_insensitive() -> None:
    """Built-in voice names are matched case-insensitively."""
    from kokoro_studio.api_server import _resolve_voice
    assert _resolve_voice("AF_HEART") == "af_heart"
    assert _resolve_voice("Am_Onyx") == "am_onyx"
    assert _resolve_voice("BM_FABLE") == "bm_fable"


def test_resolve_voice_unknown_raises_http_400() -> None:
    """An unknown voice name raises HTTPException with status 400."""
    from kokoro_studio.api_server import _resolve_voice
    with pytest.raises(HTTPException) as exc_info:
        _resolve_voice("nonexistent_voice_xyz")
    assert exc_info.value.status_code == 400
    assert "Unknown voice" in exc_info.value.detail


def test_resolve_voice_empty_string_raises_400() -> None:
    """An empty voice name also raises 400 (won't match anything)."""
    from kokoro_studio.api_server import _resolve_voice
    with pytest.raises(HTTPException) as exc_info:
        _resolve_voice("")
    assert exc_info.value.status_code == 400


def test_resolve_voice_special_chars_raises_400() -> None:
    """A name with special characters raises 400."""
    from kokoro_studio.api_server import _resolve_voice
    with pytest.raises(HTTPException) as exc_info:
        _resolve_voice("voice!@#")
    assert exc_info.value.status_code == 400


# ===================================================================
# _resolve_format tests
# ===================================================================


def test_resolve_format_valid() -> None:
    """Known formats are mapped to the correct engine format."""
    from kokoro_studio.api_server import _resolve_format
    assert _resolve_format("wav") == "wav"
    assert _resolve_format("mp3") == "mp3"
    assert _resolve_format("flac") == "flac"
    assert _resolve_format("ogg") == "ogg"
    assert _resolve_format("pcm") == "pcm"
    assert _resolve_format("opus") == "ogg"  # fallback


def test_resolve_format_case_insensitive() -> None:
    """Format names are case-insensitive."""
    from kokoro_studio.api_server import _resolve_format
    assert _resolve_format("WAV") == "wav"
    assert _resolve_format("MP3") == "mp3"
    assert _resolve_format("Flac") == "flac"
    assert _resolve_format("OGG") == "ogg"


def test_resolve_format_strips_whitespace() -> None:
    """Leading/trailing whitespace is stripped."""
    from kokoro_studio.api_server import _resolve_format
    assert _resolve_format("  wav  ") == "wav"
    assert _resolve_format("  mp3  ") == "mp3"


def test_resolve_format_unknown_raises_400() -> None:
    """An unsupported format raises HTTPException with status 400."""
    from kokoro_studio.api_server import _resolve_format
    with pytest.raises(HTTPException) as exc_info:
        _resolve_format("aiff")
    assert exc_info.value.status_code == 400
    assert "Unsupported response_format" in exc_info.value.detail


# ===================================================================
# _build_audio_response tests
# ===================================================================


def test_build_response_pcm_returns_raw_float32() -> None:
    """The PCM path returns raw float32 bytes with the correct media type."""
    from kokoro_studio.api_server import _build_audio_response
    resp = _build_audio_response(_SAMPLE_AUDIO, "pcm", "pcm")
    assert resp.status_code == 200
    assert resp.media_type == "audio/L16;rate=24000;channels=1"
    body = resp.body
    assert len(body) == _SAMPLE_AUDIO.nbytes
    # Should decode back to float32
    decoded = np.frombuffer(body, dtype=np.float32)
    assert np.allclose(decoded, _SAMPLE_AUDIO)


def test_build_response_pcm_has_content_disposition() -> None:
    """PCM response includes a Content-Disposition header."""
    from kokoro_studio.api_server import _build_audio_response
    resp = _build_audio_response(_SAMPLE_AUDIO, "pcm", "pcm")
    assert "Content-Disposition" in resp.headers


# ===================================================================
# GET endpoint tests (lightweight, no model required)
# ===================================================================


class TestGetEndpoints:
    """Tests for GET endpoints that don't need the Kokoro model."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert data["engine"] == "Kokoro-82M"
        assert isinstance(data["voices"], int)
        assert data["voices"] > 0  # at least some voices

    def test_voices_returns_all_voices(self, client: TestClient) -> None:
        resp = client.get("/v1/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert "voices" in data
        assert len(data["voices"]) > 0
        # Each voice should have required fields
        for v in data["voices"][:5]:
            assert "voice" in v
            assert "description" in v
            assert "language" in v
            assert "gender" in v
            assert v["gender"] in ("female", "male")

    def test_voices_has_openai_compatible_mapping(self, client: TestClient) -> None:
        """Voices with OpenAI equivalents have the mapping filled in."""
        resp = client.get("/v1/voices")
        data = resp.json()
        alloy_entry = [v for v in data["voices"] if v["voice"] == "af_alloy"]
        assert len(alloy_entry) == 1
        assert alloy_entry[0]["openai_compatible"] == "alloy"

    def test_models_returns_list(self, client: TestClient) -> None:
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) > 0
        # First model should be the main TTS model
        assert data["data"][0]["id"] == "kokoro-82m"
        assert data["data"][0]["capabilities"]["tts"] is True

    def test_models_includes_voice_models(self, client: TestClient) -> None:
        """The models endpoint lists voice-specific models."""
        resp = client.get("/v1/models")
        data = resp.json()
        voice_ids = [m["id"] for m in data["data"]]
        assert any("kokoro-82m/" in vid for vid in voice_ids)


# ===================================================================
# POST /v1/audio/speech validation tests
# ===================================================================


class TestPostSpeechValidation:
    """Validation tests for the speech endpoint.

    These tests verify that invalid requests return 400 *before* the
    Kokoro model is invoked.  Actual synthesis is tested separately.
    """

    def test_missing_input_returns_400(self, client: TestClient) -> None:
        resp = client.post("/v1/audio/speech", json={})
        assert resp.status_code == 400
        assert "input is required" in resp.json()["detail"].lower()

    def test_empty_input_returns_400(self, client: TestClient) -> None:
        resp = client.post("/v1/audio/speech", json={"input": ""})
        assert resp.status_code == 400

    def test_blank_input_returns_400(self, client: TestClient) -> None:
        resp = client.post("/v1/audio/speech", json={"input": "   "})
        assert resp.status_code == 400

    def test_input_too_long_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "x" * 5000, "voice": "af_heart"},
        )
        assert resp.status_code == 400
        assert "4096" in resp.json()["detail"]

    def test_unknown_voice_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "totally_fake_voice_42"},
        )
        assert resp.status_code == 400
        assert "unknown voice" in resp.json()["detail"].lower()

    def test_unsupported_format_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "af_heart",
                  "response_format": "aiff"},
        )
        assert resp.status_code == 400
        assert "unsupported response_format" in resp.json()["detail"].lower()

    def test_speed_too_low_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "af_heart", "speed": 0.1},
        )
        assert resp.status_code == 400
        assert "speed" in resp.json()["detail"].lower()

    def test_speed_too_high_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "af_heart", "speed": 5.0},
        )
        assert resp.status_code == 400

    def test_invalid_speed_type_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "af_heart", "speed": "fast"},
        )
        assert resp.status_code == 400

    def test_unknown_model_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "af_heart",
                  "model": "turbo-tts-9000"},
        )
        assert resp.status_code == 400
        assert "unknown model" in resp.json()["detail"].lower()

    def test_openai_tts1_model_accepted(self, client: TestClient) -> None:
        """OpenAI model names like 'tts-1' are accepted."""
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "af_heart",
                  "model": "tts-1"},
        )
        # Should NOT be 400 (model is valid) — will be 500 if synthesis
        # isn't available, or 200 if it works.
        assert resp.status_code != 400

    def test_openai_gpt4o_mini_tts_model_accepted(self, client: TestClient) -> None:
        """The gpt-4o-mini-tts model name is accepted."""
        resp = client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "af_heart",
                  "model": "gpt-4o-mini-tts"},
        )
        # Valid model — expect either 200 or 500 (synthesis may or may not work)
        assert resp.status_code != 400


# ===================================================================
# Edge case tests for the api_server module constants
# ===================================================================


def test_openai_models_set_contains_expected() -> None:
    """The _OPENAI_MODELS set should contain all expected model names."""
    from kokoro_studio.api_server import _OPENAI_MODELS
    expected = {"tts-1", "tts-1-hd", "gpt-4o-mini-tts", "kokoro-82m", "kokoro"}
    for m in expected:
        assert m in _OPENAI_MODELS, f"missing model: {m}"


def test_response_formats_contain_all_expected() -> None:
    """All response formats should be mappable to engine formats."""
    from kokoro_studio.api_server import _RESPONSE_FORMATS
    assert "wav" in _RESPONSE_FORMATS
    assert "mp3" in _RESPONSE_FORMATS
    assert "flac" in _RESPONSE_FORMATS
    assert "ogg" in _RESPONSE_FORMATS
    assert "pcm" in _RESPONSE_FORMATS
    # opus falls back to ogg
    assert "opus" in _RESPONSE_FORMATS
    assert _RESPONSE_FORMATS["opus"] == "ogg"


def test_mime_types_cover_all_formats() -> None:
    """Every response format has a corresponding MIME type."""
    from kokoro_studio.api_server import _RESPONSE_FORMATS, _MIME_TYPES
    for fmt in _RESPONSE_FORMATS:
        engine_fmt = _RESPONSE_FORMATS[fmt]
        assert engine_fmt in _MIME_TYPES, f"missing MIME for {fmt} -> {engine_fmt}"


def test_kokoro_to_openai_reverse_mapping() -> None:
    """The reverse mapping (Kokoro → OpenAI) should be consistent."""
    from kokoro_studio.api_server import _OPENAI_TO_KOKORO, _KOKORO_TO_OPENAI
    for openai_name, kokoro_name in _OPENAI_TO_KOKORO.items():
        assert _KOKORO_TO_OPENAI[kokoro_name] == openai_name


# ===================================================================
# Server parser tests
# ===================================================================


class TestServerParser:
    """Tests for the CLI argument parser for the 'serve' subcommand."""

    def test_create_server_parser_adds_port(self) -> None:
        import argparse
        from kokoro_studio.api_server import create_server_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        serve_parser = subparsers.add_parser("serve")
        create_server_parser(serve_parser)

        ns = parser.parse_args(["serve", "--port", "9999", "--host", "0.0.0.0"])
        assert ns.port == 9999
        assert ns.host == "0.0.0.0"

    def test_create_server_parser_defaults(self) -> None:
        import argparse
        from kokoro_studio.api_server import create_server_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        serve_parser = subparsers.add_parser("serve")
        create_server_parser(serve_parser)

        ns = parser.parse_args(["serve"])
        assert ns.port == 8000
        assert ns.host == "127.0.0.1"
        assert ns.reload is False
        assert ns.workers == 1
