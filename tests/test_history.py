# -*- coding: utf-8 -*-
"""Tests for `kokoro_studio.history`.

Pure-Python module without Qt or kokoro. Coverage:

  * `HistoryEntry` dataclass: fields, immutability.
  * `GenerationHistory` class:
      - Database creation and schema auto-setup.
      - `add_generation`, `get_recent`, `get_by_id`.
      - `delete` (single row).
      - `clear` (all rows).
      - Parent directory auto-creation on init.
      - Ordering: most-recent-first in `get_recent`.
      - Limit enforcement.
      - Edge cases: empty table returns [], missing ID returns None.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from kokoro_studio.history import GenerationHistory, HistoryEntry


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def db_path() -> Path:
    """Yield a temporary database path, cleaned up after the test."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        yield Path(td) / "history.db"


# ===================================================================
# HistoryEntry dataclass
# ===================================================================

def test_history_entry_fields() -> None:
    entry = HistoryEntry(
        id=1,
        created_at="2026-07-10 12:00:00",
        text="Hello world",
        voice="af_heart",
        speed=1.0,
        duration_s=2.5,
        audio_path="/tmp/test.wav",
        format="wav",
    )
    assert entry.id == 1
    assert entry.created_at == "2026-07-10 12:00:00"
    assert entry.text == "Hello world"
    assert entry.voice == "af_heart"
    assert entry.speed == 1.0
    assert entry.duration_s == 2.5
    assert entry.audio_path == "/tmp/test.wav"
    assert entry.format == "wav"


def test_history_entry_is_frozen() -> None:
    entry = HistoryEntry(
        id=1, created_at="now", text="x", voice="v",
        speed=1.0, duration_s=1.0, audio_path="/x.wav", format="wav",
    )
    with pytest.raises((AttributeError, Exception)):
        entry.text = "y"  # type: ignore[misc]


# ===================================================================
# GenerationHistory — schema & init
# ===================================================================

def test_init_creates_schema(db_path: Path) -> None:
    """Constructing GenerationHistory must create the table and index."""
    hist = GenerationHistory(str(db_path))
    with sqlite3.connect(db_path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='history'"
        ).fetchall()
        assert len(tables) == 1
        # Verify expected columns exist (at minimum).
        cols = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
        for expected in ("id", "created_at", "text", "voice", "speed",
                         "duration_s", "audio_path", "format"):
            assert expected in cols, f"missing column: {expected}"
        # Index on created_at DESC.
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_history_created_at'"
        ).fetchall()
        assert len(indexes) == 1
    # Default state: empty table.
    entries = hist.get_recent(10)
    assert entries == []


def test_init_creates_parent_directory() -> None:
    """A nested non-existent parent directory must be auto-created."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        nested = Path(td) / "deep" / "nested" / "dir" / "history.db"
        hist = GenerationHistory(str(nested))
        assert nested.exists()
        # Should be usable immediately.
        hist.add_generation("test", "v", 1.0, 1.0, "/x.wav", "wav")


def test_init_reuses_existing_database(db_path: Path) -> None:
    """Calling init twice on the same path must not raise (idempotent)."""
    GenerationHistory(str(db_path))
    GenerationHistory(str(db_path))  # second init: table already exists


def test_table_columns_match_history_entry(db_path: Path) -> None:
    """Verify the SQL column types align with HistoryEntry fields."""
    GenerationHistory(str(db_path))
    with sqlite3.connect(db_path) as conn:
        col_info = {
            row[1]: row[2] for row in conn.execute("PRAGMA table_info(history)")
        }
    assert col_info["id"] == "INTEGER"
    assert col_info["text"] == "TEXT"
    assert col_info["voice"] == "TEXT"
    assert col_info["speed"] == "REAL"
    assert col_info["duration_s"] == "REAL"
    assert col_info["audio_path"] == "TEXT"
    assert col_info["format"] == "TEXT"


# ===================================================================
# add_generation
# ===================================================================

def test_add_generation_returns_id(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    eid = hist.add_generation("hello", "af_heart", 1.0, 2.5, "/out.wav", "wav")
    assert isinstance(eid, int)
    assert eid >= 1


def test_add_generation_persists_all_fields(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    hist.add_generation(
        text="Hello, world!",
        voice="af_bella",
        speed=0.8,
        duration_s=3.14,
        audio_path="/tmp/my_output.wav",
        output_format="mp3",
    )
    entries = hist.get_recent(10)
    assert len(entries) == 1
    e = entries[0]
    assert e.text == "Hello, world!"
    assert e.voice == "af_bella"
    assert e.speed == 0.8
    assert e.duration_s == 3.14
    assert e.audio_path == "/tmp/my_output.wav"
    assert e.format == "mp3"
    assert isinstance(e.created_at, str)
    assert len(e.created_at) > 0  # timestamp was set


def test_add_generation_auto_increments(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    id1 = hist.add_generation("a", "v", 1.0, 1.0, "/a.wav", "wav")
    id2 = hist.add_generation("b", "v", 1.0, 1.0, "/b.wav", "wav")
    assert id2 > id1
    assert id2 - id1 == 1


# ===================================================================
# get_recent
# ===================================================================

def test_get_recent_returns_newest_first(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    for i in range(5):
        hist.add_generation(f"text_{i}", "v", 1.0, float(i), f"/{i}.wav", "wav")
    entries = hist.get_recent(10)
    assert len(entries) == 5
    # Most recent first -> descending ids.
    ids = [e.id for e in entries]
    assert ids == sorted(ids, reverse=True)


def test_get_recent_respects_limit(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    for i in range(20):
        hist.add_generation(f"text_{i}", "v", 1.0, 1.0, f"/{i}.wav", "wav")
    entries = hist.get_recent(limit=5)
    assert len(entries) == 5


def test_get_recent_empty_table_returns_empty_list(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    assert hist.get_recent(10) == []


def test_get_recent_default_limit_is_fifty(db_path: Path) -> None:
    """The default limit should be 50 so the history dialog doesn't
    load an unbounded number of rows."""
    hist = GenerationHistory(str(db_path))
    for i in range(60):
        hist.add_generation(f"text_{i}", "v", 1.0, 1.0, f"/{i}.wav", "wav")
    entries = hist.get_recent()  # no limit arg
    assert len(entries) == 50


# ===================================================================
# get_by_id
# ===================================================================

def test_get_by_id_returns_entry(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    eid = hist.add_generation("test text", "af_heart", 1.5, 4.2, "/t.wav", "flac")
    entry = hist.get_by_id(eid)
    assert entry is not None
    assert entry.text == "test text"
    assert entry.voice == "af_heart"
    assert entry.speed == 1.5
    assert entry.duration_s == 4.2
    assert entry.format == "flac"


def test_get_by_id_nonexistent_returns_none(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    assert hist.get_by_id(999) is None
    assert hist.get_by_id(-1) is None


# ===================================================================
# delete
# ===================================================================

def test_delete_removes_row(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    eid = hist.add_generation("test", "v", 1.0, 1.0, "/t.wav", "wav")
    assert hist.get_by_id(eid) is not None
    deleted = hist.delete(eid)
    assert deleted is True
    assert hist.get_by_id(eid) is None


def test_delete_nonexistent_returns_false(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    assert hist.delete(999) is False


def test_delete_leaves_other_rows_intact(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    id1 = hist.add_generation("a", "v", 1.0, 1.0, "/a.wav", "wav")
    id2 = hist.add_generation("b", "v", 1.0, 1.0, "/b.wav", "wav")
    id3 = hist.add_generation("c", "v", 1.0, 1.0, "/c.wav", "wav")
    hist.delete(id2)
    remaining = hist.get_recent(10)
    assert len(remaining) == 2
    remaining_ids = {e.id for e in remaining}
    assert id1 in remaining_ids
    assert id3 in remaining_ids


# ===================================================================
# clear
# ===================================================================

def test_clear_removes_all_rows(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    for i in range(5):
        hist.add_generation(f"t{i}", "v", 1.0, 1.0, f"/{i}.wav", "wav")
    removed = hist.clear()
    assert removed == 5
    assert hist.get_recent(10) == []


def test_clear_empty_table_returns_zero(db_path: Path) -> None:
    hist = GenerationHistory(str(db_path))
    assert hist.clear() == 0


# ===================================================================
# Edge cases & robustness
# ===================================================================

def test_add_and_retrieve_long_text(db_path: Path) -> None:
    """Very long text (e.g. a full chapter) must round-trip cleanly."""
    long_text = "Hello, world! " * 10_000  # ~150k chars
    hist = GenerationHistory(str(db_path))
    eid = hist.add_generation(long_text, "v", 1.0, 60.0, "/long.wav", "wav")
    entry = hist.get_by_id(eid)
    assert entry is not None
    assert len(entry.text) == len(long_text)
    assert entry.text == long_text


def test_add_with_special_characters(db_path: Path) -> None:
    """Text with Unicode, quotes, and emoji must survive SQLite round-trip."""
    special = "Café naïve — \"double\" 'single' 💯 <test> & special"
    hist = GenerationHistory(str(db_path))
    eid = hist.add_generation(special, "v", 1.0, 1.0, "/s.wav", "wav")
    entry = hist.get_by_id(eid)
    assert entry is not None
    assert entry.text == special


def test_multiple_additions_get_recent_order(db_path: Path) -> None:
    """Insert 100 entries and verify the 50 most recent are correct."""
    hist = GenerationHistory(str(db_path))
    for i in range(100):
        hist.add_generation(f"text_{i}", "v", 1.0, float(i), f"/{i}.wav", "wav")
    entries = hist.get_recent(50)
    assert len(entries) == 50
    # IDs should be 99, 98, ..., 50
    assert entries[0].id == 100
    assert entries[-1].id == 51


def test_pathlib_path_works_as_input(db_path: Path) -> None:
    """The constructor should accept both str and Path for db_path."""
    hist = GenerationHistory(db_path)  # Path, not str
    eid = hist.add_generation("test", "v", 1.0, 1.0, "/t.wav", "wav")
    assert eid >= 1
