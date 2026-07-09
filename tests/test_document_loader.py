# -*- coding: utf-8 -*-
"""Smoke tests for `kokoro_studio.document_loader`."""

from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path

import pytest

from kokoro_studio import document_loader as dl


# ---------------------------------------------------------------------------
# Document dataclass
# ---------------------------------------------------------------------------

def test_document_field_set():
    names = {f.name for f in dataclasses.fields(dl.Document)}
    assert {"title", "chapters", "full_text",
            "author", "language", "source_path", "skipped"} <= names


def test_load_dispatch_unsupported_ext():
    with pytest.raises(ValueError, match="Unsupported"):
        dl.load_document("foo.docx")


def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        dl.load_document("/no/such/path.txt")


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------

def test_txt_roundtrip_ascii():
    content = "Hello world! Ciao Italy. " + "A" * 500 + " End."
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test.txt"
        # Binary write to avoid platform newline translation (CRLF on Windows).
        p.write_bytes(content.encode("ascii"))
        doc = dl.load_document(p)
    assert doc.title == "test"
    assert doc.chapters == [content]
    assert doc.full_text == content
    assert doc.source_path == p
    assert doc.skipped == []


def test_txt_crlf_normalized_to_lf():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test.txt"
        p.write_bytes(b"line1\r\nline2\r\nline3")
        doc = dl.load_document(p)
    assert doc.full_text == "line1\nline2\nline3"


def test_txt_empty():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "empty.txt"
        p.write_bytes(b"   \n\n   ")
        doc = dl.load_document(p)
    # After strip(), the result is empty so the chapters list is empty too.
    assert doc.full_text == ""
    assert doc.chapters == []


# ---------------------------------------------------------------------------
# UTF-8 with errors='replace'
# ---------------------------------------------------------------------------

def test_txt_invalid_utf8_replaced_not_crashed():
    """A non-UTF-8 byte sequence shouldn't crash the loader."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "weird.txt"
        # 0xC3 0x28 is a truncated 2-byte UTF-8 sequence.
        p.write_bytes(b"Hello \xc3\x28 world")
        doc = dl.load_document(p)
    # Whatever the exact replacement, we just need it not to crash.
    assert "Hello" in doc.full_text and "world" in doc.full_text
