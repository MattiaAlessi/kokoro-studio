# -*- coding: utf-8 -*-
"""Pronunciation Dictionary for Kokoro Studio.

Public API:
    load_dictionary(path)              -> Dict[str, str]
    save_dictionary(path, rules)       -> None
    apply_substitutions(text, rules)   -> str

The dictionary is a flat mapping `find -> replace` of substrings that
should be rewritten in the input text *before* TTS synthesis kicks in.
Substitution rules are matched:

  * **Whole-word only** — anchored by `\b` so a rule for "TTS" does
    NOT match inside "MTTS". Python's `\b` is Unicode-aware by default
    so non-ASCII keys (Italian accented chars, Japanese kanji) are
    also handled correctly.
  * **Case-sensitive** — "Kokoro" will NOT match "KOKORO" or "kokoro".
    This avoids silent mangling of acronyms and proper nouns; users
    who want case-insensitive behaviour can add multiple rules.
  * **Longest-first** — sorted by descending length so a rule for
    "Kokoro" beats overlapping rules for "K" before they fire.
  * **Single pass** — the whole rule set is compiled into ONE regex
    rather than chaining `str.replace` per rule, so a key like
    "A -> B" plus another "B -> C" never cascades to "A -> C".

JSON schema lives at `Documents/KokoroStudio/pronunciation.json`:

    {
      "version": 1,
      "rules": [
        {"find": "Kokoro", "replace": "Ko-ko-ro"},
        {"find": "TTS",    "replace": "tee-tee-ess"},
        {"find": "GPU",    "replace": ""}
      ]
    }

`version: 1` is forward-compat — future fields like `case_sensitive`,
`enabled`, or `language` can be added without breaking older files.

This module has zero PySide6 deps so it can run headlessly in tests and
from any future CLI / batch mode.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict


# Current schema version. Bump only when we make a backwards-incompatible
# change to the JSON shape.
_SCHEMA_VERSION: int = 1


# -----------------------------------------------------------------------
# Persistent store: load / save
# -----------------------------------------------------------------------

def load_dictionary(path: Path) -> Dict[str, str]:
    """Load a pronunciation dictionary from `path`.

    Returns an empty dict when:
      * the file doesn't exist yet (first-run scenario)
      * the file is malformed JSON
      * the file is a valid JSON but doesn't conform to the schema
        (e.g. a legacy flat dict, an old unsupported version)

    All failure modes are logged at WARNING level — not raised — so the
    GUI can recover gracefully rather than refusing to launch.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.warning(
            "[pronunciation] could not read %s: %s", path, e
        )
        return {}

    if not isinstance(data, dict):
        logging.warning(
            "[pronunciation] %s: top-level JSON is not an object", path
        )
        return {}
    if "rules" not in data:
        # Could be a legacy flat dict {Kokoro: Ko-ko-ro}. Migrate it.
        migrated: Dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                migrated[k] = v
        if migrated:
            logging.info(
                "[pronunciation] %s: migrated legacy flat schema (%d rules)",
                path, len(migrated),
            )
        return migrated

    rules: Dict[str, str] = {}
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        logging.warning(
            "[pronunciation] %s: 'rules' is not a list", path
        )
        return {}
    for i, rule in enumerate(raw_rules):
        if not isinstance(rule, dict):
            logging.warning(
                "[pronunciation] %s: rule #%d is not an object; skipped",
                path, i,
            )
            continue
        find = rule.get("find", "")
        if not isinstance(find, str):
            continue
        find = find.strip()
        if not find:
            # Empty `find` is meaningless (matches empty string everywhere),
            # so we drop those silently — the UI shouldn't allow them anyway.
            continue
        replace = rule.get("replace", "")
        # `replace may be empty (valid: delete the word); but if it's the
        # # wrong type, fall back to empty string.
        if not isinstance(replace, str):
            replace = ""
        rules[find] = replace

    version = data.get("version", 1)
    if isinstance(version, int) and version > _SCHEMA_VERSION:
        logging.warning(
            "[pronunciation] %s has version %d (newer than supported %d); "
            "loading unknown fields as best-effort",
            path, version, _SCHEMA_VERSION,
        )
    return rules


def save_dictionary(path: Path, rules: Dict[str, str]) -> None:
    """Persist `rules` to `path` as JSON.

    Creates parent directories on demand. Overwrites any existing file.
    Order of rules in JSON matches the iteration order of the input
    dict (CPython 3.7+ preserves insertion order).
    """
    payload = {
        "version": _SCHEMA_VERSION,
        "rules": [
            {"find": k, "replace": v} for k, v in rules.items()
        ],
    }
    parent = path.parent
    if parent and not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(
                f"Cannot create pronunciation directory {parent}: {e}"
            ) from e
    # `ensure_ascii=False` keeps non-ASCII find/replace strings human-
    # readable in the JSON file (Italian, Japanese users prefer this).
    # `indent=2` makes diff-able diffs in version control.
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------
# In-memory substitution
# -----------------------------------------------------------------------

# Module-level cache of compiled regexes, keyed by frozenset of rules.
# Lets us skip re-compiling the same alternation regex every time a
# user clicks "Generate" with an unchanged dict.
_REGEX_CACHE: Dict[int, "re.Pattern[str]"] = {}


def apply_substitutions(text: str, rules: Dict[str, str]) -> str:
    """Apply `rules` to `text` in a single regex pass.

    Semantics (see module docstring for details):
      * whole-word, anchored by `\b`
      * case-sensitive
      * longest-first ordering done via sorted key lengths
      * empty `replace` value deletes the matched word
      * empty rules OR empty text => identity (fast path)

    Returns:
        The rewritten text (a new str object — the input is not mutated).
    """
    if not rules or not text:
        return text

    # Stable key for the cache: frozenset of all keys. We deliberately
    # DON'T include values because deltas in replace strings don't
    # change the regex pattern.
    cache_key = hash(frozenset(rules.keys()))
    pattern = _REGEX_CACHE.get(cache_key)
    if pattern is None:
        # Sort longest-first so e.g. "TTS" beats "TT" before "TT" wins.
        sorted_keys = sorted(rules.keys(), key=len, reverse=True)
        escaped = [re.escape(k) for k in sorted_keys]
        pattern = re.compile(r"\b(?:" + "|".join(escaped) + r")\b")
        _REGEX_CACHE[cache_key] = pattern

    return pattern.sub(lambda m: rules[m.group(0)], text)


# -----------------------------------------------------------------------
# CLI smoke-test
# -----------------------------------------------------------------------

def _cli_main() -> int:  # pragma: no cover
    """`python pronunciation.py <cmd> [args...]` smoke harness.

    Supports:
        sub <rules.json> <input.txt>      # print substituted text
        demo                              # run canned test cases
    """
    import sys
    if len(sys.argv) < 2:
        print("usage: python pronunciation.py {demo|sub FILE INPUT}",
              file=sys.stderr)
        return 2

    if sys.argv[1] == "demo":
        rules = {
            "Kokoro": "Ko-ko-ro",
            "TTS":    "tee-tee-ess",
            "TT":     "x",  # longer-rule-wins means TTS still beats this
            "this":   "",
            "hello":  "y",  # case-sensitive: "Hello" stays
            "GPU":    "",
        }
        text = "Kokoro Kokoro I love TTS, TT hello world remove this"
        out = apply_substitutions(text, rules)
        print("INPUT :", text)
        print("RULES :", rules)
        print("OUTPUT:", out)
        return 0

    if sys.argv[1] == "sub" and len(sys.argv) == 4:
        rules = load_dictionary(Path(sys.argv[2]))
        with open(sys.argv[3], "r", encoding="utf-8") as f:
            text = f.read()
        print(apply_substitutions(text, rules))
        return 0

    print(f"unknown command: {sys.argv[1]}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_cli_main())
