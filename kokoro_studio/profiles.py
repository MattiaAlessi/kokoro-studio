# -*- coding: utf-8 -*-
"""Character profiles for Kokoro Studio.

Phase 3 — "Character Profiles". Save named presets of voice (or blend)
+ speed (+ optional pronunciation rules) for one-click recall.

Public API:
    CharacterProfile
        Dataclass representing a named preset.
    BUILTIN_PROFILES
        List of built-in presets shipped with the app.
    load_profiles(path) -> dict[str, CharacterProfile]
    save_profiles(path, profiles, reserved_names=...)
    is_valid_profile_name(name) -> bool
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Versioned JSON schema so a future schema change can be auto-migrated.
_PROFILES_SCHEMA_VERSION = 1

# Regex for profile names (same shape as blend names — alphanumeric + underscore).
_VALID_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CharacterProfile:
    """A named preset of TTS parameters.

    Fields:
        name:           Unique identifier (used as the JSON key + dropdown label).
        voice:          Voice or saved-blend name.
        speed:          Speed multiplier.
        description:    Short human-readable description (shown in tooltip / subtitle).
        pronunciation_rules:  Optional dict of {find: replace} applied on top of
                              the main pronunciation dictionary.  ``None`` = use
                              whatever the user has loaded in the GUI.
        is_builtin:     If True, the profile is read-only (cannot be deleted or
                        overwritten through the dialog).  Set by the loader.
    """

    name: str
    voice: str
    speed: float = 1.0
    description: str = ""
    pronunciation_rules: Optional[Dict[str, str]] = None
    is_builtin: bool = False


# ---------------------------------------------------------------------------
# Built-in presets
# ---------------------------------------------------------------------------

BUILTIN_PROFILES: List[CharacterProfile] = [
    CharacterProfile(
        name="Narrator",
        voice="af_heart",
        speed=1.0,
        description="Warm, natural — recommended for narration",
        is_builtin=True,
    ),
    CharacterProfile(
        name="News Anchor",
        voice="af_nova",
        speed=1.2,
        description="Modern, expressive — brisk newsreader pace",
        is_builtin=True,
    ),
    CharacterProfile(
        name="Storyteller",
        voice="af_bella",
        speed=0.9,
        description="Young, lively — slightly slower for dramatic reading",
        is_builtin=True,
    ),
    CharacterProfile(
        name="Professor",
        voice="am_michael",
        speed=0.85,
        description="Calm, deliberate male voice",
        is_builtin=True,
    ),
    CharacterProfile(
        name="Deep Voice",
        voice="am_onyx",
        speed=0.9,
        description="Deep timbre, authoritative",
        is_builtin=True,
    ),
    CharacterProfile(
        name="Whisper",
        voice="af_sky",
        speed=0.75,
        description="Soft, conversational — gentle pace",
        is_builtin=True,
    ),
    CharacterProfile(
        name="Energetic",
        voice="af_kore",
        speed=1.3,
        description="Bright, fast-paced delivery",
        is_builtin=True,
    ),
    CharacterProfile(
        name="British Narrator",
        voice="bf_alice",
        speed=1.0,
        description="British English female",
        is_builtin=True,
    ),
    CharacterProfile(
        name="British Deep",
        voice="bm_george",
        speed=0.85,
        description="British male, deep timbre",
        is_builtin=True,
    ),
]

# Index built-in profiles by name for fast lookup.
_BUILTIN_INDEX: Dict[str, CharacterProfile] = {
    p.name: p for p in BUILTIN_PROFILES
}


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

def is_valid_profile_name(name: object) -> bool:
    """Return True if *name* is a valid profile identifier.

    Must be a string matching ``[A-Za-z_][A-Za-z0-9_]*``.  Built-in
    names are valid (they exist), but the caller must still check the
    ``is_builtin`` flag to decide whether editing is allowed.
    """
    if not isinstance(name, str):
        return False
    return bool(_VALID_NAME_RE.match(name))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _profile_to_dict(p: CharacterProfile) -> dict:
    """Serialize a profile to a JSON-safe dict (strip is_builtin)."""
    d = asdict(p)
    d.pop("is_builtin", None)
    if d.get("pronunciation_rules") is None:
        d.pop("pronunciation_rules", None)
    return d


def _profile_from_dict(name: str, data: dict, is_builtin: bool = False) -> Optional[CharacterProfile]:
    """Deserialize a dict into a CharacterProfile.

    Returns None if the data is malformed (skipped silently on load).
    """
    try:
        voice = str(data["voice"])
        speed = float(data.get("speed", 1.0))
        description = str(data.get("description", ""))
        pron_raw = data.get("pronunciation_rules")
        pron = dict(pron_raw) if isinstance(pron_raw, dict) else None
        return CharacterProfile(
            name=name,
            voice=voice,
            speed=speed,
            description=description,
            pronunciation_rules=pron,
            is_builtin=is_builtin,
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_profiles(path: Path, profiles: Dict[str, CharacterProfile], reserved_names: Optional[Dict[str, object]] = None) -> None:
    """Write *profiles* to a JSON file at *path*.

    Args:
        path:             Destination file path.
        profiles:         Name → CharacterProfile mapping.
        reserved_names:   Optional dict whose keys are reserved
                          (e.g. built-in voices from ``engine.VOICES``).
                          A profile whose name collides with a reserved
                          name is silently excluded from the save
                          (the built-in name wins).

    Raises:
        OSError:  If the file cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    cleaned: Dict[str, dict] = {}
    for name, profile in profiles.items():
        if not isinstance(profile, CharacterProfile):
            raise ValueError(
                f"Profile {name!r} is not a CharacterProfile instance."
            )
        if not is_valid_profile_name(name):
            raise ValueError(
                f"Profile name {name!r} is not a valid identifier."
            )
        if reserved_names and name in reserved_names:
            print(
                f"[Kokoro] Skipping profile {name!r}: collides with reserved name",
                file=sys.stderr,
            )
            continue
        if profile.is_builtin:
            continue  # built-in profiles are not persisted
        cleaned[name] = _profile_to_dict(profile)

    payload = {
        "version": _PROFILES_SCHEMA_VERSION,
        "profiles": cleaned,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_profiles(path: Path) -> Dict[str, CharacterProfile]:
    """Load user-defined profiles from a JSON file at *path*.

    Always merges built-in profiles on top, so built-in names can
    never be shadowed by user data.

    Returns a dict name → CharacterProfile (built-in + user-defined).
    """
    result = dict(_BUILTIN_INDEX)  # built-ins always present

    if not path.exists():
        return result

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return result

    if not isinstance(raw, dict):
        return result

    # Versioned schema.
    raw_profiles = raw.get("profiles") if isinstance(raw.get("version"), int) else raw

    if not isinstance(raw_profiles, dict):
        return result

    for name, data in raw_profiles.items():
        if not is_valid_profile_name(name):
            continue
        if name in _BUILTIN_INDEX:
            continue  # never override a built-in
        profile = _profile_from_dict(name, data, is_builtin=False)
        if profile is not None:
            result[name] = profile

    return result
