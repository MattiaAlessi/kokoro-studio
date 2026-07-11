# -*- coding: utf-8 -*-

"""Kokoro TTS wrapper (hexgrad/Kokoro-82M).

Public API:
    - list_voices(lang=None, gender=None) -> List[str]
    - get_voice_info(voice)               -> Dict[str, str]
    - generate_speech(text, ...)          -> np.ndarray (float32 mono @ 24 kHz)

Supported languages (the catalog ships English voices; non-English lang
codes 'e'/'f'/'h'/'i'/'p' are espeak-ng-backed and use English voices
internally, while 'j'/'z' need separate voice packs):
    a  American English       (misaki[en] built-in)
    b  British English        (misaki[en] built-in)
    j  Japanese               (pip install misaki[ja] + voice pack)
    z  Mandarin Chinese       (pip install misaki[zh] + voice pack)
    e  Spanish                (espeak-ng voice 'es')
    f  French                 (espeak-ng voice 'fr-fr')
    h  Hindi                  (espeak-ng voice 'hi')
    i  Italian                (espeak-ng voice 'it')
    p  Brazilian Portuguese   (espeak-ng voice 'pt-br')

Kokoro-82M ships ~29 English voice presets; the VOICES dict below lists the
full catalog with language / gender / grade / short description.
"""

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Mapping, Optional, Tuple, Union

import numpy as np
import soundfile as sf


if TYPE_CHECKING:
    # Only for type-checkers: at runtime `kokoro` stays lazy (see _get_pipeline).
    from kokoro import KPipeline


# Force UTF-8 on stdout/stderr even on Windows (legacy cp1252 terminals) so that
# non-ASCII characters (->, smart quotes, etc.) don't raise UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Constants: supported languages and voices
# ---------------------------------------------------------------------------

# Mapping: lang_code -> {"label", "requires"}
# Catalog only ships English voices; non-English lang codes ('j'/'z' Japanese
# / Mandarin) need separate voice packs, while 'e'/'f'/'h'/'i'/'p' are
# espeak-ng-backed. Each entry carries:
#   - "label"            : English description (used by voice metadata).
#   - "label_localized"  : Italian description (used by the GUI dropdown).
#   - "requires"         : setup hints shown in the GUI.
LANG_CODES: Dict[str, Dict[str, str]] = {
    "a": {"label": "American English",      "label_localized": "Inglese Americano",      "requires": "misaki[en] built-in"},
    "b": {"label": "British English",       "label_localized": "Inglese Britannico",     "requires": "misaki[en] built-in"},
    "j": {"label": "Japanese",              "label_localized": "Giapponese",             "requires": "pip install misaki[ja]"},
    "z": {"label": "Mandarin Chinese",      "label_localized": "Cinese Mandarino",       "requires": "pip install misaki[zh]"},
    "e": {"label": "Spanish",               "label_localized": "Spagnolo",               "requires": "espeak-ng voice 'es'"},
    "f": {"label": "French",                "label_localized": "Francese",               "requires": "espeak-ng voice 'fr-fr'"},
    "h": {"label": "Hindi",                 "label_localized": "Hindi",                  "requires": "espeak-ng voice 'hi'"},
    "i": {"label": "Italian",               "label_localized": "Italiano",               "requires": "espeak-ng voice 'it'"},
    "p": {"label": "Brazilian Portuguese",  "label_localized": "Portoghese Brasiliano",  "requires": "espeak-ng voice 'pt-br'"},
}

# voice -> (lang_code, gender, grade, description).
# Grades follow Kokoro's internal quality tiers (A = highest, D = baseline).
VOICES: Dict[str, Tuple[str, str, str, str]] = {
    # 🇺🇸 American English (lang 'a') — 21 voices
    "af_alloy":   ("a", "f", "A", "clean, neutral"),
    "af_aoede":   ("a", "f", "A", "young, articulate"),
    "af_bella":   ("a", "f", "A", "young, lively"),
    "af_emma":    ("a", "f", "B", "American English with a British accent"),
    "af_heart":   ("a", "f", "A", "warm, natural (recommended for narration)"),
    "af_jessica": ("a", "f", "A", "crisp, friendly"),
    "af_kore":    ("a", "f", "A", "bright, energetic"),
    "af_nicole":  ("a", "f", "A", "clear, slightly formal"),
    "af_nova":    ("a", "f", "A", "modern, expressive"),
    "af_river":   ("a", "f", "A", "soft, conversational"),
    "af_sarah":   ("a", "f", "A", "calm tone"),
    "af_sky":     ("a", "f", "A", "versatile"),
    "am_adam":    ("a", "m", "D", "American male"),
    "am_echo":    ("a", "m", "D", "American male"),
    "am_eric":    ("a", "m", "D", "American male"),
    "am_fenrir":  ("a", "m", "D", "American male, deeper timbre"),
    "am_liam":    ("a", "m", "D", "American male"),
    "am_michael": ("a", "m", "D", "American male"),
    "am_onyx":    ("a", "m", "D", "American male, deep"),
    "am_puck":    ("a", "m", "D", "American male, playful"),
    "am_santa":   ("a", "m", "D", "American male, warm"),
    # 🇬🇧 British English (lang 'b') — 8 voices
    "bf_alice":    ("b", "f", "B", "British English female"),
    "bf_emma":     ("b", "f", "B", "British English female"),
    "bf_isabella": ("b", "f", "B", "British English female"),
    "bf_lily":     ("b", "f", "B", "British English female"),
    "bm_daniel":   ("b", "m", "B", "British male"),
    "bm_fable":    ("b", "m", "B", "British male"),
    "bm_george":   ("b", "m", "B", "British, deep timbre"),
    "bm_lewis":    ("b", "m", "B", "British male"),
}

DEFAULT_VOICE = "af_heart"
SAMPLE_RATE = 24000  # Kokoro produces audio at 24 kHz
SPEED_MIN = 0.1
SPEED_MAX = 3.0

# Output formats supported when saving audio.
# Order matters: the first entry 'wav' is the GUI default and matches the
# legacy behaviour (uncompressed PCM, largest file). MP3 is encoded with
# the pure-Python `lameenc` package (no FFmpeg dependency). FLAC and OGG
# are written through `soundfile`, which delegates to libsndfile + libFLAC
# + libvorbis — all bundled in the `soundfile` wheel on Windows.
OUTPUT_FORMATS: Tuple[str, ...] = ("wav", "mp3", "flac", "ogg")

# Map file extension -> canonical format name (used by save_audio() when
# the format is inferred from a path). Keeps inference robust against
# accidental uppercase / double-extension edge cases.
_EXT_TO_FORMAT: Dict[str, str] = {
    "wav": "wav",
    "mp3": "mp3",
    "flac": "flac",
    "ogg": "ogg",
}

# Default bitrate (kbps) used for lossy codecs. Keeps files small without
# audibly degrading 24 kHz speech. Exposed as a constant so a future GUI
# slider can dial it without hunting for magic numbers.
MP3_BITRATE_KBPS = 192

# Cross-segment silence inserted by `generate_speech` between
# multi-speaker segments. 0.25 s sounds natural without dragging on a
# long dialogue script; set `speaker_gap_s=0.0` to disable.
_DIALOGUE_DEFAULT_GAP_S = 0.25

# Default JSON file for persisted voice-blend presets (Phase 2). Path
# is anchored at `Documents/KokoroStudio/voice_blends.json` so a
# single grep surfaces the canonical location. The GUI auto-creates
# the parent directory on first save; the engine itself never writes
# here (the GUI owns writes via `blending.save_blends`). READ-ONLY on
# the engine side: lazily loaded via `_ensure_blends_loaded()`.
VOICE_BLENDS_FILENAME = "voice_blends.json"


# ---------------------------------------------------------------------------
# Pipeline cache (KPipeline is heavy to load, reuse it)
# ---------------------------------------------------------------------------
_pipelines: Dict[str, "KPipeline"] = {}

# Voice blend registry (Phase 2 - Voice Blending / Mixing). Lazily
# populated on first `generate_speech` call from the JSON persisted by
# the GUI. CLI scripts that want to bypass disk reads can pass
# `blends=<dict>` directly to `generate_speech` instead.
_loaded_blends: Dict[str, "VoiceBlend"] = {}


def _get_pipeline(lang_code: str) -> "KPipeline":
    """Return (and memoize) the KPipeline for `lang_code`."""
    if lang_code not in LANG_CODES:
        raise ValueError(
            f"lang_code '{lang_code}' is not valid. "
            f"Supported: {sorted(LANG_CODES)}"
        )

    if lang_code not in _pipelines:
        # Lazy import: lets the module be imported even without `kokoro` installed.
        from kokoro import KPipeline

        print(f"[Kokoro] Loading pipeline (lang={lang_code})...", file=sys.stderr)
        _pipelines[lang_code] = KPipeline(lang_code=lang_code)
    return _pipelines[lang_code]


def _get_pipeline_voices(lang_code: str) -> Dict[str, object]:
    """Return the `KPipeline.voices` mapping for `lang_code`.

    Used by the voice-blending path to look up the loaded voice tensors
    (per KVoiceWalk / Kokoro internals, KPipeline populates `.voices`
    with torch.Tensor instances after construction). Returns {} if the
    pipeline doesn't expose a `.voices` attribute (defensive: older or
    futurized Kokoro releases could drop it without telling us).
    """
    pipe = _get_pipeline(lang_code)
    voices = getattr(pipe, "voices", None)
    if voices is None:
        # Fallback: try `voice_pack` or `voicepacks`.
        for alt in ("voice_pack", "voicepacks"):  # noqa: SIM118
            v = getattr(pipe, alt, None)
            if isinstance(v, dict):
                return v
        return {}
    if isinstance(voices, dict):
        return voices  # type: ignore[return-value]
    return {}


def _prime_voice_into_pipeline(lang_code: str, voice_name: str) -> bool:
    """Force Kokoro to materialise `voice_name` in `KPipeline.voices`.

    Kokoro's `KPipeline.voices` dict is populated lazily on the FIRST
    synthesis call (`pipe(text, voice=X)`) — a freshly-constructed
    pipeline has an empty `.voices` dict. That trips our blend path:
    `compute_blend_tensor(blend, pipeline_voices)` raises a clean
    ``KeyError("voice_a 'X' is not loaded in the current pipeline…")``
    when the user creates a blend using a voice that hasn't been
    synthesised yet (no prior Generate / Preview to warm the pipeline
    up). Most visible with `af_heart`, the default voice — the bug
    surfaces on the FIRST action of a session that goes straight to
    the Blend editor without an init-time Preview.

    We "prime" by issuing a one-chunk synthesis call with a phoneme-
    safe tiny text ("a") — Kokoro's phonemiser accepts the single
    letter as a valid chunk, and we `break` out of the generator after
    the first iteration so the cost is bounded (~50-150 ms per voice).
    Idempotent: an already-loaded voice short-circuits via the
    ``voice_name in pipeline_voices`` membership test, so calling
    prime repeatedly with the same voice is free.

    Returns:
        True if `voice_name` is now in `pipeline.voices` (already
        present OR freshly primed). False if the pipeline doesn't
        expose a `.voices` dict, the voice is unknown to Kokoro (and
        the prime call raises or doesn't insert), or any other failure
        path — callers can fall through to `compute_blend_tensor` so
        the user still gets a precise error message.
    """
    pipe = _get_pipeline(lang_code)
    pv = getattr(pipe, "voices", None)
    if not isinstance(pv, dict):
        return False
    if voice_name in pv:
        return True  # already primed by an earlier Generate / Preview
    try:
        # "a" is a single-letter English-letter input — guaranteed to
        # survive the SentencePiece phonemiser and produce exactly one
        # chunk ("a" → /ɑ/ → ~50 ms of audio). We discard the audio by
        # breaking out of the generator after the first iteration.
        for _ in pipe("a", voice=voice_name):
            break
    except Exception:
        # Prime failed for some reason (unknown voice name, etc.).
        # Returning False lets `compute_blend_tensor`'s downstream
        # validation raise a precise KeyError instead of us masking
        # the real failure with a generic exception.
        return False
    return voice_name in pv


def _ensure_blends_loaded(
    override: Optional[Mapping[str, "VoiceBlend"]] = None,
    blends_path: Optional[Path] = None,
) -> Dict[str, "VoiceBlend"]:
    """Lazy-loader for `voice_blends.json`.

    Priority:
      1. Explicit `override` mapping (CLI / tests bypass disk).
      2. Disk read from `blends_path` (default: `<Documents>/KokoroStudio/voice_blends.json`)
         using `kokoro_studio.blending.load_blends`. Returns {} silently
         when the file is missing or malformed (mirrors pronunciation).

    Side-effect: updates module-level `_loaded_blends` so subsequent
    `generate_speech(voice="my_blend")` calls recognise the name.
    """
    global _loaded_blends
    if override is not None:
        _loaded_blends = dict(override)
        return _loaded_blends

    # Lazy import: blending is shipped with the package, but a headless
    # build (CLI without the deck of extra deps) shouldn't fail at
    # first-import. Mirror the pronunciation import pattern.
    try:
        from kokoro_studio.blending import load_blends
    except ImportError as e:  # pragma: no cover — module bug, not runtime
        print(f"[Kokoro] Voice blending unavailable: {e}", file=sys.stderr)
        _loaded_blends = {}
        return _loaded_blends

    if blends_path is None:
        # Default location: <Documents>/KokoroStudio/voice_blends.json.
        # We re-use the engine's _default_output_dir helper for path
        # resolution so a future change of default folder (e.g. move
        # to AppData on Linux) only has to touch one place.
        try:
            base = Path(_default_output_dir())
        except Exception:
            base = Path.home() / "Documents"
        blends_path = base / VOICE_BLENDS_FILENAME

    _loaded_blends = load_blends(blends_path)
    return _loaded_blends


def _default_output_dir() -> str:  # type: ignore[no-redef]
    """Resolve the default blend-file directory without importing PySide6.

    Lives at module level so `_ensure_blends_loaded` can call it without
    dragging in the GUI. Duplicates the logic in `gui.py`'s
    `_default_output_dir` because importing `kokoro_studio.gui` here
    would create a circular import (gui imports engine).
    """
    # Lazy Qt import: keep engine headless-importable (CLI/tests).
    try:
        from PySide6.QtCore import QStandardPaths  # type: ignore
        docs = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation
        )
    except Exception:
        docs = ""
    base = Path(docs) if docs else Path.home() / "Documents"
    folder = base / "KokoroStudio"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path.cwd()
    return str(folder)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_voices(lang: Optional[str] = None, gender: Optional[str] = None) -> List[str]:
    """List available voices, optionally filtered by language and/or gender.

    The bundled catalog only ships English voices (lang 'a' / 'b'). Filtering
    by any non-English code — espeak-ng-backed ('e' / 'f' / 'h' / 'i' / 'p')
    OR voice-pack-backed ('j' / 'z') — therefore returns [] so the GUI can
    show a "no voices for this language" placeholder. To synthesize a
    foreign language from an English voice you have to explicitly pass
    `lang_code` to `generate_speech` after picking the English voice from
    `lang='a'|'b'|None`.
    """
    if lang is None or lang in {"a", "b"}:
        match_langs = {"a", "b"}
    else:
        # No voices in the bundle for non-English lang codes.
        match_langs = set()
    return sorted(
        v
        for v, (l, g, _g, _d) in VOICES.items()
        if l in match_langs and (gender is None or g == gender)
    )


def get_voice_info(voice: str) -> Dict[str, str]:
    """Return a dict with the metadata of a voice."""
    if voice not in VOICES:
        available = ", ".join(list_voices())
        raise ValueError(f"voice '{voice}' is not recognized. Available: {available}")
    lang, gender, grade, descr = VOICES[voice]
    return {
        "voice": voice,
        "lang": lang,
        "lang_label": LANG_CODES[lang]["label"],
        "gender": gender,
        "grade": grade,
        "description": descr,
    }


def _infer_format_from_path(path: str) -> str:
    """Pick the canonical format name from a file path's suffix.

    Falls back to 'wav' if the path has no recognised extension — this
    matches the original (pre-multiformat) behaviour, so callers that pass
    a bare `output_path` keep working unchanged.
    """
    ext = Path(path).suffix.lower().lstrip(".")
    return _EXT_TO_FORMAT.get(ext, "wav")


def save_audio(
    audio: np.ndarray,
    output_path: str,
    output_format: Optional[str] = None,
) -> None:
    """Persist `audio` (float32 mono @ 24 kHz) to disk in WAV/MP3/FLAC/OGG.

    Args:
        audio:         numpy.ndarray, dtype float32, shape (n,) or (n, 1).
        output_path:   destination file path. Its suffix is used to infer
                       the format when `output_format` is None.
        output_format: optional canonical name (`'wav'|'mp3'|'flac'|'ogg'`).
                       When supplied it overrides the suffix and rejects
                       unknown values with a clear ValueError.

    Raises:
        ValueError:  on an unsupported format string.
        ImportError: if MP3 is requested but `lameenc` isn't installed.
        OSError:     propagated from the underlying writer (disk full,
                     permission denied, etc.).
    """
    if not isinstance(audio, np.ndarray) or audio.dtype != np.float32:
        # Normalize common cases without silently mangling data:
        # - object / list of float → cast
        # - int16 → scale to [-1, 1]
        a = np.asarray(audio)
        if a.dtype == np.int16:
            audio = (a.astype(np.float32) / 32767.0)
        else:
            audio = a.astype(np.float32)

    # Flatten (n, 1) → (n,) — soundfile / lameenc both expect 1-D for mono.
    if audio.ndim == 2 and audio.shape[1] == 1:
        audio = audio.reshape(-1)
    elif audio.ndim != 1:
        raise ValueError(
            f"`audio` must be 1-D mono (got shape {audio.shape})."
        )

    fmt = (
        output_format.lower()
        if output_format is not None
        else _infer_format_from_path(output_path)
    )
    if fmt not in OUTPUT_FORMATS:
        raise ValueError(
            f"Unsupported output format '{fmt}'. "
            f"Supported: {list(OUTPUT_FORMATS)}"
        )

    # Writers below raise OSError themselves on a bad dir, so we don't
    # need a pre-flight check here.

    if fmt == "wav":
        # soundfile writes float WAV headers by default; .wav with PCM int16
        # would compress better, but round-tripping through float32 keeps
        # downstream tooling simple (no clipping on re-read).
        sf.write(output_path, audio, SAMPLE_RATE, subtype="FLOAT")
    elif fmt == "flac":
        sf.write(output_path, audio, SAMPLE_RATE, format="FLAC")
    elif fmt == "ogg":
        # Vorbis is the safe choice at 24 kHz (Opus typically targets 48 kHz).
        sf.write(output_path, audio, SAMPLE_RATE, format="OGG", subtype="VORBIS")
    elif fmt == "mp3":
        try:
            import lameenc  # pure-Python LAME wrapper, no FFmpeg needed
        except ImportError as e:
            raise ImportError(
                "MP3 export requires the `lameenc` package. "
                "Install it with:  pip install lameenc"
            ) from e

        # Clip → int16. TTS output is already roughly in [-1, 1], but rare
        # overshoots happen near boundaries; hard-clipping is the standard
        # choice for LAME and introduces only a handful of samples.
        pcm = np.clip(audio * 32767.0, -32768.0, 32767.0).astype(np.int16)

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(MP3_BITRATE_KBPS)
        encoder.set_in_sample_rate(SAMPLE_RATE)
        encoder.set_channels(1)
        encoder.set_quality(2)  # 0..9, 2 is a good quality/speed sweet spot

        mp3_bytes = encoder.encode(pcm.tobytes()) + encoder.flush()
        with open(output_path, "wb") as f:
            f.write(mp3_bytes)


def generate_speech(
    text: str,
    voice: str = DEFAULT_VOICE,
    lang_code: Optional[str] = None,
    output_path: Optional[str] = None,
    speed: float = 1.0,
    split_pattern: Optional[str] = None,
    on_chunk: Optional["Callable[[int, int, np.ndarray], None]"] = None,
    stop_check: Optional["Callable[[], bool]"] = None,
    output_format: Optional[str] = None,
    pronunciation_rules: Optional[Dict[str, str]] = None,
    multi_speaker: bool = False,
    speaker_gap_s: float = _DIALOGUE_DEFAULT_GAP_S,
    voice_blend: Union["VoiceBlend", Tuple[str, str, float], None] = None,
    blends: Optional[Mapping[str, "VoiceBlend"]] = None,
    apply_ssml: bool = False,
) -> np.ndarray:
    """Synthesize `text` with Kokoro and return the audio (float32) at 24 kHz.

    Args:
        text:          text to synthesize (non-empty).
        voice:         voice name (default: 'af_heart'). See VOICES or list_voices().
                       In multi-speaker mode this is used as the default voice
                       for unmarked lines and as fallback for unknown markers.
        lang_code:     if None, derived from the voice; if specified, must be
                       consistent with the voice (otherwise ValueError).
        output_path:   if specified, save the audio. Format is decided by
                       `output_format` if given, otherwise inferred from the
                       file extension (defaults to WAV for unknown suffixes).
        output_format: optional canonical name (`'wav'|'mp3'|'flac'|'ogg'`).
                       When None, the format is inferred from `output_path`'s
                       suffix (.wav / .mp3 / .flac / .ogg). The legacy
                       call-site behaviour (no format argument → WAV) is
                       fully preserved for compatibility.
        speed:         number in (SPEED_MIN, SPEED_MAX]. 1.0 = normal.
        split_pattern: optional regex to split long text (e.g. r'\\n+').
        on_chunk:      optional callback invoked after every Kokoro chunk with
                       args (segment_index, chunk_index, audio_chunk_ndarray).
                       In single-speaker mode `segment_index` is always 0. In
                       multi-speaker mode it indicates which voice segment
                       produced the chunk (0-based). For the cross-segment
                       silence gap a sentinel `segment_index` is paired with
                       `chunk_index = kokoro_studio.dialogue.CHUNK_IDX_GAP`
                       so consumers that care can distinguish synthetic
                       silence from real audio. The chunk's dtype is
                       float32, mono, at SAMPLE_RATE Hz. Exceptions raised
                       by the callback are logged to stderr and ignored.
        stop_check:    optional callable returning True to request cancellation.
                       Checked after each chunk; if it returns True a
                       RuntimeError("Synthesis cancelled by caller.") is raised
                       *before* writing any output file.
        output_format: optional canonical name (`'wav'|'mp3'|'flac'|'ogg'`).
                       When None, the format is inferred from `output_path`'s
                       suffix (.wav / .mp3 / .flac / .ogg). The legacy
                       call-site behaviour (no format argument → WAV) is
                       fully preserved for compatibility.
        pronunciation_rules: optional `{find: replace}` map applied to the
                       input `text` (or each segment, in multi-speaker mode)
                       BEFORE synthesis (whole-word, case-sensitive,
                       longest-rule-first). Empty / None is a no-op fast
                       path. Lazily imports the `pronunciation` module so
                       users who only ever synthesise without a dict don't
                       need to install anything beyond the engine's
                       baseline deps.
        multi_speaker: if True, parse `[voice_name]: text` markers in `text`
                       (one marker per line, at the start) and synthesise
                       each segment independently. Insert `speaker_gap_s`
                       seconds of silence between segments. Unknown voice
                       tokens fall back to `voice`; warnings are echoed to
                       stderr but synthesis continues so a partial typo
                       doesn't abort the whole script.
        speaker_gap_s: cross-segment silence in multi-speaker mode, in
                       seconds. Set to 0.0 for instant joins. Default is
                       `_DIALOGUE_DEFAULT_GAP_S` (0.25 s — short enough
                       to not feel sluggish, long enough to avoid harsh
                       jump-cuts between voices). Each gap is also fed
                       through `on_chunk` as synthetic silence so the
                       real-time streaming path plays it through.
        voice_blend:  Phase 2 — Voice Blending / Mixing. When set, takes
                       precedence over `voice`: the synthesizer runs with
                       a freshly-computed blend tensor (alpha * voice_a +
                       (1.0 - alpha) * voice_b). Accepts a `VoiceBlend`
                       dataclass OR a `(voice_a, voice_b, alpha)` 3-tuple
                       for ergonomic inline use. Both inputs must name
                       presets already loaded into `KPipeline.voices`,
                       i.e. presets from `engine.VOICES`. The blend is
                       computed lazily and cached internally — the first
                       Generate with a given alpha is the only one that
                       pays the interpolation cost.
        blends:       Phase 2 — pre-loaded blend presets keyed by name.
                       When supplied, overrides the engine's auto-load
                       from disk. CLI scripts pass this to inline a
                       custom blend without touching the persistent
                       JSON file. When `None` (the default) the engine
                       lazily reads `<Documents>/KokoroStudio/voice_blends.json`.
        apply_ssml:   Phase 2 — SSML-lite Controls. When True (opt-in),
                       the text is routed through `kokoro_studio.ssml.parse_ssml`
                       so `<break time="..."/>`, `<emphasis>...</emphasis>`,
                       and `<prosody rate="...">...</prosody>` expand into
                       silence gaps / per-segment speed scaling. Mutually
                       exclusive with `multi_speaker`: if both are set the
                       function silently ignores `apply_ssml` and proceeds
                       with multi-speaker routing (dialogue markers win).
                       Default False for backward compat — the GUI flips it
                       on via a user-facing checkbox.

    Returns:
        numpy.ndarray float32 mono at 24 kHz.

    Raises:
        ValueError:   for invalid input or unsupported output_format.
        ImportError:  if the `kokoro` library is not installed, or if MP3
                       export is requested but `lameenc` is missing.
        RuntimeError: if the pipeline produces no audio, or synthesis was
                       cancelled via `stop_check`.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("`text` must be a non-empty string.")

    # ---- Voice blend pre-processing ------------------------------
    # Voice blending is the FIRST gate because `voice_blend` (when set)
    # takes precedence over the bare `voice` string. We resolve into a
    # concrete tensor here so the rest of the function only has to deal
    # with a single `resolved_voice` value (string OR tensor).
    from kokoro_studio.blending import (
        VoiceBlend,
        _coerce_to_blend,
        compute_blend_tensor,
        resolve_voice_param,
    )
    blend = _coerce_to_blend(voice_blend)
    if blend is not None:
        # Validate blend inputs upfront so the user gets a clean ValueError
        # on a typo rather than a NameError-ish KeyError from the pipeline.
        if blend.voice_a not in VOICES:
            raise ValueError(
                f"voice_blend voice_a '{blend.voice_a}' is not a known "
                f"voice. Available: {', '.join(list_voices())}"
            )
        if blend.voice_b not in VOICES:
            raise ValueError(
                f"voice_blend voice_b '{blend.voice_b}' is not a known "
                f"voice. Available: {', '.join(list_voices())}"
            )
        # Auto-derive lang_code from voice_a (or verify consistency).
        blend_lang = VOICES[blend.voice_a][0]
        if lang_code is None:
            lang_code = blend_lang
        elif lang_code != blend_lang:
            raise ValueError(
                f"voice_blend voice_a '{blend.voice_a}' belongs to lang "
                f"'{blend_lang}', not to '{lang_code}'."
            )
        # Resolve the tensor through the same code path used for the
        # `voice=blend_name` case so caching / pipeline-voice lookup
        # behave identically regardless of how the user invokes.
        pipeline_voices = _get_pipeline_voices(lang_code)
        # Kokoro populates `pipeline.voices` lazily on first synthesis.
        # Pre-warm both blend voices so `compute_blend_tensor` doesn't
        # false-positive on a session that hasn't synthesised them yet
        # (e.g. the FIRST action being a Blend preview with af_heart).
        _prime_voice_into_pipeline(lang_code, blend.voice_a)
        _prime_voice_into_pipeline(lang_code, blend.voice_b)
        resolved_voice = compute_blend_tensor(blend, pipeline_voices)
        _resolved_via_blend = True
    else:
        _resolved_via_blend = False

    # ---- Default-voice gate ---------------------------------------
    # Only run this when we're NOT in ad-hoc blend mode. In blend mode
    # the `voice` string is unused (the tensor is what matters).
    if not _resolved_via_blend:
        # Lazily populate `_loaded_blends`. This MUST happen before the
        # voice-existence check so saved blend names are accepted.
        _ensure_blends_loaded(override=blends)
        valid_voice_names = set(VOICES.keys()) | set(_loaded_blends.keys())
        if voice not in valid_voice_names:
            available = ", ".join(list_voices())
            extra = (
                f" + blends: {sorted(_loaded_blends.keys())}"
                if _loaded_blends else ""
            )
            raise ValueError(
                f"voice '{voice}' is not recognized. "
                f"Available built-in: {available}{extra}"
            )

    # `resolved_voice` may be either a built-in name, a saved blend
    # name, or (above) a tensor. KPipeline accepts all three so we
    # assign once and re-use downstream. For the non-blend-mode path
    # we resolve the saved-blend-name case here too (so the engine
    # transparently supports `[my_blend]:` markers AND
    # `voice="my_blend"` calls).
    if not _resolved_via_blend:
        # Pre-warm the saved-blend's tensor inputs (Kokoro lazy-loads
        # voice tensors on first synthesis; without this, a freshly
        # loaded pipeline raises KeyError on `compute_blend_tensor`
        # when the user picks a saved blend with which they haven't
        # generated anything yet).
        if voice in _loaded_blends:
            _sb_lang = (
                VOICES[voice][0] if voice in VOICES
                else VOICES[_loaded_blends[voice].voice_a][0]
            )
            _prime_voice_into_pipeline(_sb_lang, _loaded_blends[voice].voice_a)
            _prime_voice_into_pipeline(_sb_lang, _loaded_blends[voice].voice_b)
        resolved_voice = resolve_voice_param(
            voice, _loaded_blends, _get_pipeline_voices(
                VOICES[voice][0] if voice in VOICES
                else VOICES[_loaded_blends[voice].voice_a][0]
            ),
        )

    # Type-guard on speed: only accept numbers in (SPEED_MIN, SPEED_MAX]
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) \
            or speed < SPEED_MIN or speed > SPEED_MAX:
        raise ValueError(f"`speed` must be a number in ({SPEED_MIN}, {SPEED_MAX}].")

    # Auto-derive lang_code from the voice prefix, or verify consistency
    # if the caller passed it explicitly. Only meaningful when we're
    # NOT in blend mode (we already set lang_code from blend.voice_a
    # above).
    if not _resolved_via_blend:
        expected_lang = VOICES[voice][0]
        if lang_code is None:
            lang_code = expected_lang
        elif lang_code != expected_lang:
            raise ValueError(
                f"voice '{voice}' belongs to lang '{expected_lang}', "
                f"not to '{lang_code}'."
            )

    # ---- Pronunciation pre-processing -----------------------------
    if pronunciation_rules:
        # Lazy import mirrors the `lameenc` strategy in `save_audio()`:
        # the engine stays usable for users who never bother with a dict.
        from kokoro_studio.pronunciation import apply_substitutions
        original_len = len(text)
        text = apply_substitutions(text, pronunciation_rules)
        print(f"[Kokoro] Pronunciation rules applied  "
              f"({original_len} -> {len(text)} chars, "
              f"{len(pronunciation_rules)} rule(s))",
              file=sys.stderr)

    # ---- Multi-speaker dispatch -----------------------------------
    # Each segment calls Kokoro separately (Kokoro bakes voice style into
    # the forward pass so voice swaps aren't possible mid-call). The
    # engine handles parsing + per-segment pronunciation rules + the
    # inter-segment silence gap, so the GUI gets a single entry point.
    # Blend names are accepted as marker tokens (same regex as built-ins)
    # so the parser's known_voices list is widened to include them.
    if multi_speaker:
        from kokoro_studio.dialogue import parse_dialogue  # lazy: no Kokoro dep
        segs, warnings = parse_dialogue(
            text,
            default_voice=voice,
            known_voices=set(VOICES.keys()) | set(_loaded_blends.keys()),
        )
        for w in warnings:
            print(f"[Kokoro] Dialogue warning: {w}", file=sys.stderr)
        if not segs:
            raise ValueError(
                "Dialogue mode found no synthesizable segments in the "
                "editor text (all lines were empty after marker stripping)."
            )
        return _generate_dialogue_segments(
            segments=segs,
            speed=speed,
            output_path=output_path,
            output_format=output_format,
            on_chunk=on_chunk,
            stop_check=stop_check,
            pronunciation_rules=pronunciation_rules,
            speaker_gap_s=speaker_gap_s,
            blends=blends if blends is not None else (_loaded_blends or None),
        )

    pipeline = _get_pipeline(lang_code)

    print(f"[Kokoro] Synthesis: voice={voice}, lang={lang_code}, "
          f"speed={speed}, len(text)={len(text)}", file=sys.stderr)

    chunks: List[np.ndarray] = []
    start = time.time()
    # `resolved_voice` is either a string (built-in or saved blend name)
    # OR a torch.Tensor (computed via `voice_blend` arg). KPipeline
    # accepts both directly, so we pass through without branching.
    # ---- SSML-lite routing (Phase 2) -------------------------------
    # If the user opted in AND the text contains SSML-lite markup AND
    # we're not in multi-speaker mode (multi-speaker wins — dialogue
    # markers control `voice=` per-segment which SSML doesn't), route
    # through `_generate_ssml_segments` which inserts `<break>` silences
    # and per-segment `<prosody rate>` speed overrides. The
    # `detect_ssml(text)` short-circuit keeps the plain-text path
    # untouched for the vast majority of generations that have no markup.
    if apply_ssml and not multi_speaker:
        from kokoro_studio.ssml import detect_ssml, parse_ssml
        if detect_ssml(text):
            ssml_segs = parse_ssml(text)
            print(
                f"[Kokoro] SSML-lite routing: {len(ssml_segs)} segments "
                f"({sum(1 for s in ssml_segs if s.kind == 'break')} breaks, "
                f"{sum(1 for s in ssml_segs if s.kind == 'emphasis')} emphasis, "
                f"{sum(1 for s in ssml_segs if s.kind == 'prosody')} prosody)",
                file=sys.stderr,
            )
            return _generate_ssml_segments(
                ssml_segments=ssml_segs,
                base_text=text,
                voice=resolved_voice,
                lang_code=lang_code,
                speed=speed,
                output_path=output_path,
                output_format=output_format,
                on_chunk=on_chunk,
                stop_check=stop_check,
                pronunciation_rules=pronunciation_rules,
            )

    pipe_kwargs: Dict[str, object] = {"voice": resolved_voice, "speed": speed}
    if split_pattern is not None:
        pipe_kwargs["split_pattern"] = split_pattern
    for i, (_graphemes, _phonemes, audio) in enumerate(pipeline(text, **pipe_kwargs)):
        a = np.asarray(audio, dtype=np.float32)
        chunks.append(a)
        print(f"  - chunk {i}: {len(a)} samples ({len(a)/SAMPLE_RATE:.2f}s)",
              file=sys.stderr)
        if on_chunk is not None:
            try:
                on_chunk(0, i, a)
            except Exception as cb_err:
                print(f"  ! on_chunk callback raised: {cb_err}", file=sys.stderr)
        if stop_check is not None and stop_check():
            raise RuntimeError("Synthesis cancelled by caller.")

    if not chunks:
        raise RuntimeError("Kokoro produced no audio (empty or unreadable text?).")

    full_audio = np.concatenate(chunks)
    elapsed = time.time() - start

    if output_path:
        # Resolve effective format for logging (keep record of what we
        # actually wrote, regardless of how it was specified).
        effective_format = (
            output_format.lower()
            if output_format is not None
            else _infer_format_from_path(output_path)
        )
        save_audio(full_audio, output_path, output_format=output_format)
        print(f"[Kokoro] Saved {output_path}  ({effective_format.upper()}) "
              f"({elapsed:.2f}s of generation, "
              f"{len(full_audio)/SAMPLE_RATE:.2f}s of audio)",
              file=sys.stderr)

    return full_audio


def _generate_dialogue_segments(
    segments: List["DialogueSegment"],
    speed: float,
    output_path: Optional[str],
    output_format: Optional[str],
    on_chunk: "Callable[[int, int, np.ndarray], None]",
    stop_check: "Callable[[], bool]",
    pronunciation_rules: Optional[Dict[str, str]],
    speaker_gap_s: float,
    blends: Optional[Mapping[str, "VoiceBlend"]] = None,
) -> np.ndarray:
    """Per-segment synthesis path used when `multi_speaker=True`.

    Each segment is synthesised by its own `KPipeline(...)` call because
    Kokoro bakes the voice style vector into the forward pass — voice
    switches inside one call are impossible. Between segments we emit
    `speaker_gap_s` seconds of silence through the same `on_chunk`
    callback so a real-time streaming consumer plays a natural pause.

    Per-segment contract:
      * Pronunciation rules are applied independently to each segment's
        text (rules are whole-word, deterministic, and don't cross
        segment boundaries anyway — but matching engine_情的)
      * The on_chunk callback receives `(seg_idx, chunk_idx, audio)`
        where `seg_idx` is 0-based segment index. The cross-segment
        silence is emitted with `chunk_idx = dialogue.CHUNK_IDX_GAP`
        so consumers can distinguish it from real audio if needed.
      * Each `seg.voice` is resolved against the engine's loaded
        voice catalog AND the blend registry (`blends`). If the name
        resolves to a `VoiceBlend`, the per-segment tensor is computed
        via `blending.compute_blend_tensor`.
    """
    from kokoro_studio.dialogue import DialogueSegment, CHUNK_IDX_GAP  # noqa: F401
    from kokoro_studio.blending import compute_blend_tensor, resolve_voice_param

    all_audio: List[np.ndarray] = []
    start = time.time()
    # Convert gap seconds → int samples once up front.
    gap_samples = int(round(SAMPLE_RATE * max(0.0, float(speaker_gap_s))))
    # Effective blend registry for this session: prefer the explicit
    # `blends=` arg (CLI / test override), else fall back to the
    # auto-loaded disk registry.
    effective_blends = (
        blends if blends is not None else (_loaded_blends or None)
    )

    for seg_idx, seg in enumerate(segments):
        # Per-segment pronunciation rewrite. `apply_substitutions`
        # short-circuits on empty rules; we still gate the call
        # here because the lazy import is cheap and avoids an
        # import on every segment.
        seg_text = seg.text
        if pronunciation_rules:
            from kokoro_studio.pronunciation import apply_substitutions
            seg_text = apply_substitutions(seg_text, pronunciation_rules)

        # Resolve the right pipeline for this segment's voice.
        # Each segment's voice can be a built-in name OR a saved blend
        # name; we accept both here.
        valid_names = set(VOICES.keys())
        if effective_blends:
            valid_names |= set(effective_blends.keys())
        if seg.voice not in valid_names:
            # The parser normally catches unknown voices (it received
            # `known_voices` widened with blend names from the caller),
            # but if a caller bypassed parse_dialogue and passed an
            # arbitrary segment list we still want to fail cleanly.
            listed = sorted(valid_names)
            raise ValueError(
                f"Dialogue segment #{seg_idx} references unknown "
                f"voice '{seg.voice}'. Known: {listed}"
            )

        # Resolve the segment voice to either a string or a tensor.
        # All built-ins share the same lang_code within a single
        # multi-speaker pass because we only loaded one pipeline.
        seg_is_blend = bool(
            effective_blends and seg.voice in effective_blends
        )
        if seg_is_blend:
            seg_lang = VOICES[effective_blends[seg.voice].voice_a][0]
            _prime_voice_into_pipeline(
                seg_lang, effective_blends[seg.voice].voice_a,
            )
            _prime_voice_into_pipeline(
                seg_lang, effective_blends[seg.voice].voice_b,
            )
        else:
            # Built-in voice names: KPipeline loads them natively inside
            # the per-segment `seg_pipeline(...)` synthesis call that
            # follows below. Priming here would add ~50-150 ms of
            # one-tick synthesis per segment with zero benefit, so we
            # intentionally skip it.
            seg_lang = VOICES[seg.voice][0]  # used by get_pipeline_voices below
        seg_pipeline = _get_pipeline(seg_lang)
        seg_pipeline_voices = _get_pipeline_voices(seg_lang)
        seg_resolved = resolve_voice_param(
            seg.voice, effective_blends or {}, seg_pipeline_voices,
        )

        print(
            f"[Kokoro] Dialogue segment {seg_idx + 1}/{len(segments)}"
            f": voice={seg.voice}{' (blend)' if seg_is_blend else ''}, "
            f"lang={seg_lang}, "
            f"len(text)={len(seg_text)}",
            file=sys.stderr,
        )

        seg_audio_parts: List[np.ndarray] = []
        for chunk_idx, (_g, _p, audio) in enumerate(
            seg_pipeline(seg_text, voice=seg_resolved, speed=speed)
        ):
            a = np.asarray(audio, dtype=np.float32)
            seg_audio_parts.append(a)
            print(
                f"  - seg {seg_idx + 1} chunk {chunk_idx}: "
                f"{len(a)} samples ({len(a)/SAMPLE_RATE:.2f}s)",
                file=sys.stderr,
            )
            if on_chunk is not None:
                try:
                    on_chunk(seg_idx, chunk_idx, a)
                except Exception as cb_err:
                    print(
                        f"  ! on_chunk callback raised (seg {seg_idx}): "
                        f"{cb_err}",
                        file=sys.stderr,
                    )
            if stop_check is not None and stop_check():
                raise RuntimeError("Synthesis cancelled by caller.")

        if seg_audio_parts:
            all_audio.append(np.concatenate(seg_audio_parts))

        # Cross-segment silence gap (skip after the last segment so we
        # don't pad the file with a trailing pause).
        if gap_samples > 0 and seg_idx < len(segments) - 1:
            gap = np.zeros(gap_samples, dtype=np.float32)
            all_audio.append(gap)
            if on_chunk is not None:
                try:
                    on_chunk(seg_idx, CHUNK_IDX_GAP, gap)
                except Exception as cb_err:
                    print(
                        f"  ! on_chunk callback raised (gap): {cb_err}",
                        file=sys.stderr,
                    )

    if not all_audio:
        raise RuntimeError(
            "Kokoro produced no audio for any dialogue segment."
        )

    full_audio = np.concatenate(all_audio)
    elapsed = time.time() - start

    if output_path:
        effective_format = (
            output_format.lower()
            if output_format is not None
            else _infer_format_from_path(output_path)
        )
        save_audio(full_audio, output_path, output_format=output_format)
        print(
            f"[Kokoro] Saved {output_path}  ({effective_format.upper()}) "
            f"({elapsed:.2f}s of generation, "
            f"{len(full_audio)/SAMPLE_RATE:.2f}s of audio, "
            f"{len(segments)} segments)",
            file=sys.stderr,
        )

    return full_audio


# ---------------------------------------------------------------------------
# SSML-lite synthesis (Phase 2 - SSML-lite Controls)
# ---------------------------------------------------------------------------

def _generate_ssml_segments(
    ssml_segments: List["SSMLSegment"],
    base_text: str,
    voice: object,
    lang_code: str,
    speed: float,
    output_path: Optional[str],
    output_format: Optional[str],
    on_chunk: "Callable[[int, int, np.ndarray], None]",
    stop_check: "Callable[[], bool]",
    pronunciation_rules: Optional[Dict[str, str]],
) -> np.ndarray:
    """Per-segment synthesis path used when ``apply_ssml=True``.

    The SSML-lite layer is *flat* by design (no nesting): we walk the
    parsed segment list and synthesise each ``text`` / ``emphasis`` /
    ``prosody`` segment as one ``pipeline(...)`` call (Kokoro bakes the
    voice style vector into the forward pass — speed overrides inside
    a single call aren't possible), then insert silence zeros for
    ``break`` segments and emit them through the same ``on_chunk``
    callback so a real-time streaming consumer plays the pauses too.

    Per-segment contract:
      * Pronunciation rules rewrite the *plain text* of each segment
        (only; SSML tags never go through the dict — the parser strips
        them out into discrete ``SSMLSegment.kind`` fields before this
        helper runs).
      * ``<emphasis>`` and ``<prosody rate="...">`` multiply the base
        ``speed``: the effective speed is ``clip(base * seg.speed_mult,
        SPEED_MIN, SPEED_MAX]``. A ``<prosody rate="0.5">`` line at
        base speed 1.0 therefore renders at 0.5x (half-speed), while
        a ``<prosody rate="2.0">`` at the engine max renders at
        ``SPEED_MAX``. Out-of-range raw rates from the parser were
        already clamped in ``kokoro_studio.ssml.SPEED_MULT_MAX`` /
        ``SPEED_MULT_MIN``; this layer adds the engine's defence-in-
        depth clamp so a future caller passing hand-rolled segments
        can't blow up the pipeline.
      * ``<break time="..."/>`` segments emit ``np.zeros(int(duration_s *
        SAMPLE_RATE))`` mono float32 silence. They pass through
        ``on_chunk`` with ``chunk_idx = dialogue.CHUNK_IDX_GAP`` (same
        sentinel multi-speaker uses for cross-segment silence) so a
        consumer can distinguish synthetic silence from real audio.

    Returns:
        numpy.ndarray float32 mono at 24 kHz, with all text segments
        concatenated in input order, punctuated by break silences.
    """
    from kokoro_studio.ssml import SSMLSegment  # type-only: lazy import below
    from kokoro_studio.dialogue import CHUNK_IDX_GAP  # same sentinel as dialogue
    from kokoro_studio.pronunciation import apply_substitutions

    all_audio: List[np.ndarray] = []
    start = time.time()
    pipeline = _get_pipeline(lang_code)

    text_kinds = {"text", "emphasis", "prosody"}

    for seg_idx, seg in enumerate(ssml_segments):
        if stop_check is not None and stop_check():
            raise RuntimeError("Synthesis cancelled by caller.")

        if seg.kind == "break":
            # SSML-lite pause: emit exact-duration zero-filled float32
            # silence. ``duration_s`` was already validated by the
            # parser (>= BROKEN down to a minimum of 1 ms to keep
            # numpy happy). We still coerce here in case a caller
            # bypasses ``parse_ssml`` with hand-rolled segments.
            n_samples = max(1, int(round(float(seg.duration_s) * SAMPLE_RATE)))
            silence = np.zeros(n_samples, dtype=np.float32)
            all_audio.append(silence)
            print(
                f"  - SSML break @ seg {seg_idx + 1}/{len(ssml_segments)}: "
                f"{seg.duration_s:.3f}s "
                f"({n_samples} samples)",
                file=sys.stderr,
            )
            if on_chunk is not None:
                try:
                    on_chunk(seg_idx, CHUNK_IDX_GAP, silence)
                except Exception as cb_err:
                    print(
                        f"  ! on_chunk callback raised (break): {cb_err}",
                        file=sys.stderr,
                    )
            continue

        if seg.kind not in text_kinds:
            # Unknown kind from a future SSML extension: emit nothing
            # (parser already tried to fold unknown tags into text
            # content upstream, so this only fires for hand-rolled
            # segments). Bail loudly once so a developer notice.
            print(
                f"  ! SSML seg {seg_idx + 1}/{len(ssml_segments)}: "
                f"unknown kind '{seg.kind}', skipping",
                file=sys.stderr,
            )
            continue

        # Apply per-segment pronunciation rewrite on the plain text
        # ONLY. SSML tags aren't in `seg.text` — the parser stripped
        # them into discrete segments already — so the dict is safe
        # to apply wholesale here.
        seg_text = seg.text
        if pronunciation_rules and seg_text:
            seg_text = apply_substitutions(seg_text, pronunciation_rules)

        # A pure-whitespace segment (e.g. between two adjacent blocks)
        # produces no audio and no warning; skip Kokoro entirely so we
        # don't pay the model-call cost.
        if not seg_text or not seg_text.strip():
            continue

        # Per-segment speed override: ``base_speed * speed_mult``,
        # clamped to the engine's safe band. Segments with
        # ``speed_mult == 1.0`` (the dict default for kind='text' and
        # kind='emphasis') are indistinguishable from baseline; we
        # still pass the multiplied value to keep the path uniform.
        effective_speed = max(
            SPEED_MIN,
            min(SPEED_MAX, float(speed) * float(seg.speed_mult)),
        )

        print(
            f"  - SSML seg {seg_idx + 1}/{len(ssml_segments)}: "
            f"kind={seg.kind}, speed_mult={seg.speed_mult:.2f} "
            f"(effective={effective_speed:.2f}), "
            f"len(text)={len(seg_text)}",
            file=sys.stderr,
        )

        seg_audio_parts: List[np.ndarray] = []
        for chunk_idx, (_g, _p, audio) in enumerate(
            pipeline(seg_text, voice=voice, speed=effective_speed)
        ):
            a = np.asarray(audio, dtype=np.float32)
            seg_audio_parts.append(a)
            if on_chunk is not None:
                try:
                    on_chunk(seg_idx, chunk_idx, a)
                except Exception as cb_err:
                    print(
                        f"  ! on_chunk callback raised (seg {seg_idx}): "
                        f"{cb_err}",
                        file=sys.stderr,
                    )
            if stop_check is not None and stop_check():
                raise RuntimeError("Synthesis cancelled by caller.")

        if seg_audio_parts:
            all_audio.append(np.concatenate(seg_audio_parts))

    if not all_audio:
        raise RuntimeError(
            "SSML-lite path produced no audio (all segments were breaks "
            "or empty)."
        )

    full_audio = np.concatenate(all_audio)
    elapsed = time.time() - start

    if output_path:
        effective_format = (
            output_format.lower()
            if output_format is not None
            else _infer_format_from_path(output_path)
        )
        save_audio(full_audio, output_path, output_format=output_format)
        print(
            f"[Kokoro] Saved {output_path}  ({effective_format.upper()}) "
            f"({elapsed:.2f}s of generation, "
            f"{len(full_audio)/SAMPLE_RATE:.2f}s of audio, "
            f"SSML-lite with {len(ssml_segments)} segments)",
            file=sys.stderr,
        )

    return full_audio


# ---------------------------------------------------------------------------
# Pretty printing (used by interactive mode and external scripts)
# ---------------------------------------------------------------------------

def _print_voice_table(lang: Optional[str] = None, gender: Optional[str] = None) -> None:
    """Print the available voices in a tabular format."""
    voices = list_voices(lang=lang, gender=gender)
    title = f"AVAILABLE VOICES ({len(voices)})"
    if lang or gender:
        filters = []
        if lang:
            filters.append(f"lang={lang}")
        if gender:
            filters.append(f"gender={gender}")
        title += " -- filters: " + ", ".join(filters)
    print(title)
    print(f"  {'voice':14s} {'grade':5s} {'g':2s} {'language':12s}  description")
    print("  " + "-" * 72)
    for v in voices:
        info = get_voice_info(v)
        print(f"  {v:14s} {info['grade']:5s} {info['gender']:2s} "
              f"{info['lang_label']:12s}  {info['description']}")


# ---------------------------------------------------------------------------
# Prompt helpers for interactive mode
# ---------------------------------------------------------------------------

def _read_multiline_text() -> Optional[str]:
    """Read multi-line text from stdin. Ends with an empty line or EOF.

    Typing 'q' (or Ctrl+C / Ctrl+D) on the first line returns None (= quit).
    """
    while True:
        print()
        print('STEP -- Text to synthesize')
        print('  (multi-line: end with an empty line; "q" on the first line = quit)')
        lines: List[str] = []
        first = True
        while True:
            try:
                prompt = "> " if first else "| "
                line = input(prompt)
            except EOFError:
                print()
                break
            first = False
            if not lines and line.strip().lower() in ("q", "quit", "exit"):
                return None
            if line == "" and lines:
                break  # end of the multi-line block
            if line == "" and not lines:
                first = True  # reset prompt style to retry empty input
                continue  # initial empty input: keep waiting
            lines.append(line)
        text = "\n".join(lines).strip()
        if text:
            return text
        print("  ! Empty text, try again.")


def _prompt_choice(question: str, valid) -> Optional[str]:
    """Ask for a choice among `valid`. Returns None if the user just presses Enter.

    Raises EOFError if the user types 'q' (handled by interactive_main).
    """
    valid_set = set(valid)
    while True:
        try:
            v = input(f"{question} > ").strip()
        except EOFError:
            raise  # let interactive_main handle the exit
        if not v:
            return None
        if v.lower() in ("q", "quit", "exit"):
            raise EOFError
        if v in valid_set:
            return v
        print(f"  ! Choice '{v}' is not valid. Try again.")


def _prompt_float(question: str, default: float) -> float:
    """Ask for a float in (SPEED_MIN, SPEED_MAX]. Returns default if input is empty."""
    while True:
        try:
            v = input(f"{question} [default: {default:.2f}] > ").strip()
        except EOFError:
            return default
        if not v:
            return default
        try:
            f = float(v)
        except ValueError:
            print("  ! Not a valid number. Try again.")
            continue
        if SPEED_MIN < f <= SPEED_MAX:
            return f
        print(f"  ! Must be in ({SPEED_MIN}, {SPEED_MAX}]. Try again.")


def _prompt_text(question: str, default: str = "") -> str:
    """Ask for a string. Returns default if input is empty."""
    try:
        v = input(f"{question} [default: {default or '<empty>'}] > ").strip()
    except EOFError:
        return default
    return v if v else default


# ---------------------------------------------------------------------------
# Interactive mode (terminal)
# ---------------------------------------------------------------------------

def interactive_main() -> int:
    """Step-by-step audio generation loop running in the terminal."""
    print()
    print("=" * 70)
    print("  KOKORO TTS  -  Interactive mode")
    print("  (type 'q' or press Ctrl+C at any time to exit)")
    print("=" * 70)

    while True:
        try:
            # 1. Text
            text = _read_multiline_text()
            if text is None:
                print("\nBye!")
                return 0

            # 2. Voice
            print()
            _print_voice_table()
            print()
            voice = _prompt_choice(
                f"Choose a voice (Enter for default: {DEFAULT_VOICE})",
                list_voices(),
            ) or DEFAULT_VOICE
            info = get_voice_info(voice)
            print(f"  -> {voice} ({info['lang_label']}, Grade {info['grade']}, {info['gender']})")

            # 3. Speed
            print()
            print("STEP -- Synthesis speed")
            print("  (1.0 = normal; <1 slower (audiobook); >1 faster)")
            speed = _prompt_float("Speed (Enter for default: 1.00)", default=1.0)

            # 4. Output
            print()
            default_out = f"Kokoro_{voice}.wav"
            output = _prompt_text("Output WAV path", default=default_out)
            if not output.lower().endswith(".wav"):
                output += ".wav"

            # 5. Confirm
            print()
            print("=" * 70)
            print("  SUMMARY")
            print("=" * 70)
            preview = text if len(text) <= 100 else text[:97] + "..."
            print(f"  Text:    {preview!r}")
            print(f"  Voice:   {voice}")
            print(f"          {info['description']} [{info['lang_label']}, {info['gender']}, Grade {info['grade']}]")
            print(f"  Speed:   {speed}")
            print(f"  Output:  {output}")
            print()
            try:
                ok = input("Proceed? [Y/n] > ").strip().lower()
            except EOFError:
                ok = "y"
            if ok in ("n", "no"):
                print("  Cancelled. Let's start over.\n")
                continue

            # 6. Generation
            print()
            print("[...] Synthesis in progress, please wait...")
            try:
                audio = generate_speech(
                    text=text,
                    voice=voice,
                    output_path=output,
                    speed=speed,
                )
            except ImportError:
                print("\n[ERROR] 'kokoro' library not installed.", file=sys.stderr)
                print("         Run: pip install kokoro soundfile", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"\n[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
                retry = input("\nTry again from the start? [y/N] > ").strip().lower()
                if retry in ("y", "yes"):
                    continue
                return 1

            print()
            print(f"  [OK] Written: {output}  ({len(audio)/SAMPLE_RATE:.2f}s of audio)")

            # 7. Retry
            try:
                retry = input("\nGenerate another one? [y/N] > ").strip().lower()
            except EOFError:
                retry = "n"
            if retry not in ("y", "yes"):
                print("Bye!")
                return 0
            print()

        except KeyboardInterrupt:
            print("\n\nInterrupted. Bye!")
            return 0
        except EOFError:
            print("\n\nBye!")
            return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point: launches the interactive terminal mode."""
    return interactive_main()


if __name__ == "__main__":
    sys.exit(main())
