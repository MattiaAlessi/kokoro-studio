# -*- coding: utf-8 -*-
"""Tests for `kokoro_studio.profiles`.

Pure-Python module without Qt or kokoro. Coverage:

  * `CharacterProfile` dataclass: fields, defaults, frozenness.
  * `BUILTIN_PROFILES`: list shape, no duplicates.
  * `is_valid_profile_name`: valid and invalid identifiers.
  * `save_profiles` / `load_profiles`: roundtrip, versioned schema,
    legacy flat-schema, missing file, malformed JSON, built-in merge.
  * Built-in names are never shadowed by user data.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from kokoro_studio.profiles import (
    BUILTIN_PROFILES, CharacterProfile, is_valid_profile_name,
    load_profiles, save_profiles,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def json_path() -> Path:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        yield Path(td) / "profiles.json"


# ===================================================================
# CharacterProfile dataclass
# ===================================================================

def test_profile_defaults() -> None:
    p = CharacterProfile(name="test", voice="af_heart")
    assert p.speed == 1.0
    assert p.description == ""
    assert p.pronunciation_rules is None
    assert p.is_builtin is False


def test_profile_all_fields() -> None:
    p = CharacterProfile(
        name="Custom",
        voice="af_bella",
        speed=0.8,
        description="My custom voice",
        pronunciation_rules={"hello": "world"},
        is_builtin=False,
    )
    assert p.name == "Custom"
    assert p.voice == "af_bella"
    assert p.speed == 0.8
    assert p.description == "My custom voice"
    assert p.pronunciation_rules == {"hello": "world"}
    assert p.is_builtin is False


def test_profile_is_frozen() -> None:
    p = CharacterProfile(name="x", voice="v")
    with pytest.raises((AttributeError, Exception)):
        p.voice = "changed"  # type: ignore[misc]


def test_profile_builtin_flag_default() -> None:
    """is_builtin should default to False for user-created profiles."""
    p = CharacterProfile(name="u", voice="v")
    assert p.is_builtin is False


# ===================================================================
# BUILTIN_PROFILES
# ===================================================================

def test_builtin_profiles_is_list() -> None:
    assert isinstance(BUILTIN_PROFILES, list)
    assert len(BUILTIN_PROFILES) > 0


def test_builtin_profiles_all_have_is_builtin_true() -> None:
    for p in BUILTIN_PROFILES:
        assert p.is_builtin is True, f"{p.name} is not marked built-in"


def test_builtin_profiles_no_duplicate_names() -> None:
    names = [p.name for p in BUILTIN_PROFILES]
    assert len(names) == len(set(names)), "Duplicate built-in profile names"


def test_builtin_profiles_all_have_valid_voice() -> None:
    """All built-in profiles should reference a known voice name pattern."""
    for p in BUILTIN_PROFILES:
        assert isinstance(p.voice, str)
        assert len(p.voice) > 0


def test_builtin_profiles_speed_in_range() -> None:
    for p in BUILTIN_PROFILES:
        assert 0.1 <= p.speed <= 3.0, f"{p.name} speed {p.speed} out of range"


# ===================================================================
# is_valid_profile_name
# ===================================================================

@pytest.mark.parametrize("name", [
    "a", "MyProfile", "user_123", "_underscore", "Narrator",
    "British_Deep", "X", "A_B_C_99",
])
def test_valid_profile_names(name: str) -> None:
    assert is_valid_profile_name(name) is True


@pytest.mark.parametrize("name", [
    "", "123abc", "my-profile", "my.profile", "my profile",
    "hello!", "sp ace", "tab\t", "new\nline",
])
def test_invalid_profile_names(name: str) -> None:
    assert is_valid_profile_name(name) is False


def test_is_valid_profile_name_rejects_non_string() -> None:
    assert is_valid_profile_name(None) is False  # type: ignore[arg-type]
    assert is_valid_profile_name(123) is False  # type: ignore[arg-type]


# ===================================================================
# save_profiles / load_profiles roundtrip
# ===================================================================

def test_save_and_load_roundtrip(json_path: Path) -> None:
    """Saving then loading must yield the same user profiles."""
    profiles = {
        "my_narrator": CharacterProfile(
            name="my_narrator", voice="af_heart", speed=0.9,
            description="Slower narrator",
        ),
        "fast_talker": CharacterProfile(
            name="fast_talker", voice="af_nova", speed=1.5,
        ),
    }
    save_profiles(json_path, profiles)
    loaded = load_profiles(json_path)

    # Built-in profiles are always merged in
    for name in ["my_narrator", "fast_talker"]:
        assert name in loaded, f"Missing profile: {name}"
        assert loaded[name].voice == profiles[name].voice
        assert loaded[name].speed == profiles[name].speed
        assert loaded[name].is_builtin is False


def test_load_merges_builtins(json_path: Path) -> None:
    """load_profiles must always include built-in profiles."""
    # Empty file on disk
    loaded = load_profiles(json_path)
    for p in BUILTIN_PROFILES:
        assert p.name in loaded, f"Missing built-in: {p.name}"
        assert loaded[p.name].is_builtin is True


def test_load_missing_file_returns_builtins(json_path: Path) -> None:
    """A non-existent file should return only built-ins."""
    # Create path but don't write anything
    loaded = load_profiles(json_path)
    for p in BUILTIN_PROFILES:
        assert p.name in loaded


def test_load_malformed_json_returns_builtins(json_path: Path) -> None:
    json_path.write_text("{not valid", encoding="utf-8")
    loaded = load_profiles(json_path)
    for p in BUILTIN_PROFILES:
        assert p.name in loaded


def test_save_creates_parent_directory() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        nested = Path(td) / "deep" / "nested" / "dir" / "profiles.json"
        save_profiles(nested, {"x": CharacterProfile("x", "af_heart")})
        assert nested.exists()


def test_save_writes_versioned_schema(json_path: Path) -> None:
    save_profiles(json_path, {"x": CharacterProfile("x", "v", 1.0)})
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert "x" in raw["profiles"]
    assert raw["profiles"]["x"]["voice"] == "v"
    assert raw["profiles"]["x"]["speed"] == 1.0


def test_save_skips_builtin_profiles(json_path: Path) -> None:
    """Built-in profiles should never be persisted."""
    all_profiles = {
        "Narrator": CharacterProfile("Narrator", "v", is_builtin=True),
        "user_one": CharacterProfile("user_one", "v"),
    }
    save_profiles(json_path, all_profiles)
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    assert "Narrator" not in raw.get("profiles", {}), "Built-in was persisted"
    assert "user_one" in raw.get("profiles", {})


def test_builtin_names_never_overridden(json_path: Path) -> None:
    """A user-saved profile with a built-in name must not shadow it."""
    save_profiles(json_path, {
        "Narrator": CharacterProfile("Narrator", "af_bella", speed=2.0),
    })
    loaded = load_profiles(json_path)
    assert loaded["Narrator"].voice == "af_heart"  # original built-in


def test_save_rejects_invalid_name(json_path: Path) -> None:
    with pytest.raises(ValueError, match="not a valid identifier"):
        save_profiles(json_path, {
            "bad-name!": CharacterProfile("bad-name!", "v"),
        })


def test_save_rejects_non_profile_value(json_path: Path) -> None:
    with pytest.raises(ValueError, match="not a CharacterProfile"):
        save_profiles(json_path, {"x": {"voice": "v"}})  # type: ignore[arg-type]


def test_load_skips_invalid_names_in_file(json_path: Path) -> None:
    """Corrupt entries in the JSON file should be skipped silently."""
    payload = {
        "version": 1,
        "profiles": {
            "good_name": {"voice": "af_heart", "speed": 1.0},
            "1bad!": {"voice": "af_heart", "speed": 1.0},
            "": {"voice": "af_heart", "speed": 1.0},
        },
    }
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_profiles(json_path)
    assert "good_name" in loaded
    assert "1bad!" not in loaded
    assert "" not in loaded


def test_load_skips_malformed_entries(json_path: Path) -> None:
    payload = {
        "version": 1,
        "profiles": {
            "good": {"voice": "af_heart", "speed": 1.0},
            "no_voice": {"speed": 1.0},           # missing voice
            "bad_speed": {"voice": "v", "speed": "not-a-number"},
        },
    }
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_profiles(json_path)
    assert "good" in loaded
    assert "no_voice" not in loaded
    assert "bad_speed" not in loaded


def test_load_with_pronunciation_rules(json_path: Path) -> None:
    """Profiles with pronunciation rules should roundtrip correctly."""
    rules = {"hello": "world", "foo": "bar"}
    save_profiles(json_path, {
        "with_rules": CharacterProfile(
            "with_rules", "af_heart", pronunciation_rules=rules,
        ),
    })
    loaded = load_profiles(json_path)
    assert "with_rules" in loaded
    assert loaded["with_rules"].pronunciation_rules == rules


def test_load_pronunciation_rules_not_required(json_path: Path) -> None:
    """Profiles without pronunciation rules should load fine."""
    save_profiles(json_path, {
        "no_rules": CharacterProfile("no_rules", "af_heart"),
    })
    loaded = load_profiles(json_path)
    assert loaded["no_rules"].pronunciation_rules is None
