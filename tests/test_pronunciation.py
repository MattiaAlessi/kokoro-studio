# -*- coding: utf-8 -*-
"""Smoke tests for `kokoro_studio.pronunciation`."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from kokoro_studio import pronunciation as pron


# ---------------------------------------------------------------------------
# Substitution semantics
# ---------------------------------------------------------------------------

def test_basic_replacement():
    assert pron.apply_substitutions("Kokoro Kokoro",
                                    {"Kokoro": "Ko-ko-ro"}) == "Ko-ko-ro Ko-ko-ro"


def test_case_sensitive_default():
    # 'hello' rule should NOT match 'Hello'.
    out = pron.apply_substitutions("Hello hello", {"hello": "x"})
    assert out == "Hello x"


def test_longest_rule_wins():
    # 'Kokoro' is longer than 'K', so 'Kokoro' rule fires first.
    out = pron.apply_substitutions("Kokoro K", {"K": "alpha", "Kokoro": "beta"})
    assert out == "beta alpha"


def test_whole_word_boundary():
    # \b prevents 'TTS' from matching inside 'MTTS'.
    out = pron.apply_substitutions("MTTS TTS", {"TTS": "tee-tee-ess"})
    assert out == "MTTS tee-tee-ess"


def test_empty_rules_is_identity():
    assert pron.apply_substitutions("hello", {}) == "hello"


def test_empty_text_is_identity():
    assert pron.apply_substitutions("", {"Kokoro": "x"}) == ""


def test_empty_replacement_deletes_word():
    out = pron.apply_substitutions("remove this word", {"this": ""})
    assert out == "remove  word"  # double space where 'this' was


def test_unicode_keys_preserved():
    # \b is Unicode-aware in Python's re module by default.
    out = pron.apply_substitutions(
        "Ciao Italia, ciao Roma",
        {"Ciao": "CIAO", "Roma": "ROMA"},
    )
    assert out == "CIAO Italia, ciao ROMA"


def test_single_pass_no_cascade():
    # If 'A' -> 'B' AND 'B' -> 'C', 'A' must NOT become 'C' on a single
    # pass; only 'B' rules fire on a re-pass of the substituted text.
    # With single-pass regex, 'A' -> 'B' is the only substitution seen.
    out = pron.apply_substitutions("A B", {"A": "B", "B": "C"})
    assert out == "B C", f"unexpected cascade: {out!r}"


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------

def test_json_roundtrip():
    rules = {"Kokoro": "Ko-ko-ro", "GPU": "", "Ciao": "ciao"}
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "pronunciation.json"
        pron.save_dictionary(p, rules)
        loaded = pron.load_dictionary(p)
        assert loaded == rules


def test_json_schema_v1():
    """Files written by save_dictionary should declare version=1."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "p.json"
        pron.save_dictionary(p, {"A": "B"})
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["version"] == 1
        assert raw["rules"] == [{"find": "A", "replace": "B"}]


def test_missing_file_returns_empty():
    assert pron.load_dictionary(Path("/no/such/file.json")) == {}


def test_malformed_json_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "broken.json"
        p.write_text("not json at all {", encoding="utf-8")
        assert pron.load_dictionary(p) == {}


def test_legacy_flat_schema_migrated():
    """Older files written as `{Kokoro: Ko-ko-ro}` (no `rules` wrapper)
    should auto-migrate to the versioned schema on read."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "legacy.json"
        p.write_text(json.dumps({"Kokoro": "Ko-ko-ro", "TTS": "tee"}),
                     encoding="utf-8")
        loaded = pron.load_dictionary(p)
        assert loaded == {"Kokoro": "Ko-ko-ro", "TTS": "tee"}


def test_blank_find_dropped():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "p.json"
        p.write_text(json.dumps({
            "version": 1,
            "rules": [
                {"find": "Kokoro", "replace": "Ko-ko-ro"},
                {"find": "",        "replace": "ignored"},
                {"find": "TTS",     "replace": "tee"},
            ]
        }), encoding="utf-8")
        loaded = pron.load_dictionary(p)
        assert loaded == {"Kokoro": "Ko-ko-ro", "TTS": "tee"}


def test_newer_version_warning_but_loads(tmp_path, caplog):
    """Future-version files should still load (best-effort)."""
    p = tmp_path / "future.json"
    p.write_text(json.dumps({
        "version": 99,
        "rules": [{"find": "A", "replace": "B"}],
    }), encoding="utf-8")
    with caplog.at_level("WARNING"):
        loaded = pron.load_dictionary(p)
    assert loaded == {"A": "B"}
