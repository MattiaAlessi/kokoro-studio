# -*- coding: utf-8 -*-
"""Tests for `kokoro_studio.blending`.

Pure-Python module without Qt, kokoro or numpy. Coverage:

  * `VoiceBlend` dataclass: alpha bounds, type coercion, frozenness.
  * `is_valid_blend_name`: regex shape, shared with dialogue markers.
  * `_coerce_to_blend`: 3-tuple / VoiceBlend / None / bad input.
  * `compute_blend_tensor`: formula, caching, missing-voice KeyError.
  * `clear_tensor_cache`: cache eviction.
  * `resolve_voice_param`: built-in name passthrough vs. blend tensor.
  * `save_blends` / `load_blends`: roundtrip, versioned schema,
    legacy flat-schema migration, malformed JSON, missing file,
    forward-compatible versions, partial-file skip, reserved-name
    collision rejection, parent directory auto-creation, invalid
    name rejection.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from kokoro_studio import blending as bld
from kokoro_studio.blending import (
    VoiceBlend,
    clear_tensor_cache,
    compute_blend_tensor,
    is_valid_blend_name,
    load_blends,
    resolve_voice_param,
    save_blends,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(autouse=True)
def _isolated_blend_cache():
    """Reset the module-level tensor cache between tests.

    The cache is keyed on (va, vb, alpha) and shared across tests; an
    unisolated cache would mask caching bugs (a hit from an earlier
    test could make a "first call" test pass spuriously).
    """
    clear_tensor_cache()
    yield
    clear_tensor_cache()


@pytest.fixture
def fake_voices() -> dict:
    """Two stand-in voice "tensors" — numpy float32 arrays.

    Kokoro's real `KPipeline.voices` returns torch.Tensor instances; we
    mirror the supported-arithmetic contract (`alpha * t + (1.0 - alpha) * u`)
    with numpy arrays. Pure-Python lists do NOT support scalar-elementwise
    multiplication (`[1, 2, 3] * 0.5` repeats the list, it does not
    multiply element-wise), so we cannot use them here.
    """
    import numpy as np
    return {
        "af_bella": np.array([1.0, 0.0, 0.0], dtype=np.float32),  # 1 0 0
        "af_sarah": np.array([0.0, 1.0, 0.0], dtype=np.float32),  # 0 1 0
    }


# ===================================================================
# VoiceBlend dataclass
# ===================================================================

def test_voice_blend_accepts_valid_alpha():
    b = VoiceBlend(voice_a="af_bella", voice_b="af_sarah", alpha=0.5)
    assert b.voice_a == "af_bella"
    assert b.voice_b == "af_sarah"
    assert b.alpha == 0.5


def test_voice_blend_alpha_endpoints_valid():
    """alpha=0.0 and alpha=1.0 are degenerate but legal corners."""
    VoiceBlend("a", "b", 0.0)
    VoiceBlend("a", "b", 1.0)


def test_voice_blend_alpha_below_zero_rejected():
    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        VoiceBlend("a", "b", -0.01)


def test_voice_blend_alpha_above_one_rejected():
    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        VoiceBlend("a", "b", 1.01)


def test_voice_blend_non_numeric_alpha_rejected():
    with pytest.raises(ValueError):
        VoiceBlend("a", "b", "0.5")  # type: ignore[arg-type]


def test_voice_blend_bool_alpha_rejected():
    """bool is a subclass of int — the dataclass must reject it
    because True/False aren't meaningful blend weights."""
    with pytest.raises(ValueError):
        VoiceBlend("a", "b", True)  # type: ignore[arg-type]


def test_voice_blend_int_alpha_coerced_to_float():
    """An int alpha (e.g. 0 from JSON) must be coerced to float so
    downstream tensor arithmetic doesn't accidentally do int * tensor.
    """
    b = VoiceBlend("a", "b", 0)
    assert isinstance(b.alpha, float)
    assert b.alpha == 0.0


def test_voice_blend_is_frozen():
    b = VoiceBlend("a", "b", 0.5)
    with pytest.raises((AttributeError, Exception)):
        b.alpha = 0.7  # type: ignore[misc]


def test_voice_blend_rejects_non_string_voices():
    with pytest.raises(ValueError):
        VoiceBlend(123, "b", 0.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        VoiceBlend("a", None, 0.5)  # type: ignore[arg-type]


# ===================================================================
# is_valid_blend_name
# ===================================================================

@pytest.mark.parametrize("name", [
    "a", "af_bella", "_under", "X1", "Bella_Sarah_70",
    "abc_def_ghi_99", "z9", "_", "A_",
])
def test_is_valid_blend_name_accepts(name):
    assert is_valid_blend_name(name) is True


@pytest.mark.parametrize("name", [
    "1abc",         # leading digit
    "af-bella",     # hyphen
    "af.bella",     # dot
    "af bella",     # space
    "",             # empty
    "af_bella!",    # punctuation
    "af_bèlla",     # non-ASCII letter
    "af\tbella",    # tab
])
def test_is_valid_blend_name_rejects(name):
    assert is_valid_blend_name(name) is False


def test_is_valid_blend_name_rejects_non_string():
    assert is_valid_blend_name(None) is False  # type: ignore[arg-type]
    assert is_valid_blend_name(123) is False  # type: ignore[arg-type]


# ===================================================================
# _coerce_to_blend
# ===================================================================

def test_coerce_to_blend_none_passthrough():
    assert bld._coerce_to_blend(None) is None


def test_coerce_to_blend_dataclass_passthrough():
    b = VoiceBlend("a", "b", 0.5)
    assert bld._coerce_to_blend(b) is b


def test_coerce_to_blend_tuple_to_dataclass():
    out = bld._coerce_to_blend(("af_bella", "af_sarah", 0.7))
    assert isinstance(out, VoiceBlend)
    assert out.voice_a == "af_bella"
    assert out.voice_b == "af_sarah"
    assert out.alpha == 0.7


def test_coerce_to_blend_rejects_bad_input():
    with pytest.raises(ValueError):
        bld._coerce_to_blend("af_bella")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        bld._coerce_to_blend(["a", "b", 0.5])  # list, not tuple
    with pytest.raises(ValueError):
        bld._coerce_to_blend(("a", "b", 0.5, "extra"))  # 4-tuple


def test_coerce_to_blend_rejects_out_of_range_tuple():
    with pytest.raises(ValueError):
        bld._coerce_to_blend(("a", "b", 1.5))


# ===================================================================
# compute_blend_tensor
# ===================================================================

def test_compute_blend_tensor_pure_blend(fake_voices):
    """alpha=0.5 of [1,0,0] + 0.5 of [0,1,0] = [0.5, 0.5, 0]."""
    blend = VoiceBlend("af_bella", "af_sarah", 0.5)
    out = compute_blend_tensor(blend, fake_voices)
    import numpy as np
    assert np.allclose(out, [0.5, 0.5, 0.0])


def test_compute_blend_tensor_alpha_one_returns_a(fake_voices):
    """alpha=1.0 should reproduce voice_a exactly (linear interp endpoint)."""
    blend = VoiceBlend("af_bella", "af_sarah", 1.0)
    out = compute_blend_tensor(blend, fake_voices)
    import numpy as np
    assert np.allclose(out, [1.0, 0.0, 0.0])


def test_compute_blend_tensor_alpha_zero_returns_b(fake_voices):
    """alpha=0.0 should reproduce voice_b exactly (linear interp endpoint)."""
    blend = VoiceBlend("af_bella", "af_sarah", 0.0)
    out = compute_blend_tensor(blend, fake_voices)
    import numpy as np
    assert np.allclose(out, [0.0, 1.0, 0.0])


def test_compute_blend_tensor_caches_result(fake_voices):
    """A second call with the same (va, vb, alpha) MUST return the same
    object identity — confirms the cache hit (not just equality)."""
    blend = VoiceBlend("af_bella", "af_sarah", 0.5)
    first = compute_blend_tensor(blend, fake_voices)
    second = compute_blend_tensor(blend, fake_voices)
    assert first is second  # object identity — cache hit


def test_compute_blend_tensor_cache_alpha_rounded(fake_voices):
    """alpha=0.50001 and alpha=0.50002 should hit the same cache slot
    (alpha is rounded to 4 decimals before keying)."""
    a = compute_blend_tensor(VoiceBlend("af_bella", "af_sarah", 0.50001), fake_voices)
    b = compute_blend_tensor(VoiceBlend("af_bella", "af_sarah", 0.50002), fake_voices)
    # Same rounded key (0.5) → same cached object.
    assert a is b


def test_compute_blend_tensor_different_alpha_different_cache(fake_voices):
    """alpha=0.5 and alpha=0.6 must produce different cached entries."""
    a = compute_blend_tensor(VoiceBlend("af_bella", "af_sarah", 0.5), fake_voices)
    b = compute_blend_tensor(VoiceBlend("af_bella", "af_sarah", 0.6), fake_voices)
    assert a is not b
    assert not np.array_equal(a, b)


def test_compute_blend_tensor_missing_voice_a_raises(fake_voices):
    with pytest.raises(KeyError, match="voice_a"):
        compute_blend_tensor(
            VoiceBlend("xx_ghost", "af_sarah", 0.5), fake_voices,
        )


def test_compute_blend_tensor_missing_voice_b_raises(fake_voices):
    with pytest.raises(KeyError, match="voice_b"):
        compute_blend_tensor(
            VoiceBlend("af_bella", "xx_ghost", 0.5), fake_voices,
        )


def test_compute_blend_tensor_rejects_none_blend(fake_voices):
    with pytest.raises(ValueError, match="not be None"):
        compute_blend_tensor(None, fake_voices)  # type: ignore[arg-type]


def test_clear_tensor_cache_drops_entries(fake_voices):
    blend = VoiceBlend("af_bella", "af_sarah", 0.5)
    first = compute_blend_tensor(blend, fake_voices)
    clear_tensor_cache()
    second = compute_blend_tensor(blend, fake_voices)
    # After clear, the cache miss path produces a NEW object (equality
    # is preserved but identity changes).
    import numpy as np
    assert np.array_equal(first, second)
    assert first is not second


# ===================================================================
# resolve_voice_param
# ===================================================================

def test_resolve_voice_param_builtin_passthrough(fake_voices):
    """A name that isn't in `blends` is returned unchanged so the
    KPipeline resolves it as a built-in Kokoro voice."""
    out = resolve_voice_param("af_bella", {}, fake_voices)
    assert out == "af_bella"


def test_resolve_voice_param_blend_returns_tensor(fake_voices):
    """A name that IS in `blends` is computed and the tensor returned."""
    blends = {"bella_sarah": VoiceBlend("af_bella", "af_sarah", 0.3)}
    out = resolve_voice_param("bella_sarah", blends, fake_voices)
    # 0.3 * [1,0,0] + 0.7 * [0,1,0] = [0.3, 0.7, 0]
    import numpy as np
    assert np.allclose(out, [0.3, 0.7, 0.0])


def test_resolve_voice_param_blend_missing_voice_raises(fake_voices):
    """A blend whose voice_a is NOT in the pipeline must raise so the
    user gets a clean error, not a KeyError from deep in the pipeline."""
    blends = {"bad": VoiceBlend("xx_ghost", "af_sarah", 0.5)}
    with pytest.raises(KeyError):
        resolve_voice_param("bad", blends, fake_voices)


# ===================================================================
# load_blends / save_blends roundtrip
# ===================================================================

def test_save_and_load_roundtrip(fake_voices):
    """Saving then loading must yield the same dict (alpha rounded
    to 4 decimals during cache keying is irrelevant to JSON storage)."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "voice_blends.json"
        blends = {
            "bella_sarah_70": VoiceBlend("af_bella", "af_sarah", 0.7),
            "heart_nova": VoiceBlend("af_heart", "af_nova", 0.3),
        }
        save_blends(path, blends)
        loaded = load_blends(path)
        assert set(loaded) == set(blends)
        for name, b in blends.items():
            assert loaded[name].voice_a == b.voice_a
            assert loaded[name].voice_b == b.voice_b
            assert loaded[name].alpha == b.alpha


def test_save_creates_parent_dir(tmp_path):
    """A nested non-existent parent directory must be auto-created."""
    nested = tmp_path / "deep" / "nested" / "dir" / "blends.json"
    save_blends(nested, {"x": VoiceBlend("a", "b", 0.5)})
    assert nested.exists()


def test_save_rejects_invalid_name(tmp_path):
    """A name that fails the regex is rejected before touching disk."""
    with pytest.raises(ValueError, match="not a valid identifier"):
        save_blends(
            tmp_path / "b.json",
            {"1bad-name!": VoiceBlend("a", "b", 0.5)},
        )


def test_save_rejects_non_voiceblend_value(tmp_path):
    """A non-VoiceBlend value is rejected (we never want a dict-shaped
    entry to leak into the JSON)."""
    with pytest.raises(ValueError, match="not a VoiceBlend"):
        save_blends(
            tmp_path / "b.json",
            {"ok": {"voice_a": "a", "voice_b": "b", "alpha": 0.5}},
        )


def test_save_rejects_reserved_name_collision(tmp_path):
    """A blend name that collides with a built-in voice is rejected
    so the user can't shadow `af_heart` etc. in `_voice_list`."""
    reserved = {"af_heart": ("a", "f", "A", "...")}
    with pytest.raises(ValueError, match="collide"):
        save_blends(
            tmp_path / "b.json",
            {"af_heart": VoiceBlend("af_bella", "af_sarah", 0.5)},
            reserved_names=reserved,
        )


def test_save_writes_versioned_schema(tmp_path):
    """The on-disk shape MUST be `{"version": 1, "blends": {...}}` so
    we have a forward-compatible migration surface."""
    path = tmp_path / "b.json"
    save_blends(path, {"x": VoiceBlend("a", "b", 0.5)})
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert "x" in raw["blends"]
    assert raw["blends"]["x"]["voice_a"] == "a"
    assert raw["blends"]["x"]["voice_b"] == "b"
    assert raw["blends"]["x"]["alpha"] == 0.5


def test_load_missing_file_returns_empty():
    """A non-existent file is a normal first-run case (not an error)."""
    out = load_blends(Path("/tmp/definitely_does_not_exist_42.json"))
    assert out == {}


def test_load_malformed_json_returns_empty(tmp_path):
    """A broken JSON file should NOT crash — load as {} and log a warning."""
    path = tmp_path / "b.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_blends(path) == {}


def test_load_non_dict_top_level_returns_empty(tmp_path):
    path = tmp_path / "b.json"
    path.write_text("[]", encoding="utf-8")
    assert load_blends(path) == {}


def test_load_legacy_flat_schema_migrated(tmp_path):
    """A pre-versioned file (raw name->entry map) is migrated on load."""
    path = tmp_path / "b.json"
    legacy = {
        "legacy_blend": {"voice_a": "af_bella", "voice_b": "af_sarah", "alpha": 0.6},
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    out = load_blends(path)
    assert "legacy_blend" in out
    assert out["legacy_blend"].voice_a == "af_bella"
    assert out["legacy_blend"].alpha == 0.6


def test_load_legacy_skips_invalid_entries(tmp_path):
    """A legacy entry with bad shape is silently dropped (don't abort
    the whole load because one row is broken)."""
    path = tmp_path / "b.json"
    legacy = {
        "good": {"voice_a": "a", "voice_b": "b", "alpha": 0.5},
        "bad":  {"voice_a": "a", "alpha": 0.5},  # missing voice_b
        "junk": "not a dict",
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    out = load_blends(path)
    assert "good" in out
    assert "bad" not in out
    assert "junk" not in out


def test_load_version_newer_than_supported_loads_best_effort(tmp_path):
    """A file with version > supported loads as best-effort (forward
    compat) so future schema additions don't break old binaries."""
    path = tmp_path / "b.json"
    future = {
        "version": 99,
        "blends": {
            "future_blend": {"voice_a": "a", "voice_b": "b", "alpha": 0.5},
        },
    }
    path.write_text(json.dumps(future), encoding="utf-8")
    out = load_blends(path)
    assert "future_blend" in out
    assert out["future_blend"].alpha == 0.5


def test_load_versioned_skips_invalid_blend_names(tmp_path):
    """A blend entry whose NAME doesn't pass the regex is silently
    skipped so a corrupt row can't poison the loaded dict."""
    path = tmp_path / "b.json"
    payload = {
        "version": 1,
        "blends": {
            "valid_name": {"voice_a": "a", "voice_b": "b", "alpha": 0.5},
            "1invalid!":  {"voice_a": "a", "voice_b": "b", "alpha": 0.5},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    out = load_blends(path)
    assert "valid_name" in out
    assert "1invalid!" not in out


def test_load_versioned_skips_bad_entry_shapes(tmp_path):
    path = tmp_path / "b.json"
    payload = {
        "version": 1,
        "blends": {
            "good": {"voice_a": "a", "voice_b": "b", "alpha": 0.5},
            "alpha_nan": {"voice_a": "a", "voice_b": "b", "alpha": "0.5"},  # str alpha
            "alpha_neg": {"voice_a": "a", "voice_b": "b", "alpha": -0.1},   # bad range
            "missing_va": {"voice_b": "b", "alpha": 0.5},                    # missing va
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    out = load_blends(path)
    assert set(out.keys()) == {"good"}


def test_load_versioned_blends_not_dict_returns_empty(tmp_path):
    """A versioned file with `blends: []` (not a dict) is treated as
    empty — corruption-tolerant load."""
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"version": 1, "blends": []}), encoding="utf-8")
    assert load_blends(path) == {}


# ===================================================================
# Public API surface
# ===================================================================

def test_public_api_exports_present():
    """The module's __all__ is the canonical public surface — any
    breakage here is a hard backward-compat error."""
    from kokoro_studio import blending as b
    for name in [
        "VoiceBlend", "is_valid_blend_name", "load_blends", "save_blends",
        "compute_blend_tensor", "clear_tensor_cache", "resolve_voice_param",
    ]:
        assert hasattr(b, name), f"missing public symbol: {name}"
