# -*- coding: utf-8 -*-
"""Document loaders for Kokoro Studio (TXT / PDF / EPUB).

Public API:
    load_document(path)  -> Document

A `Document` carries both the joined `full_text` (handy for the editor
pane today) and a per-chapter `chapters` list (handy for Phase 4's
Audiobook Builder — re-parsing the EPUB redundantly is wasteful).

The default mapping by file extension is:
    *.txt   -> _load_txt   (UTF-8 with errors='replace')
    *.pdf   -> _load_pdf   (pypdf)
    *.epub  -> _load_epub  (ebooklib + BeautifulSoup html.parser)

This module has zero PySide6 / GUI imports so it can run headlessly in
tests and in the Phase 4 audiobook builder CLI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union


# -----------------------------------------------------------------------
# Public types
# -----------------------------------------------------------------------

@dataclass
class Document:
    """Loaded document with chapter granularity.

    Attributes:
        title:        Best-effort document title from the EPUB's Dublin
                      Core metadata, else the file stem.
        author:       Best-effort author(s) from EPUB DC:creator, else
                      `None`. Empty string normalises to None so callers
                      can do `if doc.author:` without surprise.
        language:     Best-effort language code (e.g. 'en', 'it') from
                      EPUB DC:language, else None.
        chapters:     Ordered list of chapter texts. For TXT/PDF today
                      this is a single-element list with the entire
                      document body. For EPUB we keep one entry per
                      ITEM_DOCUMENT so Phase 4 can iterate chapters
                      without re-parsing.
        full_text:    `"\n\n".join(chapters)` — what the GUI dumps into
                      the editor.
        source_path:  Where the document was loaded from. Useful for
                      logging and for the Audiobook Builder's progress
                      checkpoint file.
        skipped:      Names/ids of EPUB items that failed to parse and
                      were skipped. Empty list if everything succeeded.
                      GUI surfaces this in the status bar.
    """
    title: str
    chapters: List[str]
    full_text: str
    author: Optional[str] = None
    language: Optional[str] = None
    source_path: Optional[Path] = None
    skipped: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------
# Loader entry point
# -----------------------------------------------------------------------

_SUPPORTED_EXTS = (".txt", ".pdf", ".epub")


def load_document(path: Union[str, Path]) -> Document:
    """Load a TXT / PDF / EPUB file from disk.

    Dispatch is by file extension. Unknown extensions raise ValueError
    so the GUI can show a friendly error without crashing.

    Args:
        path: filesystem path to the document.

    Returns:
        A `Document` with at least `full_text` populated.

    Raises:
        FileNotFoundError: if `path` doesn't exist.
        ValueError:        if the extension isn't supported.
        ImportError:       propagated from the underlying parser when a
                           third-party library is missing (pypdf,
                           ebooklib, bs4). The GUI catches this and
                           prompts the user to install deps.
        Exception:         any underlying parse failure (encrypted PDF,
                           malformed EPUB manifest, etc.) — re-raised
                           with the original traceback so the user
                           sees the real cause.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {p}")
    ext = p.suffix.lower()
    if ext not in _SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported document extension '{ext}'. "
            f"Supported: {list(_SUPPORTED_EXTS)}"
        )

    if ext == ".txt":
        doc = _load_txt(p)
    elif ext == ".pdf":
        doc = _load_pdf(p)
    else:  # .epub
        doc = _load_epub(p)

    doc.source_path = p
    return doc


# -----------------------------------------------------------------------
# Format implementations
# -----------------------------------------------------------------------

def _load_txt(path: Path) -> Document:
    """Read a plain-text file.

    Decoding strategy: read binary, then UTF-8 with `errors='replace'` so
    any malformed bytes become the Unicode replacement character
    (U+FFFD) instead of crashing. This isn't perfect for non-UTF-8
    documents but is dramatically simpler than pulling in `chardet` and
    handles the "weird Latin-1 word in a UTF-8 file" edge case well
    enough for TTS.

    Newlines are normalized to LF so CRLF-authored files (Notepad on
    Windows, classic Mac OS, etc.) compare cleanly with LF-authored ones
    in tests and downstream chunking.
    """
    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    # Some old Mac files use bare \r as the line ending (no \n).
    text = text.replace("\r", "\n")
    text = text.strip()
    return Document(
        title=path.stem,
        chapters=[text] if text else [],
        full_text=text,
    )


def _load_pdf(path: Path) -> Document:
    """Extract per-page text from a PDF via pypdf.

    Notes:
        - `pypdf.PdfReader.extract_text()` may insert spaces around
          soft-hyphen breaks; Kokoro's tokenizer normally handles
          these OK but downstream chapters (Phase 4) may want to
          run a de-hyphenation pass.
        - Scanned PDFs containing only images produce empty strings;
          we silently drop those pages rather than failing.
        - Encrypted/password-protected PDFs raise an exception we
          don't catch here — the GUI surfaces the original error.
    """
    # Imported lazily so a missing pypdf doesn't break TXT import.
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(path))
    chapters: List[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception as e:
            # Single-page parse failure shouldn't kill the whole import.
            logging.warning("[document_loader] PDF page skipped: %s", e)
            continue
        t = t.strip()
        if t:
            chapters.append(t)

    full_text = "\n\n".join(chapters)
    return Document(
        title=path.stem,
        chapters=chapters,
        full_text=full_text,
    )


def _load_epub(path: Path) -> Document:
    """Parse an EPUB into per-`ITEM_DOCUMENT` chapters.

    Follows the approach documented in `PLAN.md`:
        1. Iterate `book.get_items()` filtered to `ITEM_DOCUMENT` (=9).
        2. Read raw XHTML via `item.get_body_content().decode('utf-8')`.
        3. Strip HTML with `BeautifulSoup(..., 'html.parser').get_text()`.
        4. Suppress ebooklib's noisy warnings (broken manifest links).
        5. Per-item try/except so one malformed item doesn't kill the
           whole book.

    Reading order uses `book.spine` so chapter N+2 isn't accidentally
    rendered before N+1 because the item order in the manifest doesn't
    match the reading order (common in EPUBs with nested sub-books or
    footnotes).
    """
    # Lazy imports: missing libs only break this code path.
    from ebooklib import epub, ITEM_DOCUMENT  # type: ignore
    from bs4 import BeautifulSoup              # type: ignore

    # The ebooklib backend emits `epub.BadManifest` and friends on
    # broken-metadata EPUBs at WARNING level. We don't want them
    # spammed into the GUI's stderr on every load.
    logging.getLogger("ebooklib").setLevel(logging.ERROR)

    book = epub.read_epub(str(path))

    # Build map id -> item for ordered traversal via spine.
    items_by_id = {
        item.get_id(): item
        for item in book.get_items()
    }

    ordered_ids: List[str] = []
    for spine_ref, _linear in book.spine:
        # spine items can be either by id (string) or actual item; handle both.
        if isinstance(spine_ref, str):
            ordered_ids.append(spine_ref)
        else:
            ordered_ids.append(spine_ref.get_id())

    chapters: List[str] = []
    skipped: List[str] = []
    for item_id in ordered_ids:
        item = items_by_id.get(item_id)
        if item is None:
            # Spine referenced an id that's not in the manifest. Skipping
            # silently is the right call — inventory files / nav docs
            # are spine-referenced but not `ITEM_DOCUMENT`. We only mark
            # the item as skipped if it actually IS an ITEM_DOCUMENT but
            # failed to parse; missing ids are bookkeeping noise.
            continue
        if item.get_type() != ITEM_DOCUMENT:
            continue
        try:
            raw = item.get_body_content()
            if not raw:
                continue
            body = raw.decode("utf-8", errors="replace")
            # `html.parser` avoids pulling lxml's C deps on Windows.
            text = BeautifulSoup(body, "html.parser").get_text(
                separator="\n"
            )
            # Collapse runs of blank lines + trim whitespace.
            text = "\n".join(line.rstrip() for line in text.splitlines())
            text = "\n\n".join(
                block for block in text.split("\n\n") if block.strip()
            ).strip()
            if text:
                chapters.append(text)
        except Exception as e:
            # One malformed item shouldn't tank the whole book.
            skipped.append(item_id)
            logging.warning(
                "[document_loader] EPUB item %r skipped: %s", item_id, e
            )
            continue

    full_text = "\n\n".join(chapters)

    # Best-effort Dublin Core metadata. Every lookup try/except'd — a
    # malformed EPUB can make individual metadata calls blow up even
    # when `read_epub` succeeded.
    title = path.stem
    author: Optional[str] = None
    language: Optional[str] = None
    try:
        m = book.get_metadata("DC", "title")
        if m and m[0] and m[0][0]:
            t = str(m[0][0]).strip()
            if t:
                title = t
    except Exception:
        pass
    try:
        m = book.get_metadata("DC", "creator")
        if m and m[0] and m[0][0]:
            a = str(m[0][0]).strip()
            if a:
                author = a
    except Exception:
        pass
    try:
        m = book.get_metadata("DC", "language")
        if m and m[0] and m[0][0]:
            lg = str(m[0][0]).strip()
            if lg:
                language = lg
    except Exception:
        pass

    return Document(
        title=title,
        author=author,
        language=language,
        chapters=chapters,
        full_text=full_text,
        skipped=skipped,
    )


# -----------------------------------------------------------------------
# CLI smoke-test entry point
# -----------------------------------------------------------------------

def _cli_main() -> int:  # pragma: no cover
    """Headless smoke-test entry point: `python document_loader.py <file>`."""
    import sys
    if len(sys.argv) != 2:
        print("usage: python document_loader.py <path-to-txt|pdf|epub>",
              file=sys.stderr)
        return 2
    try:
        doc = load_document(sys.argv[1])
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"title:    {doc.title}")
    print(f"chapters: {len(doc.chapters)}")
    print(f"chars:    {len(doc.full_text):,}")
    if doc.chapters:
        preview = doc.full_text[:400].replace("\n", " ")
        print(f"preview:  {preview!r}{'...' if len(doc.full_text) > 400 else ''}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_cli_main())
