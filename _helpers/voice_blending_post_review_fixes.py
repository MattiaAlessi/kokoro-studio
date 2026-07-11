"""Reviewer-flagged follow-up fixes for the voice-blending integration.

Applies 4 surgical edits, idempotently:
  R1 — `kokoro_studio/blending.py`: normalize `-0.0` alpha in
       `VoiceBlend.__post_init__` so the rounded cache key matches `0.0`.
  R2 — `kokoro_studio/gui.py` `__init__`: add a second
       `_repopulate_voice_list(None)` call AFTER `_load_blends()` so
       saved blends appear in the voice list on first paint.
  R3 — `kokoro_studio/gui.py`: tighten `blends` typing in
       `SynthesisWorker.__init__` and `_start_synthesis` to
       `Optional[Mapping[str, "VoiceBlend"]]` (matches engine signature).
  R4 — `kokoro_studio/gui.py`: add a `_preview_in_progress` re-entrancy
       guard so a click on Generate while a blend preview is synthesising
       can't double-up on the KPipeline.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> tuple[bytes, bool, str]:
    data = path.read_bytes()
    eol = b"\r\n" in data and data.count(b"\r\n") >= 100
    text = data.decode("utf-8")
    if eol:
        text = text.replace("\r\n", "\n")
    return data, eol, text


def _write(path: Path, eol: bool, text: str) -> None:
    if eol:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def _patch(label: str, path: Path, old: str, new: str) -> bool:
    _, eol, text = _read(path)
    if old not in text:
        print(f"ERROR: {label} anchor not found in {path.name}", file=sys.stderr)
        return False
    if text.count(old) > 1:
        print(
            f"ERROR: {label} anchor matches multiple locations in {path.name}",
            file=sys.stderr,
        )
        return False
    text = text.replace(old, new, 1)
    _write(path, eol, text)
    print(f"  {label} OK")
    return True


# ================================================================
# R1 — Normalise -0.0 alpha in VoiceBlend.__post_init__
# ================================================================
BLENDING = ROOT / "kokoro_studio" / "blending.py"
R1_OLD = '''        if not isinstance(self.alpha, (int, float)) or isinstance(self.alpha, bool):
            raise ValueError(
                f"alpha must be a real number in [0.0, 1.0], got {self.alpha!r}"
            )
        alpha_f = float(self.alpha)
        if not (0.0 <= alpha_f <= 1.0):
            raise ValueError(
                f"alpha must be in [0.0, 1.0], got {alpha_f}"
            )'''
R1_NEW = '''        if not isinstance(self.alpha, (int, float)) or isinstance(self.alpha, bool):
            raise ValueError(
                f"alpha must be a real number in [0.0, 1.0], got {self.alpha!r}"
            )
        alpha_f = float(self.alpha)
        if not (0.0 <= alpha_f <= 1.0):
            raise ValueError(
                f"alpha must be in [0.0, 1.0], got {alpha_f}"
            )
        # Normalise -0.0 to +0.0 so the rounded cache key matches the
        # `0.0` entry (otherwise two VoiceBlends with alpha=0.0 and
        # alpha=-0.0 would compute twice and cache twice). 0.0 + 0.0
        # is the canonical IEEE-754 identity that flips the sign bit.
        if alpha_f == 0.0:
            alpha_f = 0.0'''
if not _patch("R1 VoiceBlend -0.0 normalisation", BLENDING, R1_OLD, R1_NEW):
    sys.exit(1)


# ================================================================
# R2 — Add second _repopulate_voice_list(None) after _load_blends
# ================================================================
GUI = ROOT / "kokoro_studio" / "gui.py"
R2_OLD = '''        self._load_pron_dict()
        # Phase 2 - Voice Blending. Load BEFORE repopulate so
        # blend entries appear in the voice list on first paint.
        self._load_blends()
        self._update_button_states()'''
R2_NEW = '''        self._load_pron_dict()
        # Phase 2 - Voice Blending. Load blends so they're
        # available to the FIRST `_repopulate_voice_list` call
        # below; otherwise blends loaded from disk on first run
        # would never render in the voice list (the panel was
        # built before this hook ran).
        self._load_blends()
        # Rebuild the voice list now that the blend registry is
        # populated; without this, saved blends stay invisible
        # until the user saves a new one (which itself triggers
        # a repopulate via `_save_blend`).
        self._repopulate_voice_list(None)
        self._update_button_states()'''
if not _patch("R2 __init__ repopulate after _load_blends", GUI, R2_OLD, R2_NEW):
    sys.exit(1)


# ================================================================
# R3 — Tighten `blends` typing in SynthesisWorker + _start_synthesis
# ================================================================
# R3a — SynthesisWorker.__init__ signature
R3A_OLD = '''        # Phase 2 - Voice Blending. Snapshot of the GUI's
        # `_loaded_blends` dict at click time, so the worker
        # thread doesn't re-read disk between requests. Voice
        # blends are frozen dataclasses, so a shallow dict copy
        # is thread-safe.
        blends: Optional[dict] = None,
        parent: Optional[QObject] = None,'''
R3A_NEW = '''        # Phase 2 - Voice Blending. Snapshot of the GUI's
        # `_loaded_blends` dict at click time, so the worker
        # thread doesn't re-read disk between requests. Voice
        # blends are frozen dataclasses, so a shallow dict copy
        # is thread-safe.
        blends: Optional[Mapping[str, "VoiceBlend"]] = None,
        parent: Optional[QObject] = None,'''
if not _patch("R3a SynthesisWorker blends typing", GUI, R3A_OLD, R3A_NEW):
    sys.exit(1)

# R3b — _start_synthesis signature
R3B_OLD = '''        # Phase 2 - Voice Blending. Snapshotted blend registry
        # forwarded to the SynthesisWorker; if None, the engine
        # auto-loads from <Documents>/KokoroStudio/voice_blends.json.
        blends: Optional[dict] = None,
    ) -> None:'''
R3B_NEW = '''        # Phase 2 - Voice Blending. Snapshotted blend registry
        # forwarded to the SynthesisWorker; if None, the engine
        # auto-loads from <Documents>/KokoroStudio/voice_blends.json.
        blends: Optional[Mapping[str, "VoiceBlend"]] = None,
    ) -> None:'''
if not _patch("R3b _start_synthesis blends typing", GUI, R3B_OLD, R3B_NEW):
    sys.exit(1)


# ================================================================
# R4 — Preview re-entrancy guard
# ================================================================
# R4a — Pre-declare the flag in __init__ (next to _suppress_blend_alpha_sync)
R4A_OLD = '''        # Suppresses the alpha_slider <-> alpha_spin feedback loop.
        self._suppress_blend_alpha_sync = False'''
R4A_NEW = '''        # Suppresses the alpha_slider <-> alpha_spin feedback loop.
        self._suppress_blend_alpha_sync = False
        # Set by `_on_preview_blend_clicked` while a preview is
        # synthesising on the GUI thread. The SynthesisWorker
        # check (`_worker.isRunning()`) does NOT cover this case
        # because the preview is synchronous `generate_speech` —
        # a Generate click during preview would otherwise launch
        # a second `pipeline(...)` on the same KPipeline.
        self._preview_in_progress = False'''
if not _patch("R4a __init__ _preview_in_progress flag", GUI, R4A_OLD, R4A_NEW):
    sys.exit(1)

# R4b — Guard the preview click: refuse to start if a preview is already running
R4B_OLD = '''    def _on_preview_blend_clicked(self) -> None:
        """Ad-hoc preview of the panel's CURRENTLY-EDITED blend.

        Uses `voice_blend=(a, b, alpha)` so the user can hear a
        tweak before saving it as a preset.
        """
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Busy",
                "A generation is already running. Stop it first "
                "to preview a new blend.",
            )
            return'''
R4B_NEW = '''    def _on_preview_blend_clicked(self) -> None:
        """Ad-hoc preview of the panel's CURRENTLY-EDITED blend.

        Uses `voice_blend=(a, b, alpha)` so the user can hear a
        tweak before saving it as a preset. Synthesis runs on
        the GUI thread (short phrase, ~1-2 s); a re-entrancy
        flag prevents a Generate click from racing against the
        synchronous `generate_speech` call.
        """
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Busy",
                "A generation is already running. Stop it first "
                "to preview a new blend.",
            )
            return
        if self._preview_in_progress:
            return  # silently drop the second click'''
if not _patch("R4b _on_preview_blend_clicked guard", GUI, R4B_OLD, R4B_NEW):
    sys.exit(1)

# R4c — Set/clear the flag around the synchronous generate_speech call
R4C_OLD = '''        try:
            _audio = generate_speech(
                text=_phrase, voice_blend=_blend,
                output_path=_out_path, speed=1.0,
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Blend preview failed",
                f"{type(e).__name__}: {e}",
            )
            return
        self._last_audio_path = _out_path
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(_out_path))
        self._player.play()
        self._play_btn.setEnabled(True)
        self._status_label.setText(
            f"Blend preview  \u00b7  {int(round(_alpha*100))}% {_va} + "
            f"{int(round((1.0-_alpha)*100))}% {_vb}  \u00b7  "
            f"{len(_audio)/SAMPLE_RATE:.2f}s"
        )'''
R4C_NEW = '''        self._preview_in_progress = True
        try:
            _audio = generate_speech(
                text=_phrase, voice_blend=_blend,
                output_path=_out_path, speed=1.0,
            )
        except Exception as e:
            self._preview_in_progress = False
            QMessageBox.critical(
                self, "Blend preview failed",
                f"{type(e).__name__}: {e}",
            )
            return
        finally:
            self._preview_in_progress = False
        self._last_audio_path = _out_path
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(_out_path))
        self._player.play()
        self._play_btn.setEnabled(True)
        self._status_label.setText(
            f"Blend preview  \u00b7  {int(round(_alpha*100))}% {_va} + "
            f"{int(round((1.0-_alpha)*100))}% {_vb}  \u00b7  "
            f"{len(_audio)/SAMPLE_RATE:.2f}s"
        )'''
if not _patch("R4c _on_preview_blend_clicked flag set/clear", GUI, R4C_OLD, R4C_NEW):
    sys.exit(1)


# ================================================================
# Final syntax check
# ================================================================
import ast
for p in (BLENDING, GUI):
    try:
        ast.parse(p.read_text(encoding="utf-8"))
        print(f"  {p.name} SYNTAX OK")
    except SyntaxError as e:
        print(f"  {p.name} SYNTAX ERROR: {e}", file=sys.stderr)
        sys.exit(1)

print("\nAll post-review fixes applied.")
