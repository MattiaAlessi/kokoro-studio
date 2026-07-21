# -*- coding: utf-8 -*-
"""Emotion / Style Sliders for Kokoro Studio.

Phase 4 — Premium & Platform Features.  Manipulates the StyleTTS 2 style
vectors (voice tensors) to create emotional variations of any voice.

Public API:
    StyleParameters
        Dataclass: energy, warmth, expressiveness (each 0.0–1.0).

    compute_style_tensor(base_voice, params, pipeline_voices, blends?)
        -> torch.Tensor (modified style vector)

    default_style_params()
        -> StyleParameters (mid-range defaults)

    style_presets()
        -> dict of named StyleParameters for quick recall

How it works
------------
Kokoro-82M is built on StyleTTS 2, where each "voice" is a latent style
vector (a torch.Tensor).  The KPipeline accepts both string voice names
AND raw tensors as the ``voice=`` parameter.  We exploit this by:

  1. **Energy** (0.0–1.0): blend between a "calm" voice group and an
     "energetic" voice group, then mix with the base voice tensor.
  2. **Warmth** (0.0–1.0): blend between a "cool" voice group and a
     "warm" voice group, mixed into the tensor.
  3. **Expressiveness** (0.0–1.0): add scaled zero-mean gaussian noise
     to the tensor — subtle perturbations that create natural variation
     without changing the speaker identity.

The module has ZERO PySide6 dependencies and can be tested headlessly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Voice groupings for style interpolation
#
# These pairs define the "extreme" ends of each slider.  The actual
# interpolation happens in the latent space of voice tensors, not in
# audio space.  Hand-picked so the endpoints sound subjectively
# different while staying inside the same speaker neighbourhood.
# ---------------------------------------------------------------------------

# Warmth: "warm" voice group (rich, soft, deeper timbre)
_WARM_VOICES: Tuple[str, ...] = (
    "af_heart", "af_bella", "af_river", "af_sarah", "am_santa",
)

# Warmth: "cool" voice group (bright, crisp, lighter timbre)
_COOL_VOICES: Tuple[str, ...] = (
    "af_alloy", "af_aoede", "af_nova", "af_sky", "am_onyx",
)

# Energy: "energetic" voices (lively, dynamic)
_ENERGETIC_VOICES: Tuple[str, ...] = (
    "af_kore", "af_nicole", "af_jessica", "af_aoede",
)

# Energy: "calm" voices (relaxed, smooth)
_CALM_VOICES: Tuple[str, ...] = (
    "af_heart", "af_river", "af_sarah", "am_fenrir",
)


# ---------------------------------------------------------------------------
# Style parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StyleParameters:
    """Emotional/style modulation parameters.

    All values are normalised to [0.0, 1.0] where 0.5 is the neutral
    midpoint (no modification from the base voice).

    Attributes:
        energy:        0.0 = calm/smooth, 0.5 = neutral, 1.0 = energetic/bright.
        warmth:        0.0 = cool/crisp,  0.5 = neutral, 1.0 = warm/deep.
        expressiveness: 0.0 = flat/steady, 0.5 = neutral, 1.0 = dynamic/varied.
    """
    energy: float = 0.5
    warmth: float = 0.5
    expressiveness: float = 0.5

    def __post_init__(self) -> None:
        for field in ("energy", "warmth", "expressiveness"):
            val = getattr(self, field)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ValueError(f"{field} must be a number, got {val!r}")
            if val < 0.0 or val > 1.0:
                raise ValueError(
                    f"{field} must be in [0.0, 1.0], got {val}"
                )


def default_style_params() -> StyleParameters:
    """Return mid-range (neutral) style parameters."""
    return StyleParameters(energy=0.5, warmth=0.5, expressiveness=0.5)


# ---------------------------------------------------------------------------
# Named presets
# ---------------------------------------------------------------------------

_STYLE_PRESETS: Dict[str, StyleParameters] = {
    "Neutral":       StyleParameters(0.50, 0.50, 0.50),
    "Warm & Calm":   StyleParameters(0.20, 0.85, 0.30),
    "Bright & Energetic": StyleParameters(0.85, 0.20, 0.80),
    "Soft & Gentle": StyleParameters(0.15, 0.75, 0.20),
    "Bold & Dynamic": StyleParameters(0.90, 0.35, 0.90),
    "Cool & Crisp":  StyleParameters(0.60, 0.15, 0.50),
    "Deep & Rich":   StyleParameters(0.30, 0.95, 0.40),
    "Lively":        StyleParameters(0.80, 0.65, 0.85),
    "Monotone":      StyleParameters(0.50, 0.50, 0.00),
    "Expressive":    StyleParameters(0.65, 0.60, 0.95),
}


def style_presets() -> Dict[str, StyleParameters]:
    """Return a copy of the built-in style presets."""
    return dict(_STYLE_PRESETS)


# ---------------------------------------------------------------------------
# Tensor manipulation
# ---------------------------------------------------------------------------

def _pick_extreme_voice(
    base_voice: str,
    group_a: Tuple[str, ...],
    group_b: Tuple[str, ...],
    slider: float,
) -> str:
    """Pick an extreme voice from opposite groups based on slider value.

    At slider=0.0 picks from ``group_a``, at slider=1.0 picks from
    ``group_b``, at slider=0.5 picks the ``base_voice`` itself (neutral).
    The chosen voice is the *closest* group member to ``base_voice`` by
    name prefix, preferring the group's first entry when no match is
    found — this avoids jarring voice switches.
    """
    if slider == 0.5:
        return base_voice
    if slider < 0.5:
        # Blend toward group_a
        group = group_a
        intensity = abs(slider - 0.5) * 2.0  # 0.0 → 1.0
    else:
        group = group_b
        intensity = abs(slider - 0.5) * 2.0  # 0.0 → 1.0

    # Pick the group voice whose prefix matches the base voice, else first
    base_prefix = base_voice.split("_")[0] if "_" in base_voice else ""
    candidates = [v for v in group if v.startswith(base_prefix)]
    if candidates:
        extreme = candidates[0]
    else:
        extreme = group[0]

    # Return the extreme voice only at intensity == 1.0; at lower
    # intensities we interpolate between base and extreme later.
    return extreme


def _compute_interpolated_tensor(
    base_tensor: Any,
    target_tensor: Any,
    intensity: float,
) -> Any:
    """Linear interpolation: ``(1 - i) * base + i * target``.

    Both tensors must be the same shape (StyleTTS 2 latent vectors).
    """
    return (1.0 - intensity) * base_tensor + intensity * target_tensor


def _compute_noise_perturbation(
    tensor: Any,
    expressiveness: float,
    rng: Optional[np.random.Generator] = None,
) -> Any:
    """Add scaled gaussian noise to a voice tensor.

    The noise magnitude is proportional to the tensor's own norm and
    the ``expressiveness`` slider.  At 0.0 no noise is added (identity).
    At 1.0 the noise std is ~5 % of the tensor's norm, which creates
    subtle tonal variation without changing speaker identity.

    Args:
        tensor:         The torch.Tensor (or numpy array) to perturb.
        expressiveness: 0.0–1.0 slider value.
        rng:            Optional random generator for deterministic tests.

    Returns:
        Perturbed tensor (same type as input).
    """
    if expressiveness <= 0.0:
        return tensor

    # Work with numpy for the noise calculation
    if hasattr(tensor, "detach"):
        # torch.Tensor
        import torch  # type: ignore
        arr = tensor.detach().cpu().numpy()
        is_torch = True
    else:
        arr = np.asarray(tensor)
        is_torch = False

    # Noise std as fraction of the tensor norm
    norm = float(np.linalg.norm(arr))
    noise_scale = expressiveness * 0.05 * max(norm, 1e-8)

    if rng is None:
        rng = np.random.default_rng()
    noise = rng.normal(0.0, noise_scale, size=arr.shape).astype(arr.dtype)

    perturbed_arr = arr + noise

    if is_torch:
        # Return a new torch tensor on the same device
        device = getattr(tensor, "device", None)
        result = torch.from_numpy(perturbed_arr).to(device=device, dtype=tensor.dtype)
        return result
    return perturbed_arr


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_style_tensor(
    base_voice: str,
    params: StyleParameters,
    pipeline_voices: Mapping[str, Any],
    blends: Optional[Mapping[str, Any]] = None,
    rng: Optional[np.random.Generator] = None,
) -> Any:
    """Apply style slider parameters to a voice tensor.

    The process:
      1. Retrieve the base voice tensor from ``pipeline_voices``.
      2. Select an extreme "warmth" target voice and interpolate.
      3. Select an extreme "energy" target voice and interpolate.
      4. Add expressiveness noise.
      5. Return the modified tensor.

    Args:
        base_voice:      The original voice name (e.g. ``"af_heart"``).
        params:          Style parameters (energy, warmth, expressiveness).
        pipeline_voices: Live ``KPipeline.voices`` dict (torch.Tensor values).
        blends:          Optional blend presets (unused here, but accepted
                         for API consistency with the engine).
        rng:             Optional random generator for deterministic tests.

    Returns:
        A torch.Tensor suitable for passing as ``voice=`` to KPipeline.

    Raises:
        KeyError: if ``base_voice`` is not in ``pipeline_voices``.
        ValueError: if ``params`` is invalid.
    """
    # Validate
    if not isinstance(params, StyleParameters):
        raise ValueError("params must be a StyleParameters instance")

    # Resolve base voice: could be a string (built-in / blend) or a tensor
    if isinstance(base_voice, str):
        from kokoro_studio.blending import resolve_voice_param
        resolved = resolve_voice_param(base_voice, blends or {}, pipeline_voices)
    else:
        resolved = base_voice

    # If the resolved value is still a string (built-in voice name),
    # get the actual tensor from pipeline_voices
    if isinstance(resolved, str):
        if resolved not in pipeline_voices:
            raise KeyError(
                f"voice {resolved!r} is not loaded in the current pipeline. "
                f"Call _prime_voice_into_pipeline first."
            )
        base_tensor = pipeline_voices[resolved]
    else:
        base_tensor = resolved

    # ---- Warmth interpolation ----
    if params.warmth != 0.5:
        warmth_intensity = abs(params.warmth - 0.5) * 2.0
        extreme = _pick_extreme_voice(
            base_voice if isinstance(base_voice, str) else "",
            _COOL_VOICES, _WARM_VOICES, params.warmth,
        )
        if isinstance(extreme, str) and extreme in pipeline_voices:
            target = pipeline_voices[extreme]
            base_tensor = _compute_interpolated_tensor(
                base_tensor, target, warmth_intensity,
            )

    # ---- Energy interpolation ----
    if params.energy != 0.5:
        energy_intensity = abs(params.energy - 0.5) * 2.0
        extreme = _pick_extreme_voice(
            base_voice if isinstance(base_voice, str) else "",
            _CALM_VOICES, _ENERGETIC_VOICES, params.energy,
        )
        if isinstance(extreme, str) and extreme in pipeline_voices:
            target = pipeline_voices[extreme]
            base_tensor = _compute_interpolated_tensor(
                base_tensor, target, energy_intensity,
            )

    # ---- Expressiveness noise ----
    base_tensor = _compute_noise_perturbation(
        base_tensor, params.expressiveness, rng=rng,
    )

    return base_tensor


# ---------------------------------------------------------------------------
# Parameter display helpers
# ---------------------------------------------------------------------------

def summarize_style(params: StyleParameters) -> str:
    """Return a short human-readable summary of style parameters."""
    parts = []
    e = params.energy
    w = params.warmth
    x = params.expressiveness

    if e < 0.3:
        parts.append("Calm")
    elif e > 0.7:
        parts.append("Energetic")
    if w < 0.3:
        parts.append("Cool")
    elif w > 0.7:
        parts.append("Warm")
    if x < 0.2:
        parts.append("Flat")
    elif x > 0.8:
        parts.append("Expressive")

    if not parts:
        return "Neutral"

    return " · ".join(parts)
