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
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

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


# ---------------------------------------------------------------------------
# Pipeline cache (KPipeline is heavy to load, reuse it)
# ---------------------------------------------------------------------------
_pipelines: Dict[str, "KPipeline"] = {}


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
    on_chunk: Optional["Callable[[int, np.ndarray], None]"] = None,
    stop_check: Optional["Callable[[], bool]"] = None,
    output_format: Optional[str] = None,
    pronunciation_rules: Optional[Dict[str, str]] = None,
) -> np.ndarray:
    """Synthesize `text` with Kokoro and return the audio (float32) at 24 kHz.

    Args:
        text:          text to synthesize (non-empty).
        voice:         voice name (default: 'af_heart'). See VOICES or list_voices().
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
                       args (chunk_index, audio_chunk_ndarray). The chunk's
                       dtype is float32, mono, at SAMPLE_RATE Hz. Exceptions
                       raised by the callback are logged to stderr and ignored.
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
                       input `text` BEFORE synthesis (whole-word, case-
                       sensitive, longest-rule-first). Empty / None is a
                       no-op fast path. Lazily imports the `pronunciation`
                       module so users who only ever synthesise without a
                       dict don't need to install anything beyond the
                       engine's baseline deps.

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

    if voice not in VOICES:
        available = ", ".join(list_voices())
        raise ValueError(f"voice '{voice}' is not recognized. Available: {available}")

    # Type-guard on speed: only accept numbers in (SPEED_MIN, SPEED_MAX]
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) \
            or speed < SPEED_MIN or speed > SPEED_MAX:
        raise ValueError(f"`speed` must be a number in ({SPEED_MIN}, {SPEED_MAX}].")

    # Auto-derive lang_code from the voice prefix, or verify consistency
    # if the caller passed it explicitly.
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

    pipeline = _get_pipeline(lang_code)

    print(f"[Kokoro] Synthesis: voice={voice}, lang={lang_code}, "
          f"speed={speed}, len(text)={len(text)}", file=sys.stderr)

    chunks: List[np.ndarray] = []
    start = time.time()
    pipe_kwargs: Dict[str, object] = {"voice": voice, "speed": speed}
    if split_pattern is not None:
        pipe_kwargs["split_pattern"] = split_pattern
    for i, (_graphemes, _phonemes, audio) in enumerate(pipeline(text, **pipe_kwargs)):
        a = np.asarray(audio, dtype=np.float32)
        chunks.append(a)
        print(f"  - chunk {i}: {len(a)} samples ({len(a)/SAMPLE_RATE:.2f}s)",
              file=sys.stderr)
        if on_chunk is not None:
            try:
                on_chunk(i, a)
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
