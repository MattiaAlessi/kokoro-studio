# -*- coding: utf-8 -*-
"""Phase 2 — SSML-lite Controls.

A *deliberately tiny* subset of SSML is parsed here:

* ``<break time="1.5s"/>``        — insert silence (parsed units: ``s``
  seconds, ``ms`` milliseconds, no-unit defaults to seconds, plus a
  bare integer like ``2``).
* ``<emphasis>word</emphasis>``   — apply a slight slow-down to draw
  attention to the wrapped text (we use a 0.9× speed multiplier; see
  ``DEFAULT_EMPHASIS_SPEED_MULT``).
* ``<prosody rate="...">text</prosody>``
  — override the per-segment speed multiplier. Accepts both numeric
  (``0.8``, ``1.5``, ``"120%"``) and alias (``slow``, ``medium``,
  ``fast``, ``x-slow``, ``x-fast``) values.

The engine treats each tag through a single ``SSMLSegment`` dataclass
(see ``kokoro_studio.engine.generate_speech``'s ``apply_ssml`` kwarg
for the integration). This module is intentionally import-light so it
can be unit-tested without PullSide6, PyTorch, or Kokoro installed.

Why a custom parser rather than ``ssml-parser`` / ``lxml``?
    * The whole feature is text-preprocessing plus chunk silencing,
      so the parser only needs to recover an *ordered list* of
      segments — not a DOM tree.
    * Avoiding an external dep keeps the install footprint zero
      (important for an offline desktop app) and keeps the parser
      predictable for the user (no surprise normalisation).
    * Lenient: malformed tags, unrecognised tag names, and orphan
      open tags all degrade gracefully — none of them crash the
      parser. Unknown tag names are *preserved in text* so the
      user can see typos in their script rather than silently lose
      them; orphan open tags stay open until end-of-script so the
      audio doesn't suddenly go quiet.

Whitespace-only text segments that sit purely between two tags are
*dropped*: visual indentation shouldn't produce a phantom empty
chunk in the output. Same effect on the audio, cleaner segment list.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import List, Optional


# ---------------------------------------------------------------------------
# Speed multipliers
# ---------------------------------------------------------------------------
#
# Picked to match the Kokoro Studio PLAN.md spec ("adjust speed per
# segment") without producing robotic speech.  ``x-slow``/``x-fast`` are
# kept as escape hatches; values outside ``[SPEED_MIN, SPEED_MAX]``
# are clamped at the engine layer before reaching Kokoro.

DEFAULT_EMPHASIS_SPEED_MULT: float = 0.9  # simulate emphasis with a slight slow-down

# Paranoia band on the PARSER side: even if a user writes
# ``rate="10.0"`` the produced ``speed_mult`` doesn't go above
# ``SPEED_MULT_MAX`` (a multiplier on top of the base speed).
# Without this, a typo could x4 the speech rate silently.
SPEED_MULT_MIN: float = 0.25
SPEED_MULT_MAX: float = 2.5

# SSML uses these named-rate aliases.  We align with the W3C SSML
# "Voice / Prosody" convention rather than inventing our own names —
# users familiar with full SSML get exactly the same expectations.
RATE_ALIASES: dict = {
    "x-slow":  0.5,
    "slow":    0.75,
    "medium":  1.0,
    "fast":    1.5,
    "x-fast":  1.75,
}


# ---------------------------------------------------------------------------
# Segment model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SSMLSegment:
    """One element of a parsed SSML-lite script.

    Attributes:
        kind:       One of ``'text'``, ``'break'``, ``'emphasis'``,
                    ``'prosody'``.  Discriminator for the engine's
                    per-segment dispatch.
        text:       The literal text content (only set for ``text``,
                    ``'emphasis'``, ``'prosody'`` segments; empty for
                    ``'break'``).
        duration_s: Pause length in seconds.  Only meaningful for
                    ``'break'`` segments.
        speed_mult: Per-segment speed multiplier applied on top of
                    the global ``speed=`` argument passed to
                    Kokoro.  Defaults to 1.0 (no change); ``<emphasis>``
                    sets it to 0.9; ``<prosody>`` overrides via
                    ``rate=...``.
    """

    kind: str
    text: str = ""
    duration_s: float = 0.0
    speed_mult: float = 1.0

    @classmethod
    def text_only(cls, text: str) -> "SSMLSegment":
        return cls(kind="text", text=text, speed_mult=1.0)

    @classmethod
    def pause(cls, duration_s: float) -> "SSMLSegment":
        return cls(kind="break", duration_s=float(duration_s))

    @classmethod
    def emphasised(cls, text: str) -> "SSMLSegment":
        return cls(kind="emphasis", text=text, speed_mult=DEFAULT_EMPHASIS_SPEED_MULT)

    @classmethod
    def prosody(cls, text: str, mult: float) -> "SSMLSegment":
        return cls(kind="prosody", text=text, speed_mult=float(mult))


# ---------------------------------------------------------------------------
# Tag regex
# ---------------------------------------------------------------------------
#
# Matches ALL tags (known or unknown) with the same shape so we can
# walk the document linearly.  Unknown tag names are flagged via
# ``m.group(2)`` and treated as plain text rather than raising.  The
# ``[^>]*?`` is lazy so a malformed tag with an embedded ``>`` doesn't
# swallow the rest of the script.
TAG_RE = re.compile(
    r"<(/?)(\w+)\b([^>]*?)(/?)>",
    flags=re.IGNORECASE | re.DOTALL,
)

# Whitespace-only check used to drop visual-only text segments that
# sit purely between two tags.  ``str.strip()`` returns truthy on
# non-empty strings, so the negation `str.strip() == ""` is the
# canonical way to test "this is whitespace-only or empty".
_WHITESPACE_ONLY = lambda s: isinstance(s, str) and s.strip() == ""


# ---------------------------------------------------------------------------
# Attribute parsing
# ---------------------------------------------------------------------------


def _attr_value(attrs: str, name: str) -> Optional[str]:
    """Extract ``name``'s value from a raw attribute string.

    Supports both double- and single-quoted values; case-sensitive for
    the attribute *name*.  Returns ``None`` if the attribute is
    absent, which lets the caller apply its own default.
    """
    m = re.search(rf'\b{re.escape(name)}\s*=\s*"([^"]*)"', attrs)
    if m is not None:
        return m.group(1)
    m = re.search(rf"\b{re.escape(name)}\s*=\s*'([^']*)'", attrs)
    if m is not None:
        return m.group(1)
    return None


def _parse_break_time(raw_attrs: str) -> float:
    """Parse ``<break time="...">`` into seconds.

    Accepts:

    * ``"1.5s"``   → 1.5
    * ``"500ms"``  → 0.5
    * ``"2"``      → 2.0 (bare integer, default unit is seconds)
    * Missing     → 1.0 (the W3C default)

    Returns 0.0 for unparseable input AND emits a stderr warning so
    the user can see the typo rather than silently lose a pause.
    """
    val = _attr_value(raw_attrs, "time")
    if val is None or val == "":
        return 1.0
    s = val.strip().lower()
    seconds: Optional[float]
    if s.endswith("ms"):
        try:
            seconds = float(s[:-2]) / 1000.0
        except ValueError:
            seconds = None
    elif s.endswith("s"):
        try:
            seconds = float(s[:-1])
        except ValueError:
            seconds = None
    else:
        try:
            seconds = float(s)
        except ValueError:
            seconds = None

    if seconds is None or seconds < 0.0:
        print(
            f"[Kokoro] SSML-lite: dropping <break time=\"{val}\"/> \u2014 "
            f"unparseable time value.",
            file=sys.stderr,
        )
        return 0.0
    return seconds


def _parse_rate(raw: str) -> float:
    """Parse ``<prosody rate="...">`` into a speed multiplier.

    Accepts:

    * Aliases (``slow``/``medium``/``fast``/``x-slow``/``x-fast``).
    * Bare numbers (``0.8``, ``1.5``).
    * Percentages (``"75%"``, ``"120%"``).

    Returns ``1.0`` for anything unparseable so a typo can't accelerate
    or decelerate speech past the engine's safe bounds.  The result is
    then clamped to ``[SPEED_MULT_MIN, SPEED_MULT_MAX]`` so extreme
    author-typed values (e.g. ``rate="10.0"``) still compose sanely
    with the engine's outer ``speed=`` argument.
    """
    s = raw.strip().lower()
    parsed: float
    if s in RATE_ALIASES:
        parsed = RATE_ALIASES[s]
    elif s.endswith("%"):
        try:
            pct = float(s[:-1])
            parsed = pct / 100.0
        except ValueError:
            parsed = 1.0
    else:
        try:
            v = float(s)
            parsed = v if v > 0 else 1.0
        except ValueError:
            parsed = 1.0
    if parsed < SPEED_MULT_MIN:
        return SPEED_MULT_MIN
    if parsed > SPEED_MULT_MAX:
        return SPEED_MULT_MAX
    return parsed


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_KNOWN_TAGS = frozenset({"emphasis", "prosody", "break"})


def parse_ssml(text: str) -> List[SSMLSegment]:
    """Parse SSML-lite markup in ``text`` into an ordered segment list.

    Lenient design contract:

    * Self-closing (`<break .../>`) and XHTML-style (`<break ...>`)
      breaks are both accepted.
    * Unrecognised tag names are **preserved in text** (not stripped)
      so the user can see typos in their script.  Angle brackets are
      kept verbatim — see the rationale note below.
    * Opening tags without a matching close are tolerated: any text
      written after the orphan open accumulates as if the tag were
      still active until end-of-script.
    * Whitespace-only text segments that sit purely between two tags
      are **dropped**, since visual indentation shouldn't produce a
      phantom empty chunk in the engine's output.

    Returns:
        A list of ``SSMLSegment`` in source order.  Empty input
        returns an empty list; an all-text script returns one
        ``SSMLSegment(kind='text', text=...)`` element.
    """
    if not text:
        return []

    segments: List[SSMLSegment] = []
    buf: List[str] = []           # accumulated text chunks for the active segment
    stack: List = []              # each entry: (tag_kind, speed_mult)

    def _flush_buf(*, force: bool = False) -> None:
        """Move the current text-buffer into a segment.

        ``force=True`` keeps whitespace-only buffers (used for unknown
        tag ranges so their literal brackets aren't dropped).  The
        default path drops whitespace-only buffers since visual
        indentation between two tags adds no audible content.
        """
        text_content = "".join(buf)
        buf.clear()
        if not text_content:
            return
        if not force and _WHITESPACE_ONLY(text_content):
            # Visual-only chunk between tags — drop it.
            return
        if stack:
            top_kind, top_mult = stack[-1]
            if top_kind == "emphasis":
                segments.append(SSMLSegment.emphasised(text_content))
            elif top_kind == "prosody":
                segments.append(SSMLSegment.prosody(text_content, top_mult))
            else:
                segments.append(SSMLSegment(kind=top_kind, text=text_content,
                                            speed_mult=top_mult))
        else:
            segments.append(SSMLSegment.text_only(text_content))

    cursor = 0
    for m in TAG_RE.finditer(text):
        # Text BEFORE this tag — flush gracefully so any pre-tag whitespace
        # is dropped before we accumulate the post-tag content.
        if m.start() > cursor:
            buf.append(text[cursor:m.start()])
            _flush_buf()

        is_close = bool(m.group(1))
        tag = m.group(2).lower()
        attrs_str = (m.group(3) or "").strip()
        cursor = m.end()

        if tag not in _KNOWN_TAGS:
            # Lenient fallback: unknown tags are preserved verbatim in the
            # surrounding text so the user can spot them on review.  We
            # mark the buffer as "pinned" so the next non-empty flush
            # doesn't drop this bracket range as whitespace-only.
            buf.append(m.group(0))
            _flush_buf(force=True)
            continue

        if tag == "break":
            duration = _parse_break_time(attrs_str)
            if duration > 0.0:
                segments.append(SSMLSegment.pause(duration))
            continue

        if is_close:
            # Closing </emphasis> or </prosody>: flush the buffered
            # text into a segment tagged with whatever was at the
            # top of the stack.
            _flush_buf()
            if stack:
                stack.pop()
            continue

        # Opening <emphasis> / <prosody ...>: flush any buffered text
        # BEFORE the tag (so a run of plain text ends cleanly), then
        # push the new tag onto the stack.
        _flush_buf()
        if tag == "emphasis":
            stack.append(("emphasis", DEFAULT_EMPHASIS_SPEED_MULT))
        elif tag == "prosody":
            rate_raw = _attr_value(attrs_str, "rate")
            mult = (
                _parse_rate(rate_raw)
                if rate_raw is not None
                else 1.0
            )
            stack.append(("prosody", mult))

    # Trailing text.
    if cursor < len(text):
        buf.append(text[cursor:])
    _flush_buf()
    # An unclosed tag at end-of-script doesn't generate a phantom
    # segment — the buffered text has already been flushed under
    # the tag's kind by the loop above, which is the desired
    # lenient behaviour (see module docstring).
    return segments


def detect_ssml(text: str) -> bool:
    """Return True if ``text`` contains any recognised SSML-lite tag.

    Cheap pre-check used by the GUI chip / engine auto-router to
    decide whether SSML parsing should fire at all.  Cost: one
    regex pass over the script.
    """
    if not text:
        return False
    return bool(TAG_RE.search(text))


# ---------------------------------------------------------------------------
# Chip summary (used by the GUI)
# ---------------------------------------------------------------------------


def summarize_ssml(segments: List[SSMLSegment]) -> str:
    """Return a short chip-friendly summary string for ``segments``.

    Example::

        summarize_ssml([
            SSMLSegment(kind="text", text="foo"),
            SSMLSegment(kind="break", duration_s=0.5),
            SSMLSegment(kind="emphasis", text="bar"),
        ])
        # → '1 break · 1 emphasis'

    Used to render the inline SSML chip in the editor pane (parallel
    to ``dialogue.summarize_voices``).  Empty / text-only input
    returns an empty string so the caller can hide the chip.
    """
    if not segments:
        return ""
    counts: dict = {"break": 0, "emphasis": 0, "prosody": 0}
    for seg in segments:
        if seg.kind in counts:
            counts[seg.kind] += 1
    parts = []
    if counts["break"]:
        parts.append(
            f"{counts['break']} break{'s' if counts['break'] != 1 else ''}"
        )
    if counts["emphasis"]:
        parts.append(f"{counts['emphasis']} emphasis")
    if counts["prosody"]:
        parts.append(f"{counts['prosody']} prosody")
    return " · ".join(parts) if parts else ""
