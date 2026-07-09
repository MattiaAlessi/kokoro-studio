# -*- coding: utf-8 -*-
"""Tests for `kokoro_studio.dialogue`.

Pure-Python parser without Qt, kokoro or numpy — runs fast in CI
without any heavy models loaded. Coverage:

  * Single marker detection.
  * Multi-segment parsing, including continuation lines.
  * Unknown voice fallback (warning + default voice).
  * Unknowns work in known_voices=None mode (no fallback at all).
  * No markers → single default-voice segment.
  * CRLF input handling.
  * Whitespace tolerance inside the marker / after the colon.
  * Empty / whitespace-only segments dropped.
  * Marker at column > 0 (mid-line) NOT recognised — only line start.
  * detect_dialogue precheck agrees with the full parser.
"""

from __future__ import annotations

from typing import List

import pytest

from kokoro_studio import dialogue as dlg


# Convenience constructor shared across tests.
def _seg(voice: str, text: str = "...") -> dlg.DialogueSegment:
    return dlg.DialogueSegment(voice=voice, text=text)


KNOWN = {"af_heart", "am_adam", "bf_isabella"}


# ---------------------------------------------------------------------------
# Single-marker detection
# ---------------------------------------------------------------------------

def test_single_marker_creates_one_segment():
    segs, warns = dlg.parse_dialogue("[af_heart]: Hello!", default_voice="af_heart",
                                     known_voices=KNOWN)
    assert warns == []
    assert segs == [_seg("af_heart", "Hello!")]


def test_marker_with_markdown_punctuation_in_text():
    text = "[af_heart]: **Hello**, world!"
    segs, _ = dlg.parse_dialogue(text, default_voice="af_heart", known_voices=KNOWN)
    assert segs == [_seg("af_heart", "**Hello**, world!")]


# ---------------------------------------------------------------------------
# Multi-segment parsing
# ---------------------------------------------------------------------------

def test_two_speakers_round_trip():
    text = "[af_heart]: Hi.\n[am_adam]: Hey."
    segs, warns = dlg.parse_dialogue(text, default_voice="af_heart",
                                     known_voices=KNOWN)
    assert warns == []
    assert segs == [
        _seg("af_heart", "Hi."),
        _seg("am_adam", "Hey."),
    ]


def test_three_speakers_with_continuation_lines():
    text = (
        "[af_heart]: Hello there.\n"
        "How are you doing today?\n"
        "[am_adam]: I'm great, thanks.\n"
        "And yourself?\n"
        "[af_heart]: Wonderful.\n"
    )
    segs, warns = dlg.parse_dialogue(text, default_voice="af_heart",
                                     known_voices=KNOWN)
    assert warns == []
    assert segs == [
        _seg("af_heart", "Hello there.\nHow are you doing today?"),
        _seg("am_adam",   "I'm great, thanks.\nAnd yourself?"),
        _seg("af_heart", "Wonderful."),
    ]


def test_pre_marker_text_uses_default_voice():
    text = (
        "Once upon a time...\n"
        "[af_heart]: Hello!\n"
        "[am_adam]: Hi.\n"
    )
    segs, _ = dlg.parse_dialogue(text, default_voice="am_michael",
                                 known_voices=KNOWN)
    assert segs == [
        _seg("am_michael", "Once upon a time..."),
        _seg("af_heart",   "Hello!"),
        _seg("am_adam",    "Hi."),
    ]


def test_known_voices_none_passes_token_through_unchanged():
    """When the caller doesn't pass `known_voices`, the parser accepts
    anything — useful for hosting call sites (CLI / batch mode) that
    don't pre-load the engine's catalog.
    """
    text = "[xx_unknown]: Hi."
    segs, warns = dlg.parse_dialogue(text, default_voice="af_heart",
                                     known_voices=None)
    assert warns == []
    assert segs == [_seg("xx_unknown", "Hi.")]


# ---------------------------------------------------------------------------
# Unknown-voice handling
# ---------------------------------------------------------------------------

def test_unknown_voice_emits_warning_and_falls_back():
    text = "[xx_ghost]: Hi.\n[af_heart]: Hello."
    segs, warns = dlg.parse_dialogue(text, default_voice="am_michael",
                                     known_voices=KNOWN)
    assert len(segs) == 2
    assert segs[0].voice == "am_michael"
    assert segs[0].text  == "Hi."
    assert segs[1].voice == "af_heart"
    assert segs[1].text  == "Hello."
    assert len(warns) == 1
    assert "xx_ghost" in warns[0]
    assert "am_michael" in warns[0]


def test_multiple_unknown_voices_each_warned():
    text = "[xx_ghost1]: Hi.\n[xx_ghost2]: Hey.\n[af_heart]: Hello."
    segs, warns = dlg.parse_dialogue(text, default_voice="bf_isabella",
                                     known_voices=KNOWN)
    assert len(warns) == 2
    assert "xx_ghost1" in warns[0]
    assert "xx_ghost2" in warns[1]
    # All unknown tokens collapse to default.
    assert segs[0].voice == "bf_isabella"
    assert segs[1].voice == "bf_isabella"
    assert segs[2].voice == "af_heart"


# ---------------------------------------------------------------------------
# No-marker baseline
# ---------------------------------------------------------------------------

def test_no_markers_yields_single_default_segment():
    text = "Just plain text. Nothing to do with voices."
    segs, warns = dlg.parse_dialogue(text, default_voice="af_heart",
                                     known_voices=KNOWN)
    assert warns == []
    assert segs == [_seg("af_heart", text)]


def test_blank_text_yields_empty_segments():
    segs, warns = dlg.parse_dialogue("   \n\n\t", default_voice="af_heart",
                                     known_voices=KNOWN)
    assert warns == []
    assert segs == []


def test_only_marker_no_body():
    """A marker line with empty body, no following lines, is dropped."""
    segs, warns = dlg.parse_dialogue("[af_heart]:", default_voice="af_heart",
                                     known_voices=KNOWN)
    assert warns == []
    assert segs == []


def test_marker_then_continuation_only_no_body():
    """A marker with empty body followed by another segment is also fine."""
    text = "[af_heart]:\n[am_adam]: Actually just me."
    segs, _ = dlg.parse_dialogue(text, default_voice="af_heart",
                                 known_voices=KNOWN)
    # First marker had nothing — the parser should drop it cleanly
    # and not synthesise empty audio.
    assert segs == [_seg("am_adam", "Actually just me.")]


# ---------------------------------------------------------------------------
# detect_dialogue precheck
# ---------------------------------------------------------------------------

def test_detect_true_when_marker_present():
    assert dlg.detect_dialogue("Hello.\n[af_heart]: Hi.") is True


def test_detect_false_when_no_marker():
    assert dlg.detect_dialogue("Just text, no markers here.") is False


def test_detect_false_for_brackets_mid_line():
    """`[af_heart]:` mid-line IS NOT a marker — only line-start counts."""
    assert dlg.detect_dialogue("hello [af_heart]: how are you") is False


def test_detect_empty_text():
    assert dlg.detect_dialogue("") is False
    assert dlg.detect_dialogue("   \n\n") is False


# ---------------------------------------------------------------------------
# Whitespace tolerance / CRLF
# ---------------------------------------------------------------------------

def test_crlf_line_endings_supported():
    text = "[af_heart]: Hi.\r\n[am_adam]: Hey.\r\n"
    segs, _ = dlg.parse_dialogue(text, default_voice="af_heart",
                                 known_voices=KNOWN)
    assert segs == [
        _seg("af_heart", "Hi."),
        _seg("am_adam",  "Hey."),
    ]


def test_indented_marker_is_recognised():
    """Screenplays indent speaker headings one or two spaces. We accept
    leading `[ \t]*` so those round-trip correctly.
    """
    text = "    [af_heart]: Hi.\n        [am_adam]: Hey."
    segs, _ = dlg.parse_dialogue(text, default_voice="af_heart",
                                 known_voices=KNOWN)
    assert segs == [
        _seg("af_heart", "Hi."),
        _seg("am_adam",  "Hey."),
    ]


def test_inner_bracket_whitespace_does_not_match():
    """Real Kokoro voice names are strict `xx_yy` tokens — no inner
    whitespace. We deliberately do NOT accept `[ af_heart ]` because
    that would invite ambiguous parses of in-prose brackets.

    Lines with non-matching brackets fall through to "default voice,
    ordinary continuation", like any other unmarked line.
    """
    text = "[ af_heart ] : Hi."   # voice token has inner whitespace => no match
    segs, warns = dlg.parse_dialogue(text, default_voice="xx_voice",
                                     known_voices=KNOWN)
    # No marker matched -> whole line is one default-voice segment.
    assert segs == [_seg("xx_voice", "[ af_heart ] : Hi.")]
    assert warns == []


def test_marker_with_multiline_per_speaker_preserves_newlines():
    text = "[af_heart]: line one\nline two\nline three\n[am_adam]: short."
    segs, _ = dlg.parse_dialogue(text, default_voice="af_heart",
                                 known_voices=KNOWN)
    assert segs[0].text == "line one\nline two\nline three"
    assert segs[1].text == "short."


# ---------------------------------------------------------------------------
# summarize_voices helper
# ---------------------------------------------------------------------------

def test_summarize_voices_no_duplicates():
    segs = [_seg("af_heart"), _seg("am_adam"), _seg("af_heart")]
    assert dlg.summarize_voices(segs) == "af_heart, am_adam"


def test_summarize_voices_truncates_long_lists():
    segs = [_seg(f"v{i}") for i in range(6)]
    out = dlg.summarize_voices(segs)
    assert out.startswith("v0, v1, v2, v3, ")
    assert "+2 more" in out


def test_summarize_voices_empty():
    assert dlg.summarize_voices([]) == ""
    assert dlg.summarize_voices([]) == ""


# ---------------------------------------------------------------------------
# Dataclass behaviour
# ---------------------------------------------------------------------------

def test_dialogue_segment_is_frozen_dataclass():
    s = dlg.DialogueSegment(voice="af_heart", text="Hi.")
    with pytest.raises((AttributeError, Exception)):
        s.voice = "am_adam"  # type: ignore[misc]


def test_chunk_idx_gap_sentinel_is_minus_one():
    """`CHUNK_IDX_GAP` is shared with the engine as the cross-segment
    silence padding marker — make sure it didn't drift.
    """
    assert dlg.CHUNK_IDX_GAP == -1
