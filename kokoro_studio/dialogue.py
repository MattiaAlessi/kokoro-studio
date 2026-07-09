# -*- coding: utf-8 -*-
"""Multi-Speaker Dialogue parser for Kokoro Studio.

Public API:
    DialogueSegment            — dataclass (voice, text)
    parse_dialogue(text, ...)  — returns (List[DialogueSegment], List[str] warnings)
    detect_dialogue(text, ...) — cheap boolean precheck used by the GUI

Syntax (one marker per line at the START — leading whitespace allowed):

    [af_heart]: Hello there!
    This is a continuation in the same voice.
    [am_adam]: Hi!

Slash the marker at the start of a line (optionally indented) and anything
after the colon (and any whitespace following it) becomes the segment's
opening line. Subsequent lines WITHOUT a marker belong to the most recent
voice — this matches screenplay / script convention so a single tag
covers an entire multi-line speaker turn.

Lines BEFORE the first marker are spoken in `default_voice` (so users can
have narration + tagged dialogue in the same script).

Key design decisions
--------------------
* **Line-based parsing**. We split on `\\n` (after stripping any trailing
  whitespace) so the parser handles CRLF transparently — pasting from
  Windows editors / Notepad doesn't break it. Leading-tab vs leading-space
  is tolerated.
* **Permissive marker regex** (`[voice_token]:`). Token is `[A-Za-z_][A-Za-z0-9_]*`
  — matches the `<lang>_<voice>` shape of every Kokoro voice preset
  (`af_heart`, `am_adam`, `bf_isabella`, ...). We don't lock the regex to
  the bundled `VOICES` dict: if the user lists a token that's not yet on
  their version of Kokoro, the parser still recovers cleanly (graceful
  fallback to `default_voice` plus a warning the GUI surfaces).
* **Empty `rest` after colon is OK** — slice goes to current voice and the
  next non-marker lines inherit it. Useful for "speaker turn with body
  written on the next line".
* **`[voice]: text` MUST be at column 0 (modulo leading whitespace)**.
  Bracketed tokens mid-paragraph (e.g. "We use `[af_heart]:` as our
  default") are NOT switched — they're treated as ordinary prose. This
  eliminates accidental activation if the user pastes AI-shaped scripts
  or any text with markdown-y-looking angle brackets.
* **No escape syntax**. If the user really wants literal `[af_heart]:`
  in spoken text, the auto-detect banner in the GUI makes it obvious
  that multi-speaker kicked in; they can uncheck the 🎭 Dialogue mode
  toggle and the brackets will read normally.

This module has zero PySide6 / Kokoro dependencies so it can be unit-tested
in isolation and reused from any future CLI / batch mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Marker pattern. Leading `[ \t]*` allows indented dialogue opening lines
# (screenplay convention). The voice token is restricted to ASCII identifiers
# so we never accidentally match `[am_adam]:` overlapping with random prose
# (which would have spaces / non-ASCII inside the brackets).
_DIALOGUE_MARKER_RE = re.compile(
    r"^[ \t]*\[(?P<voice>[A-Za-z_][A-Za-z0-9_]*)\][ \t]*:[ \t]*(?P<rest>.*)$"
)

# Cheap pre-check pattern (compiled for speed — used in on_textChanged
# slots that fire on every keystroke).
_DIALOGUE_DETECT_RE = re.compile(
    r"^[ \t]*\[[A-Za-z_][A-Za-z0-9_]*\][ \t]*:",
    re.MULTILINE,
)

# Sentinel `chunk_idx` value that the engine passes into the on_chunk
# callback for cross-segment silence padding. Callers use this to
# distinguish "real audio" from "boring gap" if they care to skip it
# (e.g. when computing ETA we count the gap samples; when feeding the
# streaming ring buffer we play through it for a natural pause).
CHUNK_IDX_GAP = -1


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DialogueSegment:
    """One speaker turn in a multi-speaker script.

    Attributes:
        voice: Kokoro voice name (must be a key in `kokoro_studio.engine.VOICES`
               OR `default_voice` if the parser fell back from an unknown name).
        text:  Speech content — already stripped of the `[voice]:` marker
               itself; may contain newlines joining what were once
               multi-line speaker turns on the source side.
    """
    voice: str
    text: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dialogue(
    text: str,
    default_voice: str = "af_heart",
    known_voices: Optional[Set[str]] = None,
) -> Tuple[List[DialogueSegment], List[str]]:
    """Parse `text` into per-voice segments.

    Args:
        text: Source script. Newlines (LF or CRLF) are accepted; line
              orientation is what matters, not line endings.
        default_voice: Voice name used for any unmarked text (i.e. lines
              before the first `[voice]:` marker) and as a fallback for
              any unknown `[voice]:` tokens.
        known_voices: Optional set of valid voice names. When provided,
              any token not in this set triggers a warning string in the
              second return value and is silently coerced to
              `default_voice`. When `None`, all tokens are accepted as-is
              (useful for hosting call sites that don't have the
              engine's catalog to hand).

    Returns:
        (segments, warnings):
            * `segments` is the ordered list of speaker turns; empty iff
              the input had no synthesizable text.
            * `warnings` is a list of human-readable strings that the
              caller can surface via QMessageBox / status bar. Each
              warning describes one unknown voice token encountered.

    Edge cases handled:
        * No markers → returns one segment using `default_voice`.
        * Markers on every line, no body → returns the same number of
          segments but they're dropped if their body is empty.
        * Continuation lines (no marker) join the previous segment's
          text via newline.
        * CRLF or LF line endings → indistinguishable (splitlines
          handles both).
        * Mixed: bracketed markers can appear in any order.
    """
    segments: List[DialogueSegment] = []
    warnings: List[str] = []
    seen_first_marker = False
    cur_voice = default_voice
    cur_lines: List[str] = []

    def _flush() -> None:
        nonlocal cur_voice, cur_lines
        joined = "\n".join(cur_lines).strip()
        cur_lines = []
        if joined:
            segments.append(DialogueSegment(voice=cur_voice, text=joined))

    # `splitlines()` accepts `\n`, `\r\n` and `\r` transparently — no
    # pre-normalisation needed.
    for line in text.splitlines():
        m = _DIALOGUE_MARKER_RE.match(line)
        if m is not None:
            # End the previous segment (if it had content).
            _flush()

            voice = m.group("voice")
            rest = m.group("rest")

            if known_voices is not None and voice not in known_voices:
                warnings.append(
                    f"Unknown voice '{voice}' on line \"{line.strip()[:60]}\""
                    f" — falling back to '{default_voice}'."
                )
                voice = default_voice

            cur_voice = voice
            seen_first_marker = True
            # `rest` is "" when the marker is the whole line — that's a
            # legitimate opening tag with the body on the next line. We
            # start a fresh cur_lines list either way.
            cur_lines = [rest] if rest else []
        elif not seen_first_marker:
            # Pre-first-marker text → uses default_voice implicitly.
            cur_lines.append(line)
        else:
            # Continuation of the most recent speaker.
            cur_lines.append(line)

    # Flush the final accumulated segment (if any).
    _flush()

    return segments, warnings


def detect_dialogue(text: str) -> bool:
    """Return True iff `text` contains at least one parseable marker.

    Cheap O(N×regex-cost) precheck — used in `on_textChanged` handlers
    that fire on every keystroke. Returned value is identical to
    `(len(parse_dialogue(text)[1]) ... )` only because the parser
    produces no segments without markers; a separate regex tuned to the
    marker shape is faster than running the full parser.
    """
    if not text:
        return False
    return _DIALOGUE_DETECT_RE.search(text) is not None


def summarize_voices(segments: List[DialogueSegment]) -> str:
    """Render `segments` as a compact `voice1, voice2, …` summary.

    Used by the GUI speaker badge. Truncates beyond 4 voices so the
    control panel isn't blown out by a 20-character script.

    Example:
        >>> summarize_voices([
        ...     DialogueSegment("af_heart", "..."),
        ...     DialogueSegment("am_adam", "..."),
        ...     DialogueSegment("af_heart", "..."),
        ... ])
        'af_heart, am_adam'
    """
    if not segments:
        return ""
    seen: List[str] = []
    for s in segments:
        if s.voice not in seen:
            seen.append(s.voice)
    if len(seen) <= 4:
        return ", ".join(seen)
    return ", ".join(seen[:4]) + f", … (+{len(seen) - 4} more)"


__all__ = [
    "DialogueSegment",
    "parse_dialogue",
    "detect_dialogue",
    "summarize_voices",
    "CHUNK_IDX_GAP",
]
