# -*- coding: utf-8 -*-
"""Voice Blending / Mixing for Kokoro Studio.

Public API:
    VoiceBlend                        — frozen dataclass (voice_a, voice_b, alpha)
    load_blends(path)                 -> Dict[str, VoiceBlend]
    save_blends(path, blends, ...)    -> None  (raises on name conflicts with built-ins)
    compute_blend_tensor(blend, pv)   -> tensor
    resolve_voice_param(name, ...)    -> Union[str, tensor]  (str OR computed tensor)

Voice blending in Kokoro uses StyleTTS 2 style vector linear
interpolation. Two preset voice tensors (`voice_a` and `voice_b`) are
combined with a real-valued weight `alpha`:

    blended_tensor = alpha * voice_a_tensor + (1.0 - alpha) * voice_b_tensor

The KPipeline's `voice=` parameter accepts BOTH a string OR a torch.Tensor
directly, so a blended tensor can be passed straight through.

Architecture
------------

* **Zero PySide6 deps** — same as `pronunciation.py` / `dialogue.py`,
  lets us unit-test in CI without Qt at all.
* **Lazy tensor access** — we don't pre-load all 29 voice tensors. The
  engine resolves a blend via its already-loaded `KPipeline.voices`
  cache (per web research, KPipeline populates `.voices[name]` with the
  torch.Tensor after construction). We cache the resulting blended
  tensor keyed on `(va, vb, alpha)` so re-runs of the same blend are
  O(1) after the first one.
* **JSON persistence** (forward-compat versioned schema, same shape as
  pronunciation.py):

    {
      "version": 1,
      "blends": {
        "bella_sarah_70": {
          "voice_a": "af_bella",
          "voice_b": "af_sarah",
          "alpha": 0.7
        }
      }
    }

* **Blend name validation** — must match the same regex as the dialogue
  marker tokens (`[A-Za-z_][A-Za-z0-9_]*`) so blended presets can be
  used seamlessly inside `[my_blend]: text` markers.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# Constants & module-level state
# ---------------------------------------------------------------------------

# Schema version. Bump only when we change the on-disk shape.
_SCHEMA_VERSION: int = 1

# Blend names share their character class with dialogue marker tokens,
# so users can write `[my_blend]: Hello!` in editor. Keeping these two
# regexes in sync is intentional — that way any valid blend name is
# automatically compatible with the multi-speaker dialogue parser.
_BLEND_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Cache blended tensors by (va, vb, alpha). Alpha is rounded to 4 decimals
# so a continuous slider sweep doesn't blow up the cache size — we'd
# never want `0.7000001` and `0.7000002` as separate cache entries from
# a user micro-dragging the slider.
_BLEND_CACHE: Dict[Tuple[str, str, float], Any] = {}

# Cache rejected resolutions (e.g. duplicate blend name) so the engine
# can short-circuit on repeated calls. We deliberately don't cache the
# "couldn't find voice in pipeline.voices" error, because the user might
# install a new language pack mid-session — we re-resolve instead.
_VALID_NAMES_CACHE: Dict[str, None] = {}


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VoiceBlend:
    """One weighted linear combination of two preset voices.

    Attributes:
        voice_a: Kokoro voice name (must be in `kokoro_studio.engine.VOICES`
                 at runtime). Carries weight `alpha`.
        voice_b: Kokoro voice name. Carries weight `1.0 - alpha`.
        alpha:  Real weight in [0.0, 1.0] applied to `voice_a`. At the
                 endpoints (0.0 or 1.0) the blend degenerates to a pure
                 preset; mid-range values interpolate. Values outside the
                 range are rejected in `__post_init__`.
    """

    voice_a: str
    voice_b: str
    alpha: float

    def __post_init__(self) -> None:
        if not isinstance(self.alpha, (int, float)) or isinstance(self.alpha, bool):
            raise ValueError(
                f"alpha must be a real number in [0.0, 1.0], got {self.alpha!r}"
            )
        alpha_f = float(self.alpha)
        if not (0.0 <= alpha_f <= 1.0):
            raise ValueError(
                f"alpha must be in [0.0, 1.0], got {alpha_f}"
            )
        # Normalise -0.0 to +0.0 so the rounded cache key matches the
        # `0.0` entry (otherwise two VoiceBlends with alpha=0.0 and
        # alpha=-0.0 would compute twice and cache twice). 0.0 + 0.0
        # is the canonical IEEE-754 identity that flips the sign bit.
        if alpha_f == 0.0:
            alpha_f = 0.0
        if not isinstance(self.voice_a, str) or not isinstance(self.voice_b, str):
            raise ValueError("voice_a and voice_b must be strings")
        # Re-write the float-rounded value back so the dataclass always
        # stores alpha as a Python float, not a numpy scalar from a UI
        # valueChanged signal.
        object.__setattr__(self, "alpha", alpha_f)
        # Same for str (silently rejects int etc.)
        object.__setattr__(self, "voice_a", str(self.voice_a))
        object.__setattr__(self, "voice_b", str(self.voice_b))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_valid_blend_name(name: str) -> bool:
    """True iff `name` matches the blend-name regex.

    Identical to the dialogue-marker token regex — so any blend name
    can be used inside `[my_blend]: hello!` markers without parser
    fuss.
    """
    if not isinstance(name, str):
        return False
    return bool(_BLEND_NAME_RE.match(name))


def _coerce_to_blend(value: Union["VoiceBlend", Tuple[str, str, float], None]) -> Optional["VoiceBlend"]:
    """Coerce a 3-tuple `(va, vb, alpha)` OR a `VoiceBlend` instance
    into a `VoiceBlend`. Quiet no-op on `None`. Raises `ValueError` on
    anything else.
    """
    if value is None:
        return None
    if isinstance(value, VoiceBlend):
        return value
    if isinstance(value, tuple) and len(value) == 3:
        return VoiceBlend(voice_a=value[0], voice_b=value[1], alpha=value[2])
    raise ValueError(
        "`voice_blend` must be a VoiceBlend instance, a 3-tuple "
        "(voice_a, voice_b, alpha), or None."
    )


def _blend_cache_key(voice_a: str, voice_b: str, alpha: float) -> Tuple[str, str, float]:
    """Stable cache key — `alpha` is rounded to 4 decimals so the
    cache stays bounded when the user drags a slider in real time.
    """
    return (voice_a, voice_b, round(float(alpha), 4))


# ---------------------------------------------------------------------------
# Tensor resolution (engine integration)
# ---------------------------------------------------------------------------

def compute_blend_tensor(
    blend: "VoiceBlend",
    pipeline_voices: Mapping[str, Any],
) -> Any:
    """Compute (and cache) the blended tensor for `blend`.

    Args:
        blend:           a `VoiceBlend` (or anything `_coerce_to_blend` accepts).
        pipeline_voices: dict-like view of `KPipeline.voices` -- the
                         already-loaded torch.Tensors keyed by Kokoro
                         voice name. The engine supplies this after
                         `_get_pipeline(lang_code)` returns.

    Returns:
        A torch.Tensor (or any value supporting tensor arithmetic —
        `alpha * t + (1.0 - alpha) * u`). The cache reuses the same
        instance on identical `(va, vb, alpha)`.

    Raises:
        KeyError: if `voice_a` or `voice_b` isn't in `pipeline_voices`.
        ValueError: if `blend` is not a valid `VoiceBlend`.
    """
    blend = _coerce_to_blend(blend)
    if blend is None:
        raise ValueError("`blend` must not be None")

    key = _blend_cache_key(blend.voice_a, blend.voice_b, blend.alpha)
    cached = _BLEND_CACHE.get(key)
    if cached is not None:
        return cached

    if blend.voice_a not in pipeline_voices:
        raise KeyError(
            f"voice_a {blend.voice_a!r} is not loaded in the current "
            f"pipeline (known: {sorted(pipeline_voices.keys())[:5]}…)"
        )
    if blend.voice_b not in pipeline_voices:
        raise KeyError(
            f"voice_b {blend.voice_b!r} is not loaded in the current "
            f"pipeline (known: {sorted(pipeline_voices.keys())[:5]}…)"
        )

    tensor_a = pipeline_voices[blend.voice_a]
    tensor_b = pipeline_voices[blend.voice_b]
    # Both tensors share the same ShapeTTS-2 latent layout, so plain
    # linear interpolation works element-wise without broadcasting
    # hazards. If a future model changes tensor shapes per voice, the
    # fallback for `alpha * t + (1 - alpha) * u` will raise rather than
    # silently mangling the data — that's the right behaviour.
    blended = blend.alpha * tensor_a + (1.0 - blend.alpha) * tensor_b

    _BLEND_CACHE[key] = blended
    return blended


def clear_tensor_cache() -> None:
    """Drop the in-memory blend-tensor cache.

    Used in unit tests to keep state isolated. Not generally needed in
    production: the cache is bounded by `_blend_cache_key` rounding
    (alpha → 4 decimals ⇒ O(10_000) entries in the absolute worst case
    of a continuous slider sweep over [0, 1]).
    """
    _BLEND_CACHE.clear()


def resolve_voice_param(
    voice_str: str,
    blends: Mapping[str, "VoiceBlend"],
    pipeline_voices: Mapping[str, Any],
) -> Union[str, Any]:
    """If `voice_str` is a known blend in `blends`, return its blended
    tensor. Otherwise return `voice_str` itself so the KPipeline can
    resolve it as a built-in voice name.

    Args:
        voice_str:        voice name selected by the user (built-in OR saved blend)
        blends:           loaded blend presets (engine `_loaded_blends`)
        pipeline_voices:  live `KPipeline.voices` mapping

    Returns:
        Either a torch.Tensor (blend) or the input string (built-in).
    """
    if voice_str in blends:
        return compute_blend_tensor(blends[voice_str], pipeline_voices)
    return voice_str


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------

def load_blends(path: Path) -> Dict[str, "VoiceBlend"]:
    """Load blends from `path`. Returns {} on any read / parse failure.

    * Missing file → empty dict (first-run, fine).
    * Malformed JSON → logged + empty dict (don't crash startup).
    * Legacy flat schema → migrated on the fly, logged once.
    * Schema version newer than supported → loaded best-effort, logged.
    * Each blend entry is validated; bad entries are skipped silently
      with a warning so one corrupted preset doesn't kill the whole dict.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.warning("[blending] could not read %s: %s", path, e)
        return {}

    if not isinstance(data, dict):
        logging.warning("[blending] %s: top-level JSON is not an object", path)
        return {}

    if "blends" not in data:
        # Legacy flat schema: {"my_blend": {"voice_a": ..., "voice_b": ..., "alpha": ...}}
        migrated: Dict[str, "VoiceBlend"] = {}
        for name, info in data.items():
            if not isinstance(name, str) or not isinstance(info, dict):
                continue
            try:
                migrated[name] = _blend_from_mapping(name, info)
            except ValueError as e:
                logging.warning(
                    "[blending] %s: skipping legacy entry %r (%s)", path, name, e,
                )
        if migrated:
            logging.info(
                "[blending] %s: migrated legacy flat schema (%d blends)",
                path, len(migrated),
            )
        return migrated

    version = data.get("version", 1)
    if isinstance(version, int) and version > _SCHEMA_VERSION:
        logging.warning(
            "[blending] %s has version %d (newer than supported %d); "
            "loading as best-effort", path, version, _SCHEMA_VERSION,
        )

    raw = data.get("blends", {})
    if not isinstance(raw, dict):
        logging.warning("[blending] %s: 'blends' is not an object", path)
        return {}

    out: Dict[str, "VoiceBlend"] = {}
    for name, info in raw.items():
        if not isinstance(name, str) or not is_valid_blend_name(name):
            logging.warning(
                "[blending] %s: skipping invalid name %r "
                "(must match %s)", path, name, _BLEND_NAME_RE.pattern,
            )
            continue
        try:
            out[name] = _blend_from_mapping(name, info)
        except ValueError as e:
            logging.warning(
                "[blending] %s: skipping %r (%s)", path, name, e,
            )
    return out


def _blend_from_mapping(name: str, info: Any) -> "VoiceBlend":
    """Construct a `VoiceBlend` from a JSON-decoded `info` entry.

    Raises ValueError on bad shape / bad types so the loader can skip
    the entry cleanly without aborting the whole dict.
    """
    if not isinstance(info, dict):
        raise ValueError("not an object")
    va = info.get("voice_a", "")
    vb = info.get("voice_b", "")
    alpha = info.get("alpha", 0.5)
    if not isinstance(va, str) or not va:
        raise ValueError("voice_a missing or non-string")
    if not isinstance(vb, str) or not vb:
        raise ValueError("voice_b missing or non-string")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError("alpha must be a number")
    return VoiceBlend(voice_a=va, voice_b=vb, alpha=float(alpha))


def save_blends(
    path: Path,
    blends: Mapping[str, "VoiceBlend"],
    *,
    reserved_names: Optional[Mapping[str, Any]] = None,
) -> None:
    """Persist `blends` to `path` as JSON (versioned schema).

    Args:
        path:           destination file. Parent is auto-created.
        blends:         name → `VoiceBlend` mapping.
        reserved_names: optional mapping of NAMES that must NOT clash —
                        e.g. `engine.VOICES`. If a blend name collides,
                        a `ValueError` is raised (caller decides to
                        surface it to the user via QMessageBox).

    Raises:
        ValueError: on a name conflict with `reserved_names`.
        OSError:    on a parent-directory creation failure.
    """
    if reserved_names:
        clash = set(blends.keys()) & set(reserved_names.keys())
        if clash:
            raise ValueError(
                "Blend names collide with built-in voice names: "
                + ", ".join(sorted(clash))
            )

    # Validate every blend before touching disk — a malformed entry
    # should fail fast in tests, not produce a corrupt JSON file.
    for name, blend in blends.items():
        if not is_valid_blend_name(name):
            raise ValueError(
                f"Blend name {name!r} is not a valid identifier "
                f"(must match {_BLEND_NAME_RE.pattern})"
            )
        if not isinstance(blend, VoiceBlend):
            raise ValueError(f"{name!r} is not a VoiceBlend instance")

    payload = {
        "version": _SCHEMA_VERSION,
        "blends": {
            name: {
                "voice_a": b.voice_a,
                "voice_b": b.voice_b,
                "alpha": b.alpha,
            }
            for name, b in blends.items()
        },
    }

    parent = path.parent
    if parent and not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(
                f"Cannot create blend directory {parent}: {e}"
            ) from e

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public symbols
# ---------------------------------------------------------------------------

__all__ = [
    "VoiceBlend",
    "is_valid_blend_name",
    "load_blends",
    "save_blends",
    "compute_blend_tensor",
    "clear_tensor_cache",
    "resolve_voice_param",
]
