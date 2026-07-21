# -*- coding: utf-8 -*-
"""Project management: save/load .ksproj files.

A .ksproj file is a JSON document that captures the full state of the
Kokoro Studio GUI — editor text, selected voice, speed, output settings,
pronunciation rules, SSML/stream toggles, active profile, post-processing
params, and metadata (name, timestamps, format version).

This module has **zero Qt dependencies** so it can be used from the CLI
or unit tests without importing PySide6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Format version — bump when the schema changes
# ---------------------------------------------------------------------------
_FORMAT_VERSION = 1


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PostProcessingSnapshot:
    """Serialisable subset of ``PostProcessingParams``."""
    trim_silence: bool = True
    trim_threshold_db: float = -40.0
    trim_min_silence_len: int = 100
    volume_enabled: bool = False
    volume_gain_db: float = 0.0
    fade_enabled: bool = False
    fade_in_duration_s: float = 0.005
    fade_out_duration_s: float = 0.005
    normalize_enabled: bool = False
    normalize_mode: str = "peak"
    normalize_target_db: float = -1.0


@dataclass(frozen=True)
class ProjectData:
    """Complete snapshot of a Kokoro Studio session.

    This is the root object serialised into the .ksproj JSON file.
    All fields have defaults so that partial / older files don't crash
    on load — unknown keys are silently ignored.
    """

    format_version: int = _FORMAT_VERSION

    # Metadata
    name: str = "Untitled Project"
    created_at: str = ""   # ISO-8601, set by save
    updated_at: str = ""   # ISO-8601, set by save

    # Editor content
    editor_text: str = ""

    # Synthesis settings
    voice: str = "af_heart"
    speed: float = 1.0
    output_format: str = "wav"

    # Toggles
    apply_pronunciation: bool = True
    apply_ssml: bool = False
    stream: bool = False

    # Active profile (name only; the actual profile is loaded separately)
    profile_name: Optional[str] = None

    # Post-processing
    post_processing: PostProcessingSnapshot = field(default_factory=PostProcessingSnapshot)

    # Path to the source document (if the text was loaded from a file)
    source_document: Optional[str] = None


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pp_snapshot_from_params(params: Any) -> PostProcessingSnapshot:
    """Convert a ``PostProcessingParams`` instance to a serialisable snapshot."""
    return PostProcessingSnapshot(
        trim_silence=bool(getattr(params, "trim_silence", True)),
        trim_threshold_db=float(getattr(params, "trim_threshold_db", -40.0)),
        trim_min_silence_len=int(getattr(params, "trim_min_silence_len", 100)),
        volume_enabled=bool(getattr(params, "volume_enabled", False)),
        volume_gain_db=float(getattr(params, "volume_gain_db", 0.0)),
        fade_enabled=bool(getattr(params, "fade_enabled", False)),
        fade_in_duration_s=float(getattr(params, "fade_in_duration_s", 0.005)),
        fade_out_duration_s=float(getattr(params, "fade_out_duration_s", 0.005)),
        normalize_enabled=bool(getattr(params, "normalize_enabled", False)),
        normalize_mode=str(getattr(params, "normalize_mode", "peak")),
        normalize_target_db=float(getattr(params, "normalize_target_db", -1.0)),
    )


def _params_from_snapshot(snapshot: dict | PostProcessingSnapshot) -> dict:
    """Turn a deserialised snapshot back into a plain dict for reconstruction."""
    if isinstance(snapshot, PostProcessingSnapshot):
        d = asdict(snapshot)
    else:
        # JSON-parsed dict — extract known keys with defaults
        d = {k: snapshot.get(k, v) for k, v in asdict(PostProcessingSnapshot()).items()}
    return d


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_project(path: str | Path, data: ProjectData) -> None:
    """Serialise *data* to a .ksproj JSON file at *path*.

    The ``updated_at`` field is automatically set to the current time.
    If the file has no ``created_at``, it is set too.
    """
    now = _now_iso()
    created = data.created_at or now
    data = ProjectData(
        format_version=_FORMAT_VERSION,
        name=data.name,
        created_at=created,
        updated_at=now,
        editor_text=data.editor_text,
        voice=data.voice,
        speed=data.speed,
        output_format=data.output_format,
        apply_pronunciation=data.apply_pronunciation,
        apply_ssml=data.apply_ssml,
        stream=data.stream,
        profile_name=data.profile_name,
        post_processing=data.post_processing,
        source_document=data.source_document,
    )

    raw = asdict(data)
    raw["post_processing"] = asdict(data.post_processing)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)


def load_project(path: str | Path) -> ProjectData:
    """Deserialise a .ksproj JSON file from *path*.

    Unknown keys in the JSON are silently ignored.  Missing optional keys
    fall back to the ``ProjectData`` field defaults so older schema versions
    don't crash on load.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw: dict = json.load(f)

    # Extract fields with safe defaults
    pp_raw = raw.get("post_processing", {})
    if not isinstance(pp_raw, dict):
        pp_raw = {}
    pp = PostProcessingSnapshot(**_params_from_snapshot(pp_raw))

    return ProjectData(
        format_version=raw.get("format_version", _FORMAT_VERSION),
        name=raw.get("name", path.stem),
        created_at=raw.get("created_at", ""),
        updated_at=raw.get("updated_at", ""),
        editor_text=raw.get("editor_text", ""),
        voice=raw.get("voice", "af_heart"),
        speed=float(raw.get("speed", 1.0)),
        output_format=raw.get("output_format", "wav"),
        apply_pronunciation=bool(raw.get("apply_pronunciation", True)),
        apply_ssml=bool(raw.get("apply_ssml", False)),
        stream=bool(raw.get("stream", False)),
        profile_name=raw.get("profile_name"),
        post_processing=pp,
        source_document=raw.get("source_document"),
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "ProjectData",
    "PostProcessingSnapshot",
    "save_project",
    "load_project",
]
