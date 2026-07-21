# -*- coding: utf-8 -*-
"""Command-line interface for Kokoro Studio.

Usage:
    kokoro-studio batch <input_file> [options]

The ``batch`` subcommand processes a text file and generates audio for
each non-empty paragraph, producing one audio file per paragraph.

Examples:
    kokoro-studio batch story.txt
    kokoro-studio batch story.txt --voice af_heart --speed 1.2
    kokoro-studio batch story.txt --output-dir ./audio --format mp3
    kokoro-studio batch --help
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from kokoro_studio.engine import (
    OUTPUT_FORMATS,
    SAMPLE_RATE,
    SPEED_MAX,
    SPEED_MIN,
    VOICES,
    generate_speech,
    list_voices,
)


def _resolve_voice(voice: str) -> str:
    """Validate and return the voice name (built-in or blend).

    Lazy-imports ``blending`` only when needed because ``blending``
    pulls in ``scipy`` which is an optional dependency.
    """
    known = set(VOICES.keys())
    if voice in known:
        return voice
    # Check blend names (lazy import: blending pulls in scipy).
    try:
        from kokoro_studio.blending import is_valid_blend_name
    except ImportError:
        pass
    else:
        if is_valid_blend_name(voice):
            # The user might have a saved blend; the engine will
            # raise a clear error if it doesn't exist on disk.
            return voice
    builtins = list_voices()
    sys.stderr.write(
        f"Error: unknown voice '{voice}'.\n"
        f"Available built-in voices ({len(builtins)}):\n"
    )
    for v in builtins:
        sys.stderr.write(f"  {v}\n")
    sys.stderr.write(
        "Pass a voice name, or omit (default: af_heart).\n"
    )
    sys.exit(1)


def _validate_format(fmt: str) -> str:
    """Normalise and validate the output format string."""
    fmt = fmt.lower().lstrip(".")
    if fmt not in OUTPUT_FORMATS:
        sys.stderr.write(
            f"Error: unsupported format '{fmt}'.\n"
            f"Supported formats: {', '.join(OUTPUT_FORMATS)}\n"
        )
        sys.exit(1)
    return fmt


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the kokoro-studio tool."""
    parser = argparse.ArgumentParser(
        prog="kokoro-studio",
        description="Local, free, fast neural text-to-speech — CLI mode.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── batch subcommand ───────────────────────────────────────────
    # ── serve subcommand ───────────────────────────────────────────
    serve_parser = subparsers.add_parser(
        "serve",
        help="Launch the TTS API server.",
        description=(
            "Start a local REST API server with an OpenAI-compatible "
            "/v1/audio/speech endpoint and WebSocket streaming."
        ),
    )
    from kokoro_studio.api_server import create_server_parser
    create_server_parser(serve_parser)

    # ── batch subcommand ───────────────────────────────────────────
    batch_parser = subparsers.add_parser(
        "batch",
        help="Synthesise a text file (one audio file per paragraph).",
        description=(
            "Read INPUT_FILE, split it into paragraphs (separated by blank"
            " lines), and generate an audio file for each non-empty paragraph."
        ),
    )
    batch_parser.add_argument(
        "input_file",
        type=str,
        help="Path to a .txt file with the text to synthesise.",
    )
    batch_parser.add_argument(
        "--voice", "-v",
        type=str,
        default="af_heart",
        help="Voice name (default: af_heart).",
    )
    batch_parser.add_argument(
        "--speed", "-s",
        type=float,
        default=1.0,
        help=f"Speed multiplier ({SPEED_MIN}–{SPEED_MAX}, default: 1.0).",
    )
    batch_parser.add_argument(
        "--format", "-f",
        type=str,
        default="wav",
        help=f"Output format ({'/'.join(OUTPUT_FORMATS)}, default: wav).",
    )
    batch_parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=".",
        help="Output directory (default: current working directory).",
    )
    batch_parser.add_argument(
        "--prefix",
        type=str,
        default="batch",
        help="Filename prefix (default: 'batch'). Files: <prefix>_001.wav …",
    )
    batch_parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Language code (default: auto-derived from voice).",
    )
    batch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and list items without generating audio.",
    )

    return parser.parse_args(argv)


def _read_paragraphs(path: str) -> list[str]:
    """Split a text file into non-empty paragraphs."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        sys.stderr.write(f"Error: input file not found: {path}\n")
        sys.exit(1)
    except OSError as e:
        sys.stderr.write(f"Error reading {path}: {e}\n")
        sys.exit(1)

    # Split by blank lines (double newline) first.
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    if not blocks:
        # Fallback: split by single newlines.
        blocks = [b.strip() for b in text.split("\n") if b.strip()]
    if not blocks:
        sys.stderr.write("Error: no non-empty text found in input.\n")
        sys.exit(1)

    return blocks


def _run_batch(args: argparse.Namespace) -> int:
    """Execute the ``batch`` subcommand."""
    # Validate arguments
    voice = _resolve_voice(args.voice)
    fmt = _validate_format(args.format)

    if args.speed < SPEED_MIN or args.speed > SPEED_MAX:
        sys.stderr.write(
            f"Error: speed must be in [{SPEED_MIN}, {SPEED_MAX}], "
            f"got {args.speed}.\n"
        )
        return 1

    out_dir = Path(args.output_dir)
    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            sys.stderr.write(f"Error creating output directory: {e}\n")
            return 1

    # Read paragraphs
    paragraphs = _read_paragraphs(args.input_file)
    n_items = len(paragraphs)
    dig = len(str(n_items))

    if args.dry_run:
        print(f"Dry-run: {n_items} item(s) from {args.input_file}")
        print(f"  Voice: {voice}")
        print(f"  Speed: {args.speed}")
        print(f"  Format: {fmt}")
        print(f"  Output dir: {out_dir.resolve()}")
        print()
        for i, para in enumerate(paragraphs, 1):
            fname = f"{args.prefix}_{i:0{dig}d}.{fmt}"
            preview = para[:60].replace("\n", " ")
            print(f"  {i:>{dig}}/{n_items}  {fname}  \"{preview}…\"")
        return 0

    # Process each paragraph
    start_wall = time.time()
    succeeded = 0
    failed = 0
    total_duration_s = 0.0

    for i, para in enumerate(paragraphs, 1):
        fname = f"{args.prefix}_{i:0{dig}d}.{fmt}"
        out_path = str(out_dir / fname)
        preview = para[:40].replace("\n", " ")

        print(f"[{i:>{dig}}/{n_items}] {fname}  \"{preview}…\"", end="", flush=True)

        try:
            audio = generate_speech(
                text=para,
                voice=voice,
                lang_code=args.lang,
                output_path=out_path,
                output_format=fmt,
                speed=args.speed,
            )
            dur = len(audio) / SAMPLE_RATE
            total_duration_s += dur
            succeeded += 1
            print(f"  ✅ {dur:.2f}s", flush=True)
        except Exception as e:
            failed += 1
            print(f"  ❌ {e}", flush=True)

    elapsed = time.time() - start_wall
    print()
    print(f"Batch complete  ·  {elapsed:.2f}s wall clock")
    print(f"  Succeeded: {succeeded}  ({total_duration_s:.2f}s audio)")
    print(f"  Failed:    {failed}")
    print(f"  Output:    {out_dir.resolve()}")

    return 0 if failed == 0 else 1


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Parses args, dispatches to the right subcommand."""
    args = _parse_args(argv)

    if args.command == "batch":
        return _run_batch(args)
    if args.command == "serve":
        from kokoro_studio.api_server import run_server
        return run_server(args)

    # Should not be reached (subparsers are required)
    sys.stderr.write(f"Unknown command: {args.command}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
