"""Finalize the voice-blending worker plumbing.

The first run of `_helpers/voice_blending_worker_plumb.py` exited at W5
without calling `write()`, so W1-W4 changes were lost in memory.
This script applies the missing pieces (W1, W2, W3, W4) + the
post-review fixes that didn't run (R3A, R3B, R3C, R4A, R4B, R4C)
in a single pass with a guaranteed `write()` at the end.

Idempotent: each fix checks whether its NEW content is already
present; if so, it skips silently. If the OLD anchor is missing
AND the NEW content is already present, the fix is a no-op.
If neither is present, the fix errors out.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "kokoro_studio" / "gui.py"
BLENDING = ROOT / "kokoro_studio" / "blending.py"


def _read(path: Path) -> tuple[bool, str]:
    data = path.read_bytes()
    eol = b"\r\n" in data and data.count(b"\r\n") >= 100
    text = data.decode("utf-8")
    if eol:
        text = text.replace("\r\n", "\n")
    return eol, text


def _write(path: Path, eol: bool, text: str) -> None:
    if eol:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def _apply(label: str, path: Path, old: str, new: str) -> bool:
    """Apply a fix; idempotent. Returns True on success."""
    eol, text = _read(path)
    if new in text:
        print(f"  {label}: already applied, skipping")
        return True
    if old not in text:
        print(f"ERROR: {label} anchor not found and NEW not present",
              file=sys.stderr)
        return False
    if text.count(old) > 1:
        print(f"ERROR: {label} anchor matches multiple locations",
              file=sys.stderr)
        return False
    text = text.replace(old, new, 1)
    _write(path, eol, text)
    print(f"  {label} OK")
    return True


# ================================================================
# W1 — SynthesisWorker.__init__ signature: add `blends=...`
# ================================================================
W1_OLD = """        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        parent: Optional[QObject] = None,
"""
W1_NEW = """        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        # Phase 2 - Voice Blending. Snapshot of the GUI's
        # `_loaded_blends` dict at click time, so the worker
        # thread doesn't re-read disk between requests. Voice
        # blends are frozen dataclasses, so a shallow dict copy
        # is thread-safe.
        blends: Optional[Mapping[str, "VoiceBlend"]] = None,
        parent: Optional[QObject] = None,
"""
ok = True
ok &= _apply("W1 SynthesisWorker.__init__ accepts blends=", GUI, W1_OLD, W1_NEW)


# ================================================================
# W2 — SynthesisWorker.__init__ body: snapshot `self._blends`
# ================================================================
W2_OLD = """        # Phase 2 \u2014 Multi-Speaker Dialogue Mode. When True the engine
        # parses `[voice_name]:` markers in `text` and synthesises each
        # segment with its own voice. `speaker_gap_s` is the silence
        # inserted between segments (default 0.25 s).
        self._multi_speaker = multi_speaker
        self._speaker_gap_s = speaker_gap_s
"""
W2_NEW = """        # Phase 2 \u2014 Multi-Speaker Dialogue Mode. When True the engine
        # parses `[voice_name]:` markers in `text` and synthesises each
        # segment with its own voice. `speaker_gap_s` is the silence
        # inserted between segments (default 0.25 s).
        self._multi_speaker = multi_speaker
        self._speaker_gap_s = speaker_gap_s
        # Phase 2 - Voice Blending. Shallow snapshot copy so the
        # worker doesn't share the GUI's dict reference (the user
        # could open the dict editor while we're synthesising).
        self._blends: Optional[dict] = (
            dict(blends) if blends else None
        )
"""
ok &= _apply("W2 SynthesisWorker.__init__ snapshots blends", GUI, W2_OLD, W2_NEW)


# ================================================================
# W3 — SynthesisWorker.run(): pass `blends=self._blends`
# ================================================================
W3_OLD = """            audio = generate_speech(
                text=self._text,
                voice=self._voice,
                speed=self._speed,
                output_path=self._output_path,
                output_format=self._output_format,
                pronunciation_rules=self._pronunciation_rules,
                multi_speaker=self._multi_speaker,
                speaker_gap_s=self._speaker_gap_s,
                on_chunk=self._on_chunk,
                stop_check=self._stop_check,
            )
"""
W3_NEW = """            audio = generate_speech(
                text=self._text,
                voice=self._voice,
                speed=self._speed,
                output_path=self._output_path,
                output_format=self._output_format,
                pronunciation_rules=self._pronunciation_rules,
                multi_speaker=self._multi_speaker,
                speaker_gap_s=self._speaker_gap_s,
                on_chunk=self._on_chunk,
                stop_check=self._stop_check,
                # Phase 2 - Voice Blending. Pass the snapshotted
                # blend registry to the engine so it can resolve
                # saved blend names to tensors per-segment.
                blends=self._blends,
            )
"""
ok &= _apply("W3 SynthesisWorker.run forwards blends=", GUI, W3_OLD, W3_NEW)


# ================================================================
# W4 — _start_synthesis signature: add `blends: Optional[...] = None`
# ================================================================
W4_OLD = """        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
    ) -> None:
"""
W4_NEW = """        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        # Phase 2 - Voice Blending. Snapshotted blend registry
        # forwarded to the SynthesisWorker; if None, the engine
        # auto-loads from <Documents>/KokoroStudio/voice_blends.json.
        blends: Optional[Mapping[str, "VoiceBlend"]] = None,
    ) -> None:
"""
ok &= _apply("W4 _start_synthesis accepts blends=", GUI, W4_OLD, W4_NEW)


# ================================================================
# Post-review fixes that didn't run
# ================================================================
# R1 was already applied by the post-review script — skip.
# R2 was already applied by the post-review script — skip.
# R3A, R3B, R3C, R4A, R4B, R4C need to run.

# R3B — _start_synthesis signature already tightened by W4 (uses Mapping)
# so R3B is effectively a no-op. Skip.
# R3C — was about a body change. Let me re-check.

# Actually, the post-review script applied R1 and R2 but failed at R3A.
# Let me re-run R3A through R4C from the post-review script.

# R3A — SynthesisWorker blends typing (now also covered by W1's Mapping)
# Since W1 already uses Optional[Mapping[str, "VoiceBlend"]], R3A is a no-op.
# Skip.

# R3B — _start_synthesis blends typing (now covered by W4)
# Skip.

# R3C — Was supposed to update the SynthesisWorker body to use Mapping?
# No, R3C was about adding a finally block to the preview. Let me re-read.

# The post-review fixes script's R3A-R3C are:
# - R3A: SynthesisWorker blends typing (covered by W1)
# - R3B: _start_synthesis blends typing (covered by W4)
# - R3C: not present in the original post-review script; I miscounted

# The post-review fixes that DID need to run are R4A, R4B, R4C.

# R4A — Pre-declare _preview_in_progress flag
R4A_OLD = """        # Suppresses the alpha_slider <-> alpha_spin feedback loop.
        self._suppress_blend_alpha_sync = False
"""
R4A_NEW = """        # Suppresses the alpha_slider <-> alpha_spin feedback loop.
        self._suppress_blend_alpha_sync = False
        # Set by `_on_preview_blend_clicked` while a preview is
        # synthesising on the GUI thread. The SynthesisWorker
        # check (`_worker.isRunning()`) does NOT cover this case
        # because the preview is synchronous `generate_speech` \u2014
        # a Generate click during preview would otherwise launch
        # a second `pipeline(...)` on the same KPipeline.
        self._preview_in_progress = False
"""
ok &= _apply("R4A __init__ _preview_in_progress flag", GUI, R4A_OLD, R4A_NEW)


# R4B — Guard the preview click: refuse to start if a preview is already running
R4B_OLD = """    def _on_preview_blend_clicked(self) -> None:
        \"\"\"Ad-hoc preview of the panel's CURRENTLY-EDITED blend.

        Uses `voice_blend=(a, b, alpha)` so the user can hear a
        tweak before saving it as a preset.
        \"\"\"
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Busy",
                "A generation is already running. Stop it first "
                "to preview a new blend.",
            )
            return
"""
R4B_NEW = """    def _on_preview_blend_clicked(self) -> None:
        \"\"\"Ad-hoc preview of the panel's CURRENTLY-EDITED blend.

        Uses `voice_blend=(a, b, alpha)` so the user can hear a
        tweak before saving it as a preset. Synthesis runs on
        the GUI thread (short phrase, ~1-2 s); a re-entrancy
        flag prevents a Generate click from racing against the
        synchronous `generate_speech` call.
        \"\"\"
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Busy",
                "A generation is already running. Stop it first "
                "to preview a new blend.",
            )
            return
        if self._preview_in_progress:
            return  # silently drop the second click
"""
ok &= _apply("R4B _on_preview_blend_clicked guard", GUI, R4B_OLD, R4B_NEW)


# R4C — Set/clear the flag around the synchronous generate_speech call
R4C_OLD = """        try:
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
        )
"""
R4C_NEW = """        self._preview_in_progress = True
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
        )
"""
ok &= _apply("R4C _on_preview_blend_clicked flag set/clear", GUI, R4C_OLD, R4C_NEW)


# ================================================================
# Final syntax check
# ================================================================
for p in (GUI, BLENDING):
    try:
        ast.parse(p.read_text(encoding="utf-8"))
        print(f"  {p.name} SYNTAX OK")
    except SyntaxError as e:
        print(f"  {p.name} SYNTAX ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if not ok:
    print("\nSome fixes failed.", file=sys.stderr)
    sys.exit(1)
print("\nAll worker plumbing + post-review fixes applied.")
