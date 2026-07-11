"""Surgical edits to plumb `blends=` through SynthesisWorker + _start_synthesis.

Mirrors the existing `pronunciation_rules=` plumbing pattern (snapshot
at construction time, pass-through in run() / _start_synthesis).
Idempotent: re-running just no-ops.

Five targeted edits:
  W1 — SynthesisWorker.__init__ signature: add `blends: Optional[dict] = None`
  W2 — SynthesisWorker.__init__ body: snapshot `self._blends`
  W3 — SynthesisWorker.run(): pass `blends=self._blends` to generate_speech
  W4 — _start_synthesis signature: add `blends: Optional[dict] = None`
  W5 — _start_synthesis body: pass `blends=blends` to SynthesisWorker(...)
"""
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent / "kokoro_studio" / "gui.py"
data = GUI.read_bytes()
EOL_CRLF = b"\r\n" in data and data.count(b"\r\n") >= 3000
text = data.decode("utf-8")
if EOL_CRLF:
    text = text.replace("\r\n", "\n")


def write(t):
    if EOL_CRLF:
        t = t.replace("\n", "\r\n")
    GUI.write_bytes(t.encode("utf-8"))


def verify(label, needle, haystack):
    pos = haystack.find(needle)
    if pos < 0:
        print(f"ERROR: {label} anchor not found", file=sys.stderr)
        return False
    print(f"  {label} OK (pos={pos})")
    return True


# ================================================================
# W1 — SynthesisWorker.__init__ signature: add `blends=...`
# ================================================================
W1_OLD = '''        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        parent: Optional[QObject] = None,
'''
W1_NEW = '''        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
        # Phase 2 - Voice Blending. Snapshot of the GUI's
        # `_loaded_blends` dict at click time, so the worker
        # thread doesn't re-read disk between requests. Voice
        # blends are frozen dataclasses, so a shallow dict copy
        # is thread-safe.
        blends: Optional[dict] = None,
        parent: Optional[QObject] = None,
'''
if not verify("W1 SynthesisWorker __init__ signature", W1_OLD, text):
    sys.exit(1)
text = text.replace(W1_OLD, W1_NEW, 1)
print("W1 SynthesisWorker.__init__ accepts blends=")


# ================================================================
# W2 — SynthesisWorker.__init__ body: snapshot `self._blends`
# ================================================================
W2_OLD = '''        # Phase 2 — Multi-Speaker Dialogue Mode. When True the engine
        # parses `[voice_name]:` markers in `text` and synthesises each
        # segment with its own voice. `speaker_gap_s` is the silence
        # inserted between segments (default 0.25 s).
        self._multi_speaker = multi_speaker
        self._speaker_gap_s = speaker_gap_s
'''
W2_NEW = '''        # Phase 2 — Multi-Speaker Dialogue Mode. When True the engine
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
'''
if not verify("W2 SynthesisWorker __init__ body", W2_OLD, text):
    sys.exit(1)
text = text.replace(W2_OLD, W2_NEW, 1)
print("W2 SynthesisWorker.__init__ snapshots blends")


# ================================================================
# W3 — SynthesisWorker.run(): pass `blends=self._blends`
# ================================================================
W3_OLD = '''            audio = generate_speech(
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
'''
W3_NEW = '''            audio = generate_speech(
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
'''
if not verify("W3 SynthesisWorker.run generate_speech call", W3_OLD, text):
    sys.exit(1)
text = text.replace(W3_OLD, W3_NEW, 1)
print("W3 SynthesisWorker.run forwards blends=")


# ================================================================
# W4 — _start_synthesis signature: add `blends: Optional[dict] = None`
# ================================================================
# We anchor on a unique prefix of the existing signature. _start_synthesis
# has many params; we pick a distinctive mid-signature pattern.
W4_OLD = '''    def _start_synthesis(
        self,
        text: str,
        voice: str,
        speed: float,
        output_path: str,
        output_format: str,
        auto_play: bool,
        label: str,
        pronunciation_rules: Optional[dict] = None,
        multi_speaker: bool = False,
        speaker_gap_s: float = 0.25,
    ) -> None:
'''
W4_NEW = '''    def _start_synthesis(
        self,
        text: str,
        voice: str,
        speed: float,
        output_path: str,
        output_format: str,
        auto_play: bool,
        label: str,
        pronunciation_rules: Optional[dict],
        multi_speaker: bool,
        speaker_gap_s: float = 0.25,
        # Phase 2 - Voice Blending. Snapshotted blend registry
        # forwarded to the SynthesisWorker; if None, the engine
        # auto-loads from <Documents>/KokoroStudio/voice_blends.json.
        blends: Optional[dict] = None,
    ) -> None:
'''
if not verify("W4 _start_synthesis signature", W4_OLD, text):
    sys.exit(1)
text = text.replace(W4_OLD, W4_NEW, 1)
print("W4 _start_synthesis accepts blends=")


# ================================================================
# W5 — _start_synthesis body: pass `blends=blends` to SynthesisWorker
# ================================================================
# Anchor on the existing `pronunciation_rules=...` line in the
# SynthesisWorker(...) call inside _start_synthesis, and add `blends=blends`
# right after it. The anchor must be specific to _start_synthesis (not
# _on_generate_clicked) so we include a few lines of context.
W5_OLD = '''            self._worker = SynthesisWorker(
                text=text,
                voice=voice,
                speed=speed,
                output_path=output_path,
                output_format=output_format,
                pronunciation_rules=pronunciation_rules,
                multi_speaker=multi_speaker,
                speaker_gap_s=speaker_gap_s,
                parent=self,
            )
'''
W5_NEW = '''            self._worker = SynthesisWorker(
                text=text,
                voice=voice,
                speed=speed,
                output_path=output_path,
                output_format=output_format,
                pronunciation_rules=pronunciation_rules,
                multi_speaker=multi_speaker,
                speaker_gap_s=speaker_gap_s,
                # Phase 2 - Voice Blending. Forward the GUI's
                # blend snapshot to the worker so saved blend
                # names resolve to tensors at run time.
                blends=blends,
                parent=self,
            )
'''
if not verify("W5 _start_synthesis SynthesisWorker(...) call", W5_OLD, text):
    sys.exit(1)
text = text.replace(W5_OLD, W5_NEW, 1)
print("W5 _start_synthesis forwards blends to worker")


write(text)
print(f"\nAll worker plumbing applied. Wrote: {GUI}")
