# -*- coding: utf-8 -*-
"""Unit tests for `kokoro_studio.ssml` (Phase 2 SSML-lite Controls).

These tests intentionally do NOT load PySide6, the Kokoro pipeline,
or the user-installed preferences dir.  They are pure-parser tests
driven by a small handful of scripts covering all three supported
tags, all the recognised attribute forms, and the lenient
degradation paths.

Stylistically mirrors `tests/test_blending.py` for documentation
cross-reference: dataclass + frozen-style contract, import-order
stable across PySide6 / pytest versions.
"""

from __future__ import annotations

import pytest

from kokoro_studio import ssml
from kokoro_studio.ssml import (
    DEFAULT_EMPHASIS_SPEED_MULT,
    RATE_ALIASES,
    SSMLSegment,
    detect_ssml,
    parse_ssml,
    summarize_ssml,
)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_ssml_module_imports():
    assert hasattr(ssml, "SSMLSegment")
    assert hasattr(ssml, "parse_ssml")
    assert hasattr(ssml, "detect_ssml")
    assert hasattr(ssml, "summarize_ssml")
    assert hasattr(ssml, "DEFAULT_EMPHASIS_SPEED_MULT")
    assert 0.0 < DEFAULT_EMPHASIS_SPEED_MULT < 1.5  # not too aggressive


def test_default_emphasis_speed_mult_is_slow_down():
    """Emphasis should read slower, not faster, so the word draws weight."""
    assert DEFAULT_EMPHASIS_SPEED_MULT < 1.0


def test_rate_aliases_cover_slow_to_x_fast():
    assert sorted(RATE_ALIASES.keys()) == ["fast", "medium", "slow", "x-fast", "x-slow"]
    assert RATE_ALIASES["slow"] < 1.0 < RATE_ALIASES["fast"]
    assert RATE_ALIASES["x-slow"] < RATE_ALIASES["slow"]
    assert RATE_ALIASES["x-fast"] > RATE_ALIASES["fast"]


# ---------------------------------------------------------------------------
# SSMLSegment dataclass
# ---------------------------------------------------------------------------


def test_segment_is_frozen():
    """SSMLSegment is a frozen record — the same shape as VoiceBlend."""
    seg = SSMLSegment(kind="text", text="hello")
    with pytest.raises((AttributeError, Exception)):
        seg.kind = "break"


def test_segment_classmethods_return_canonical_shape():
    """The four factory classmethods lock in the field shape used downstream."""
    assert SSMLSegment.text_only("hi").kind == "text"
    assert SSMLSegment.text_only("hi").speed_mult == 1.0
    assert SSMLSegment.pause(0.5).kind == "break"
    assert SSMLSegment.pause(0.5).duration_s == 0.5
    assert SSMLSegment.emphasised("hi").kind == "emphasis"
    assert SSMLSegment.emphasised("hi").speed_mult == DEFAULT_EMPHASIS_SPEED_MULT
    assert SSMLSegment.prosody("hi", 0.8).kind == "prosody"
    assert SSMLSegment.prosody("hi", 0.8).speed_mult == 0.8


# ---------------------------------------------------------------------------
# parse_ssml — happy paths
# ---------------------------------------------------------------------------


def test_parse_plain_text_yields_single_text_segment():
    segs = parse_ssml("hello world")
    assert segs == [SSMLSegment(kind="text", text="hello world", speed_mult=1.0)]


def test_parse_empty_string_returns_empty_list():
    assert parse_ssml("") == []
    # `parse_ssml(None)` is also allowed because ``not None`` is True
    # at the top of the function — guards against accidental ``None``
    # drift when callers route through falsy data sources.
    assert parse_ssml(None) == []  # type: ignore[arg-type]  # noqa: WPS421


def test_parse_single_break_only():
    segs = parse_ssml('<break time="0.5s"/>')
    assert segs == [SSMLSegment(kind="break", duration_s=0.5)]


def test_parse_text_then_break():
    segs = parse_ssml('hello<break time="1s"/>world')
    assert segs == [
        SSMLSegment(kind="text", text="hello"),
        SSMLSegment(kind="break", duration_s=1.0),
        SSMLSegment(kind="text", text="world"),
    ]


def test_parse_emphasis_wraps_text():
    segs = parse_ssml("<emphasis>read</emphasis> this")
    assert segs == [
        SSMLSegment(kind="emphasis", text="read",
                    speed_mult=DEFAULT_EMPHASIS_SPEED_MULT),
        SSMLSegment(kind="text", text=" this"),
    ]
    # Verify the emphasis got the default speed multiplier (sanity).
    assert segs[0].speed_mult == DEFAULT_EMPHASIS_SPEED_MULT


def test_parse_prosody_with_alias():
    """`<prosody rate="slow">` becomes a prosody segment with the slow multiplier."""
    segs = parse_ssml("<prosody rate=\"slow\">carefully now</prosody>")
    assert len(segs) == 1
    assert segs[0].kind == "prosody"
    assert segs[0].text == "carefully now"
    assert segs[0].speed_mult == RATE_ALIASES["slow"]
    assert segs[0].speed_mult < 1.0


def test_parse_prosody_with_numeric_rate():
    segs = parse_ssml('<prosody rate="0.8">shh</prosody>')
    assert segs[0].kind == "prosody"
    assert segs[0].speed_mult == 0.8


def test_parse_prosody_with_percentage_rate():
    segs = parse_ssml('<prosody rate="75%">quieter</prosody>')
    assert segs[0].kind == "prosody"
    assert segs[0].speed_mult == pytest.approx(0.75)


def test_parse_mixed_tags_preserve_source_order():
    segs = parse_ssml(
        'first <emphasis>second</emphasis> '
        '<prosody rate="slow">third</prosody> '
        '<break time="1.5s"/> '
        'fourth'
    )
    kinds = [s.kind for s in segs]
    assert kinds == ["text", "emphasis", "prosody", "break", "text"]
    assert segs[3].duration_s == 1.5


# ---------------------------------------------------------------------------
# Break-time attribute parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('<break time="1.5s"/>', 1.5),
        ('<break time="500ms"/>', 0.5),
        ('<break time="2000ms"/>', 2.0),
        ('<break time="2"/>', 2.0),
        ('<break time="2s"/>', 2.0),
        # No time attribute => W3C default of 1s.
        ('<break/>', 1.0),
        ('<break>', 1.0),
    ],
)
def test_parse_break_time_units(raw, expected):
    segs = parse_ssml(raw)
    assert len(segs) == 1
    assert segs[0].kind == "break"
    assert segs[0].duration_s == pytest.approx(expected)


def test_parse_break_negative_or_garbage_drops_segment():
    """Negative or unparseable time values drop the break silently."""
    assert parse_ssml('<break time="-1s"/>') == []
    assert parse_ssml('<break time="abc"/>') == []
    # Note: pre-existing text is still preserved.
    segs = parse_ssml('hello<break time="abc"/>world')
    assert [s.kind for s in segs] == ["text", "text"]


def test_parse_break_zero_duration_drops_segment():
    """Zero-duration breaks are pointless and silently dropped."""
    assert parse_ssml('<break time="0s"/>') == []
    # But "bare" <break/> defaults to 1s (W3C) and IS retained.
    assert parse_ssml('<break/>') == [SSMLSegment(kind="break", duration_s=1.0)]


# ---------------------------------------------------------------------------
# Rate attribute parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias,mult",
    list(RATE_ALIASES.items()),
)
def test_parse_prosody_with_all_rate_aliases(alias, mult):
    segs = parse_ssml(f"<prosody rate=\"{alias}\">x</prosody>")
    assert segs[0].speed_mult == pytest.approx(mult)


def test_parse_prosody_missing_rate_attr_means_no_speed_change():
    """`<prosody>foo</prosody>` (no rate) is treated as plain prosody
    wrapping with the default 1.0 multiplier — a no-op for the engine."""
    segs = parse_ssml("<prosody>x</prosody>")
    assert segs[0].kind == "prosody"
    assert segs[0].speed_mult == 1.0


def test_parse_prosody_garbage_rate_falls_back_to_one():
    """Unrecognised rate → 1.0, not a crash."""
    segs = parse_ssml('<prosody rate="definitely-not-a-rate">x</prosody>')
    assert segs[0].speed_mult == 1.0


def test_parse_prosody_negative_numeric_falls_back_to_one():
    segs = parse_ssml('<prosody rate="-0.5">x</prosody>')
    assert segs[0].speed_mult == 1.0


# ---------------------------------------------------------------------------
# Lenient error handling
# ---------------------------------------------------------------------------


def test_parse_unclosed_emphasis_does_not_lose_the_text():
    """A malformed `<emphasis>x` (no close) should still emit the
    wrapped text as an emphasis segment — lenient fallback."""
    segs = parse_ssml("<emphasis>hello world")
    assert len(segs) == 1
    assert segs[0].kind == "emphasis"
    assert segs[0].text == "hello world"
    assert segs[0].speed_mult == DEFAULT_EMPHASIS_SPEED_MULT


def test_parse_unknown_tag_preserved_verbatim_in_text():
    """A tag with an unrecognised NAME is preserved verbatim (including
    its angle brackets) so the user can spot typos on review.  Inner
    text content survives as part of the surrounding text segment —
    we don't try to "extract" it the way a DOM parser would.

    This matches the lenient philosophy of ``dialogue.parse_dialogue``
    (unknown tokens become plain text) but is one step more paranoid:
    we keep the raw tag so the user can see "oh, I wrote ``<emphassis>``".
    """
    segs = parse_ssml('hello <unknown>world</unknown> end')
    text_concat = "".join(s.text for s in segs if s.kind == "text")
    # Both the opening and closing unknown brackets are preserved.
    assert "<unknown>" in text_concat
    assert "</unknown>" in text_concat
    assert "hello" in text_concat
    assert "world" in text_concat
    assert "end" in text_concat


def test_parse_unmatched_close_is_tolerated():
    """`</emphasis>` with no matching open is silently dropped."""
    segs = parse_ssml('hello </emphasis> world')
    # Both halves of the text should still be present.
    text_concat = "".join(s.text for s in segs if s.kind == "text")
    assert "hello" in text_concat
    assert "world" in text_concat


def test_parse_attribute_with_single_quotes():
    """`<break time='1s'/>` (single quotes) is accepted just like double-quotes."""
    segs = parse_ssml("<break time='0.75s'/>")
    assert segs[0].duration_s == pytest.approx(0.75)


def test_parse_whitespace_preserved_in_text_segments():
    """Manual spacing is meaningful — the parser must not strip it."""
    segs = parse_ssml("hello   world")
    assert segs[0].text == "hello   world"


def test_parse_empty_prosody_drops_empty_segment():
    segs = parse_ssml("<prosody rate=\"slow\"></prosody>")
    # No text, so nothing flushes — the tag becomes a no-op.
    assert segs == []


# ---------------------------------------------------------------------------
# detect_ssml
# ---------------------------------------------------------------------------


def test_detect_returns_false_for_plain_text():
    assert detect_ssml("just a regular sentence.") is False


def test_detect_returns_true_for_break_tag():
    assert detect_ssml('hi <break time="1s"/> there') is True


def test_detect_returns_true_for_emphasis_tag():
    assert detect_ssml("<emphasis>hi</emphasis>") is True


def test_detect_returns_true_for_prosody_tag():
    assert detect_ssml('<prosody rate="slow">hi</prosody>') is True


def test_detect_handles_empty_and_none():
    assert detect_ssml("") is False
    assert detect_ssml(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# summarize_ssml (chip text)
# ---------------------------------------------------------------------------


def test_summarize_returns_empty_string_for_no_segments():
    assert summarize_ssml([]) == ""
    assert summarize_ssml([SSMLSegment(kind="text", text="plain")]) == ""


def test_summarize_single_break():
    assert summarize_ssml([SSMLSegment(kind="break", duration_s=1.0)]) == "1 break"


def test_summarize_pluralises_breaks():
    assert (
        summarize_ssml([
            SSMLSegment(kind="break", duration_s=1.0),
            SSMLSegment(kind="break", duration_s=0.5),
        ])
        == "2 breaks"
    )


def test_summarize_mixed_kinds_separated_by_middle_dot():
    segs = [
        SSMLSegment(kind="text", text="x "),
        SSMLSegment(kind="break", duration_s= consumer if False else 1.0),
        SSMLSegment(kind="emphasis", text="y"),
        SSMLSegment(kind="prosody", text="z", speed_mult=0.8),
    ]
    assert summarize_ssml(segs) == "1 break · 1 emphasis · 1 prosody"


def test_summarize_drops_text_segments():
    """`summarize_ssml` only renders the structural counts — text is hidden."""
    segs = [
        SSMLSegment(kind="text", text="hello"),
        SSMLSegment(kind="text", text="world"),
        SSMLSegment(kind="emphasis", text="!"),
    ]
    assert summarize_ssml(segs) == "1 emphasis"


# ---------------------------------------------------------------------------
# Round-trip robustness — parser + summarize via a few realistic scripts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script,expected_kinds",
    [
        ("hello world.", ["text"]),
        (
            '<break time="0.4s"/> Only <emphasis>after</emphasis> a pause.',
            ["break", "text", "emphasis", "text"],
        ),
        (
            'A long sentence... <break time="1s"/> <prosody rate="slow">then pause, slow down, recover.</prosody> end.',
            ["text", "break", "prosody", "text"],
        ),
    ],
)
def test_realistic_scripts_yield_expected_order(script, expected_kinds):
    segs = parse_ssml(script)
    assert [s.kind for s in segs] == expected_kinds


def test_emphasis_inside_prosody_flattens_explicitly():
    """The Phase-2 spec says SSML-lite is *flat* — no nesting. We don't
    test nesting semantics here; we test that the linear walk still
    produces a stable order when tags are not nested."""
    segs = parse_ssml('a <emphasis>b</emphasis> c <prosody rate="fast">d</prosody> e')
    assert [s.kind for s in segs] == ["text", "emphasis", "text", "prosody", "text"]



# ---------------------------------------------------------------------------
# Defensive tests added in response to the code-review pass.
# ---------------------------------------------------------------------------


def test_parse_back_to_back_breaks_keeps_two_separate_segments():
    """Two adjacent `<break>` tags should remain TWO pause segments."""
    segs = parse_ssml('<break time="0.5s"/><break time="0.3s"/>')
    assert len(segs) == 2
    assert segs[0].kind == "break" and segs[0].duration_s == pytest.approx(0.5)
    assert segs[1].kind == "break" and segs[1].duration_s == pytest.approx(0.3)


def test_parse_handles_none_input_explicitly():
    assert parse_ssml(None) == []  # type: ignore[arg-type]


def test_parse_unicode_text_inside_tags_round_trip():
    segs = parse_ssml("<prosody rate=\"slow\">café — naïvely</prosody>")
    assert len(segs) == 1
    assert segs[0].kind == "prosody"
    assert segs[0].text == "café — naïvely"
    assert segs[0].speed_mult == RATE_ALIASES["slow"]


def test_speed_mult_is_clamped_to_safe_band():
    from kokoro_studio.ssml import SPEED_MULT_MAX, SPEED_MULT_MIN
    segs = parse_ssml('<prosody rate="10.0">shrill</prosody>')
    assert segs[0].speed_mult == SPEED_MULT_MAX
    segs = parse_ssml('<prosody rate="0.01">mumble</prosody>')
    assert segs[0].speed_mult == SPEED_MULT_MIN


def test_parse_emits_stderr_warning_for_garbled_break_time(capsys):
    parse_ssml('<break time="abc"/>')
    captured = capsys.readouterr()
    assert "SSML-lite" in captured.err
    assert "dropping" in captured.err.lower()
