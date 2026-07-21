# -*- coding: utf-8 -*-
"""Audiobook Chapter Builder for Kokoro Studio.

Phase 4 — Premium & Platform Features.  Splits EPUB/TXT documents by
chapter, assigns a voice per chapter, batch-generates the audio, and
optionally merges everything into one file.

Public API:
    ChapterInfo
        Dataclass describing one chapter's synthesis parameters.

    AudiobookProject
        Dataclass capturing a full audiobook project (document +
        per-chapter assignments + global settings).

    generate_audiobook(project, on_progress=None, on_chapter_done=None)
        Generate all chapters sequentially, returning a list of
        ``(ChapterInfo, audio_ndarray)`` tuples.

    merge_audio_segments(segments, sample_rate=24000) -> np.ndarray
        Concatenate a list of audio arrays end-to-end with optional
        cross-chapter silence.

This module has ZERO PySide6 dependencies, so it can be unit-tested
in CI and reused from CLI / batch mode without Qt.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

import numpy as np

from kokoro_studio.audio_processing import PostProcessingParams
from kokoro_studio.engine import (
    SAMPLE_RATE, generate_speech, save_audio,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChapterInfo:
    """Synthesis parameters for a single audiobook chapter.

    Fields:
        index:      1-based chapter number (for file naming).
        title:     Chapter title (best-effort from first non-empty line,
                   else "Chapter N").
        text:      Full chapter text to synthesise.
        voice:     Voice or blend name assigned to this chapter.
    """
    index: int
    title: str
    text: str
    voice: str


@dataclass(frozen=True)
class AudiobookProject:
    """Full audiobook project specification.

    Fields:
        source_path:      Path to the original document (EPUB / TXT).
        title:            Book title.
        author:           Optional author name.
        language:         Optional language code.
        chapters:         List of ``ChapterInfo``, one per chapter.
        default_voice:    Fallback voice when a chapter has none assigned.
        speed:            Global speed multiplier.
        output_format:    Output audio format ('wav', 'mp3', 'flac', 'ogg').
        output_dir:       Directory where generated files will be saved.
        chapter_gap_s:    Seconds of silence between concatenated chapters
                          when merging into a single file.  Default 0.5 s.
        post_process_params: Optional post-processing to apply to each
                          chapter's audio.

        # Export flags
        separate_files:   If True, save one audio file per chapter.
        merged_file:      If True, also generate a single merged file.
        merged_filename:  Filename for the merged file (stem only,
                          extension is derived from ``output_format``).
    """
    source_path: Optional[Path] = None
    title: str = "Untitled"
    author: Optional[str] = None
    language: Optional[str] = None
    chapters: List[ChapterInfo] = field(default_factory=list)
    default_voice: str = "af_heart"
    speed: float = 1.0
    output_format: str = "wav"
    output_dir: Path = Path(".")
    chapter_gap_s: float = 0.5
    post_process_params: Optional[PostProcessingParams] = None
    separate_files: bool = True
    merged_file: bool = False
    merged_filename: str = "audiobook_merged"


# ---------------------------------------------------------------------------
# Generation result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChapterResult:
    """Outcome of generating one chapter.

    Fields:
        chapter:     The ``ChapterInfo`` that was generated.
        duration_s:  Audio duration in seconds (0.0 on failure).
        success:     True if synthesis completed without error.
        error_msg:   Human-readable error text (empty on success).
        audio:       The full audio array (float32 mono) — only kept
                     when merging is requested, else None to save memory.
    """
    chapter: ChapterInfo
    duration_s: float
    success: bool
    error_msg: str = ""
    audio: Optional[np.ndarray] = None


@dataclass(frozen=True)
class AudiobookSummary:
    """Aggregated result of an audiobook generation run.

    Fields:
        total:              Number of chapters in the project.
        succeeded:          Chapters that completed successfully.
        failed:             Chapters that errored.
        total_audio_duration_s:  Sum of all successful chapter durations.
        elapsed_s:          Wall-clock seconds for the full run.
        output_files:       Paths of files written to disk.
    """
    total: int
    succeeded: int
    failed: int
    total_audio_duration_s: float
    elapsed_s: float
    output_files: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Chapter title extraction
# ---------------------------------------------------------------------------

def extract_chapter_title(text: str, index: int) -> str:
    """Derive a human-readable chapter title from the text.

    Heuristics (first win):
      1. First non-empty line that looks like a heading (short, ≤ 80 chars
         and doesn't end with punctuation that suggests a full sentence).
      2. First non-empty line, truncated.
      3. ``f"Chapter {index}"``
    """
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Short line without sentence-ending punctuation → likely a heading
        if len(line) <= 80 and not line.rstrip().endswith((".", "!", "?")):
            return line[:120].strip()
        # Longer line: use first 60 chars as subtitle
        return line[:60].strip() + ("…" if len(line) > 60 else "")
    return f"Chapter {index}"


# ---------------------------------------------------------------------------
# Build chapter list from a Document
# ---------------------------------------------------------------------------

def chapters_from_document(
    doc: "Document",                  # noqa: F821 — lazy import in function
    default_voice: str = "af_heart",
) -> List[ChapterInfo]:
    """Convert a ``Document.chapters`` into a list of ``ChapterInfo``.

    Each non-empty chapter becomes one ``ChapterInfo`` with the default
    voice.  Empty chapters are silently dropped.
    """
    chapters: List[ChapterInfo] = []
    for idx, chap_text in enumerate(doc.chapters, start=1):
        text = chap_text.strip()
        if not text:
            continue
        title = extract_chapter_title(text, idx)
        chapters.append(ChapterInfo(
            index=idx,
            title=title,
            text=text,
            voice=default_voice,
        ))
    return chapters


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def generate_chapter(
    chapter: ChapterInfo,
    speed: float,
    output_path: Optional[str] = None,
    output_format: str = "wav",
    pronunciation_rules: Optional[dict] = None,
    blends: Optional[dict] = None,
    post_process_params: Optional[PostProcessingParams] = None,
    on_chunk: Optional[Callable[[int, int, np.ndarray], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> np.ndarray:
    """Synthesise a single chapter's text.

    Args:
        chapter:             Chapter to generate.
        speed:               Speed multiplier.
        output_path:         Optional path to save the audio file.
        output_format:       Output format extension.
        pronunciation_rules: Optional pronunciation rules.
        blends:              Optional blend presets.
        post_process_params: Optional post-processing.
        on_chunk:            Optional chunk callback.
        stop_check:          Optional stop-request callback.

    Returns:
        float32 mono audio array at 24 kHz.
    """
    return generate_speech(
        text=chapter.text,
        voice=chapter.voice,
        speed=speed,
        output_path=output_path,
        output_format=output_format,
        pronunciation_rules=pronunciation_rules,
        blends=blends,
        post_process_params=post_process_params,
        on_chunk=on_chunk,
        stop_check=stop_check,
    )


# ---------------------------------------------------------------------------
# Full audiobook generation
# ---------------------------------------------------------------------------

def generate_audiobook(
    project: AudiobookProject,
    pronunciation_rules: Optional[dict] = None,
    blends: Optional[dict] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_chapter_done: Optional[Callable[[int, ChapterResult], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> AudiobookSummary:
    """Generate all chapters of an audiobook project sequentially.

    Each chapter is synthesised independently, then optionally saved to
    disk (separate files and/or merged file).

    Args:
        project:             The audiobook project specification.
        pronunciation_rules: Optional global pronunciation rules.
        blends:              Optional blend presets.
        on_progress:         ``(current, total, chapter_title)`` callback
                             before each chapter starts.
        on_chapter_done:     ``(index, ChapterResult)`` callback after
                             each chapter finishes.
        stop_check:          Optional callable returning True to abort.

    Returns:
        An ``AudiobookSummary`` with results and output file paths.
    """
    start_wall = time.time()
    n_total = len(project.chapters)
    results: List[ChapterResult] = []
    output_files: List[str] = []

    # Create output directory
    try:
        project.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.warning("[audiobook] Could not create output dir: %s", e)

    for idx, chapter in enumerate(project.chapters):
        if stop_check is not None and stop_check():
            break

        if on_progress is not None:
            on_progress(idx + 1, n_total, chapter.title)

        # Derive output path for this chapter's separate file
        chap_path: Optional[str] = None
        if project.separate_files:
            safe_name = _safe_filename(chapter.title)
            chap_fname = f"{idx + 1:03d}_{safe_name}.{project.output_format}"
            chap_path = str(project.output_dir / chap_fname)

        try:
            audio = generate_chapter(
                chapter=chapter,
                speed=project.speed,
                output_path=chap_path,
                output_format=project.output_format,
                pronunciation_rules=pronunciation_rules,
                blends=blends,
                post_process_params=project.post_process_params,
                stop_check=stop_check,
            )
            duration_s = len(audio) / SAMPLE_RATE
            result = ChapterResult(
                chapter=chapter,
                duration_s=duration_s,
                success=True,
                audio=audio if project.merged_file else None,
            )
            if chap_path:
                output_files.append(chap_path)
        except RuntimeError as e:
            if "cancelled" in str(e).lower():
                result = ChapterResult(
                    chapter=chapter,
                    duration_s=0.0,
                    success=False,
                    error_msg="Cancelled.",
                )
            else:
                result = ChapterResult(
                    chapter=chapter,
                    duration_s=0.0,
                    success=False,
                    error_msg=f"{type(e).__name__}: {e}",
                )
        except Exception as e:
            result = ChapterResult(
                chapter=chapter,
                duration_s=0.0,
                success=False,
                error_msg=f"{type(e).__name__}: {e}",
            )

        results.append(result)

        if on_chapter_done is not None:
            on_chapter_done(idx, result)

        if stop_check is not None and stop_check():
            break

    # Generate merged file if requested
    if project.merged_file:
        success_audios = [
            r.audio for r in results
            if r.success and r.audio is not None
        ]
        if success_audios:
            merged = merge_audio_segments(
                success_audios,
                sample_rate=SAMPLE_RATE,
                gap_s=project.chapter_gap_s,
            )
            merged_fname = f"{project.merged_filename}.{project.output_format}"
            merged_path = str(project.output_dir / merged_fname)
            try:
                save_audio(merged, merged_path, output_format=project.output_format)
                output_files.append(merged_path)
            except Exception as e:
                logging.warning("[audiobook] Merged file save failed: %s", e)

    elapsed = time.time() - start_wall
    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded
    total_audio = sum(r.duration_s for r in results if r.success)

    return AudiobookSummary(
        total=n_total,
        succeeded=succeeded,
        failed=failed,
        total_audio_duration_s=total_audio,
        elapsed_s=elapsed,
        output_files=output_files,
    )


# ---------------------------------------------------------------------------
# Audio merging
# ---------------------------------------------------------------------------

def merge_audio_segments(
    segments: List[np.ndarray],
    sample_rate: int = SAMPLE_RATE,
    gap_s: float = 0.5,
) -> np.ndarray:
    """Concatenate a list of audio arrays end-to-end.

    Inserts ``gap_s`` seconds of silence between consecutive segments.

    Args:
        segments:    List of float32 mono audio arrays.
        sample_rate: Sample rate for gap calculation (default 24000).
        gap_s:       Seconds of silence between segments (default 0.5).

    Returns:
        Concatenated float32 mono array.
    """
    if not segments:
        return np.zeros(0, dtype=np.float32)
    if len(segments) == 1:
        return segments[0].copy()

    gap_samples = int(round(sample_rate * max(0.0, gap_s)))
    gap = np.zeros(gap_samples, dtype=np.float32) if gap_samples > 0 else None

    parts: List[np.ndarray] = []
    for i, seg in enumerate(segments):
        parts.append(seg)
        if gap is not None and i < len(segments) - 1:
            parts.append(gap)

    return np.concatenate(parts) if len(parts) > 1 else parts[0]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_filename(title: str) -> str:
    """Convert a chapter title into a filesystem-safe string."""
    safe = ""
    for ch in title:
        if ch.isalnum() or ch in " _-.,'":
            safe += ch
        else:
            safe += "_"
    # Collapse multiple underscores
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip(" _").replace(" ", "_") or "chapter"
