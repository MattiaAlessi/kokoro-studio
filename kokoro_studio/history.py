# -*- coding: utf-8 -*-
"""Generation history persistence for Kokoro Studio.

Phase 3 — "Generation History". Keeps a lightweight SQLite log of every
successful synthesis so users can replay, re-export, or reload previous
generations without re-synthesising.

Public API:
    GenerationHistory
        High-level wrapper around a SQLite database. Thread-safe for the
        typical Kokoro Studio usage pattern (writes from the GUI thread,
        reads from the GUI thread).

Schema:
    history
        id            INTEGER PRIMARY KEY AUTOINCREMENT
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        text          TEXT     -- full input text (may be long)
        voice         TEXT     -- voice / blend identifier
        speed         REAL     -- speed multiplier used
        duration_s    REAL     -- generated audio duration in seconds
        audio_path    TEXT     -- absolute path to the saved audio file
        format        TEXT     -- output format ('wav', 'mp3', 'flac', 'ogg')

Notes:
    * Uses the built-in `sqlite3` module — no extra dependencies.
    * Stores the original file path, not a copy. If the user deletes the
      original audio, the history entry remains but playback will fail
      gracefully (the GUI should disable the Play action when the file
      is missing).
    * All writes are single-row INSERTs; they run on the GUI thread via
      the `finished_ok` signal, so there is no cross-thread contention.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Public data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HistoryEntry:
    """Immutable view of a single generation history row."""

    id: int
    created_at: str
    text: str
    voice: str
    speed: float
    duration_s: float
    audio_path: str
    format: str


# ---------------------------------------------------------------------------
# History manager
# ---------------------------------------------------------------------------

class GenerationHistory:
    """SQLite-backed generation history.

    Parameters:
        db_path: Path to the SQLite database file. If the file does not
            exist it will be created, along with the schema.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ---- schema --------------------------------------------------------
    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    text TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    speed REAL NOT NULL,
                    duration_s REAL NOT NULL,
                    audio_path TEXT NOT NULL,
                    format TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_history_created_at
                ON history(created_at DESC)
                """
            )

    # ---- public operations ---------------------------------------------
    def add_generation(
        self,
        text: str,
        voice: str,
        speed: float,
        duration_s: float,
        audio_path: str,
        output_format: str,
    ) -> int:
        """Insert a new history row and return its generated id."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO history
                    (text, voice, speed, duration_s, audio_path, format)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (text, voice, speed, duration_s, audio_path, output_format),
            )
            return int(cursor.lastrowid)

    def get_recent(self, limit: int = 50) -> List[HistoryEntry]:
        """Return the most recent `limit` history entries."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, created_at, text, voice, speed,
                       duration_s, audio_path, format
                FROM history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [HistoryEntry(**dict(row)) for row in cursor.fetchall()]

    def get_by_id(self, entry_id: int) -> Optional[HistoryEntry]:
        """Return a single history entry by id, or None if not found."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, created_at, text, voice, speed,
                       duration_s, audio_path, format
                FROM history
                WHERE id = ?
                """,
                (entry_id,),
            )
            row = cursor.fetchone()
            return HistoryEntry(**dict(row)) if row else None

    def delete(self, entry_id: int) -> bool:
        """Delete a history entry by id. Returns True if a row was removed."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    def clear(self) -> int:
        """Delete all history entries. Returns the number of rows removed."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM history")
            return cursor.rowcount
