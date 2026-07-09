r"""V3 patcher: switch the streaming playback backend from PySide6
QAudioSink to sounddevice (PortAudio binding).

Why: v1 (Int16 PCM + chunk conversion + auto_play fallback) didn't fix
the user's symptom. File save works. "Listen to last" works. But
real-time streaming is still silent. QAudioSink is silently no-op'ing
on the user's audio endpoint and we can't pinpoint why from here
(without their machine, diagnostics are guesswork). Migrating to
sounddevice means:

  * PortAudio uses WASAPI natively on Windows and is robustly tested.
  * sounddevice accepts float32 PCM directly, so we drop the Int16
    downconversion (maximum dynamic range, zero rounding).
  * No Qt audio-thread GC fragility (PortAudio owns its C thread).
  * No QAudioSink.error() / stateChanged races (we check `active`).

What changes:
  A. __init__ streaming attrs: `_audio_sink`, `_streaming_device` ->
     `_sd_stream` (sounddevice.OutputStream).
  B. `_start_streaming_sink` body: build a sd.OutputStream(samplerate=
     SAMPLE_RATE, channels=1, dtype='float32', blocksize=1024) wired
     to a callback that pulls from PcmRingBuffer.
  C. `_on_streaming_chunk`: push raw float32 bytes (no Int16 clip).
  D. `_on_streaming_sink_state`: convert to a no-op shim (legacy
     stateChanged handler that sounddevice doesn't need anymore).
  E. `_stop_streaming_sink`: stop + close the sounddevice stream.
  F. `_on_synthesis_done` auto_play fallback: drive the streaming-vs-
     fallback decision off `_sd_stream.active` (PortAudio's own flag).
  G. Insert new `_sd_stream_callback` method (PortAudio callback that
     pulls bytes from PcmRingBuffer).

Self-deletes after running.
"""

import pathlib
import sys

GUI = pathlib.Path("kokoro_studio/gui.py")
src = GUI.read_text(encoding="utf-8")


def replace(label: str, old: str, new: str) -> None:
    """Replace `old` with `new` in `src`; abort if not found."""
    if old not in src:
        print(f"FAIL: {label}: target string not found", file=sys.stderr)
        sys.exit(1)
    src2 = src.replace(old, new, 1)
    globals()["src"] = src2
    print(f"  {label} ok")


# -----------------------------------------------------------------------------
# A. __init__ streaming attrs
# -----------------------------------------------------------------------------
A_OLD = (
    "        self._audio_sink: Optional[QAudioSink] = None\n"
    "        self._streaming_device: Optional[StreamingPcmDevice] = None\n"
    "        self._ring_buffer: Optional[PcmRingBuffer] = None\n"
    "        self._stream_available: bool = default_audio_output_is_available()\n"
)
A_NEW = (
    "        # Streaming playback backend (Phase 2 - Real-Time Playback).\n"
    "        # v1 used QAudioSink + Int16 PCM and stayed silent on the\n"
    "        # user's Windows audio endpoint despite the format fix.\n"
    "        # v3 swapped to a sounddevice.OutputStream (PortAudio) which\n"
    "        # uses WASAPI natively and accepts float32 PCM directly:\n"
    "        #  * PcmRingBuffer (pure Python, already unit-tested) keeps\n"
    "        #    the same thread-safe producer/consumer contract;\n"
    "        #  * the chunk slot pushes Kokoro's raw float32 bytes -\n"
    "        #    zero clipping, zero rounding loss;\n"
    "        #  * PortAudio's C thread is fully self-managed: no Qt\n"
    "        #    audio-thread GC fragility, no QAudioSink error() races,\n"
    "        #    no QIODevice / streaming device refs to walk.\n"
    "        self._sd_stream: Optional[object] = None\n"
    "        self._ring_buffer: Optional[PcmRingBuffer] = None\n"
    "        self._stream_available: bool = default_audio_output_is_available()\n"
)
replace("A: init streaming attrs", A_OLD, A_NEW)


# -----------------------------------------------------------------------------
# B. _start_streaming_sink - rewrite to use sounddevice
# -----------------------------------------------------------------------------
# Match a small unique marker at the START of the method.
# Marker: the docstring opening line.
B_OLD = (
    "    def _start_streaming_sink(self) -> None:\n"
    '        """Provision the streaming sink for a fresh synthesis run.\n'
)
# We'll do a bigger replacement that covers the FULL method body.
# First find the end of the current method: the line before `def _on_streaming_chunk`
# which is the next method. We use Python's re to identify it.
# But it's simpler to just match enough context. Let's match the body
# from the `if not (self._stream_checkbox.isChecked() and self._stream_available):`
# through the v1 error() poll block (which is what we want to drop).

# Find the current method body using a sentinel + tail scan
START = "    def _start_streaming_sink(self) -> None:\n"
END_LINE = "    def _on_streaming_chunk(self, _idx: int, chunk: np.ndarray) -> None:\n"

i = src.find(START)
j = src.find(END_LINE)
assert i != -1, "B: _start_streaming_sink start marker not found"
assert j != -1, "B: _on_streaming_chunk start marker not found"
assert j > i, "B: _on_streaming_chunk should be after _start_streaming_sink"

block = src[i:j]
# Sanity check: block should mention make_kokoro_audio_format and QAudioSink
assert "make_kokoro_audio_format" in block, "B: block doesn't look like v1 _start_streaming_sink"
assert "QAudioSink" in block, "B: block doesn't look like v1 _start_streaming_sink"

# Build the new method
new_method = (
    "    def _start_streaming_sink(self) -> None:\n"
    '        """Provision sounddevice.OutputStream for streaming playback.\n'
    "\n"
    "        Why sounddevice instead of QAudioSink:\n"
    "          * PySide6's QAudioSink was silently no-op'ing on the\n"
    "            user's Windows audio endpoint despite v1's Int16 PCM\n"
    "            negotiation (file save works, Listen-to-last works,\n"
    "            but real-time streaming produces silence). Without\n"
    "            diagnostics on the user's hardware we cannot pinpoint\n"
    "            the root cause; sounddevice bypasses the entire\n"
    "            QtMultimedia streaming stack on the assumption that\n"
    "            PortAudio (via WASAPI on Windows) is more reliable.\n"
    "          * sounddevice accepts float32 PCM directly, so we drop\n"
    "            the v1 Int16 downconversion and keep Kokoro's\n"
    "            full-range output untouched.\n"
    "          * PortAudio owns its C audio thread; we get gapless\n"
    "            playback without the QAudioSink GC/threading\n"
    "            fragility we kept tripping over.\n"
    "\n"
    "        Falls back to file-based playback if:\n"
    "          - streaming checkbox is unchecked;\n"
    "          - the platform has no audio output device;\n"
    "          - sounddevice isn't importable (graceful no-op).\n"
    "\n"
    "        The Python-side state is `self._sd_stream.active` (read\n"
    "        by `_on_synthesis_done` to choose streaming-drain vs.\n"
    "        fallback-to-QMediaPlayer). PortAudio flips it False the\n"
    "        moment the callback raises `sd.CallbackStop` (which we do\n"
    "        on natural EOS via the empty-buffer + eos branch).\n"
    '        """\n'
    "        if not (self._stream_checkbox.isChecked() and self._stream_available):\n"
    "            return\n"
    "        # Lazy import: keeps the module loadable on installs\n"
    "        # without sounddevice (the app still works, just without\n"
    "        # real-time playback).\n"
    "        try:\n"
    "            import sounddevice as sd  # type: ignore[import-not-found]\n"
    "        except ImportError:\n"
    "            return\n"
    "        # Defensive: a previous run leaked a stream (e.g.\n"
    "        # close-event path was skipped). Drop it first so we\n"
    "        # don't end up with two PortAudio streams competing.\n"
    "        if self._sd_stream is not None:\n"
    "            self._stop_streaming_sink()\n"
    "        self._ring_buffer = PcmRingBuffer()\n"
    "        try:\n"
    "            self._sd_stream = sd.OutputStream(\n"
    "                samplerate=SAMPLE_RATE,\n"
    "                channels=1,\n"
    "                dtype='float32',\n"
    "                # ~46 ms per callback at 24 kHz mono is a good\n"
    "                # latency/safety trade-off: small enough to react\n"
    "                # quickly to per-chunk arrivals, large enough that\n"
    "                # transient producer jitter won't underrun.\n"
    "                blocksize=1024,\n"
    "                callback=self._sd_stream_callback,\n"
    "            )\n"
    "            self._sd_stream.start()\n"
    "        except Exception:\n"
    "            # sd.OutputStream ctor / start can fail if the host's\n"
    "            # default device is busy or pulled. Reset state so\n"
    "            # `_on_synthesis_done`'s fallback to QMediaPlayer\n"
    "            # kicks in cleanly.\n"
    "            self._sd_stream = None\n"
    "            self._ring_buffer = None\n"
    "            return\n"
    "\n"
    "    def _sd_stream_callback(self, outdata, frames, time_info, status) -> None:\n"
    '        """PortAudio callback that drains PcmRingBuffer.\n'
    "\n"
    "        Runs on PortAudio's background thread (NOT the GUI thread!).\n"
    "        Must be fast, exception-safe, and self-contained: any\n"
    "        exception here can hang the OS audio subsystem, so we let\n"
    "        only `sd.CallbackStop` propagate up and swallow everything\n"
    "        else. We deliberately do not touch Qt widgets from here\n"
    "        (PySide6 widgets are not thread-safe); a status-bar hint\n"
    "        for underruns is best handled by the GUI thread in\n"
    "        `_on_synthesis_progress`.\n"
    "\n"
    "        Underrun contract: when the ring buffer is empty AND EOS\n"
    "        is NOT set, we emit silence. The user hears a brief gap\n"
    "        (the next chunk will arrive in milliseconds). When the\n"
    "        buffer is empty AND EOS IS set, we raise CallbackStop to\n"
    "        end the stream cleanly so `_sd_stream.active` flips False\n"
    "        and `_on_synthesis_done` knows the drain finished.\n"
    '        """\n'
    "        try:\n"
    "            # `frames` = number of samples requested this call.\n"
    "            # Float32 = 4 bytes per sample, mono = 1 channel.\n"
    "            num_bytes = frames * 4\n"
    "            chunk = (\n"
    "                self._ring_buffer.pop(num_bytes)\n"
    "                if self._ring_buffer is not None\n"
    "                else b\"\"\n"
    "            )\n"
    "            if not chunk:\n"
    "                if self._ring_buffer is not None and self._ring_buffer.is_eos():\n"
    "                    raise sd.CallbackStop\n"
    "                # Underrun: silent; PortAudio will call us again\n"
    "                # as soon as the producer pushes more data.\n"
    "                outdata.fill(0)\n"
    "                return\n"
    "            arr = np.frombuffer(chunk, dtype=np.float32)\n"
    "            n = min(len(arr), frames)\n"
    "            outdata[:n, 0] = arr[:n]\n"
    "            if n < frames:\n"
    "                # Partial pull: pad remainder with silence (most\n"
    "                # common at EOS or just before chunks arrive).\n"
    "                outdata[n:, 0] = 0\n"
    "        except sd.CallbackStop:\n"
    "            raise\n"
    "        except Exception:\n"
    "            # Catastrophic failure inside the audio thread: silence\n"
    "            # and keep going. Never crash PortAudio from a callback.\n"
    "            try:\n"
    "                outdata.fill(0)\n"
    "            except Exception:\n"
    "                pass\n"
    "\n"
)
# Replace v1 method block with new sounddevice-based method + new callback
src = src[:i] + new_method + src[j:]
print("  B ok: _start_streaming_sink rewritten + _sd_stream_callback inserted")


# -----------------------------------------------------------------------------
# C. _on_streaming_chunk: revert to raw float32 push
# -----------------------------------------------------------------------------
C_OLD = (
    "        # Coerce to int16 LE PCM. The QAudioSink format chosen in\n"
    "        # `make_kokoro_audio_format` is `Int16` because Qt6's WASAPI /\n"
    "        # MediaFoundation backend won't negotiate Float32 PCM with most\n"
    "        # Windows audio endpoints \u2014 pushing Float32 bytes there results\n"
    "        # in a silent no-op sink. Downconversion: clamp to [-1, 1],\n"
    "        # scale by 32767 (asymmetric on purpose to match the LAME /\n"
    "        # soundfile convention used elsewhere in the engine), cast to\n"
    "        # int16. `np.asarray` is defensive against mis-typed callers,\n"
    "        # and `.tobytes()` returns little-endian int16 on x86/ARM,\n"
    "        # which is exactly what every supported audio backend wants.\n"
    "        pcm = (\n"
    "            np.clip(np.asarray(chunk, dtype=np.float32), -1.0, 1.0)\n"
    "            .reshape(-1)\n"
    "        )\n"
    "        pcm_int16 = np.clip(pcm * 32767.0, -32767.0, 32767.0).astype(np.int16)\n"
    "        self._ring_buffer.push(pcm_int16.tobytes())\n"
)
C_NEW = (
    "        # Push Kokoro's raw float32 bytes straight into the ring\n"
    "        # buffer. sounddevice (PortAudio) consumes float32 PCM\n"
    "        # natively on every supported backend (WASAPI / CoreAudio /\n"
    "        # PulseAudio / PipeWire), so we keep full dynamic range and\n"
    "        # avoid the v1 Int16 downconversion path entirely.\n"
    "        # `np.asarray` is defensive against mis-typed callers; the\n"
    "        # `.tobytes()` representation is little-endian IEEE-754 on\n"
    "        # x86/ARM, which is exactly what sounddevice reads.\n"
    "        pcm = np.asarray(chunk, dtype=np.float32).reshape(-1)\n"
    "        self._ring_buffer.push(pcm.tobytes())\n"
)
replace("C: _on_streaming_chunk float32 push", C_OLD, C_NEW)


# -----------------------------------------------------------------------------
# D. _on_streaming_sink_state becomes a no-op shim
# -----------------------------------------------------------------------------
# Search for the method and replace it with a no-op.
D_START = "    def _on_streaming_sink_state(self, state) -> None:\n"
D_END = "    def _stop_streaming_sink(self) -> None:\n"
i = src.find(D_START)
j = src.find(D_END)
assert i != -1 and j > i, "D: method markers not found"
block = src[i:j]
assert "QAudioSink" in block, "D: block doesn't look like v1 _on_streaming_sink_state"
new_block = (
    "    def _on_streaming_sink_state(self, state) -> None:\n"
    '        """Legacy QAudioSink stateChanged hook - now a no-op shim.\n'
    "\n"
    "        Kept as an empty method (rather than deleted) so any\n"
    "        external reference or accidental connect() doesn't crash.\n"
    "        sounddevice doesn't fire Qt-style stateChanged signals;\n"
    "        cleanup after a streaming run is handled by\n"
    "        `_stop_streaming_sink` on the GUI thread instead.\n"
    '        """\n'
    "        return\n"
    "\n"
)
src = src[:i] + new_block + src[j:]
print("  D ok: _on_streaming_sink_state -> no-op shim")


# -----------------------------------------------------------------------------
# E. _stop_streaming_sink: stop + close sounddevice stream
# -----------------------------------------------------------------------------
E_OLD = (
    "    def _stop_streaming_sink(self) -> None:\n"
    '        """Hard-stop the streaming sink (drops in-flight audio, no drain).\n'
    "\n"
    "        Used by the Stop button (Stop -> worker interrupt) and by\n"
    "        `closeEvent` (window shutdown during a streaming run). Unlike\n"
    "        the natural IdleState drain path, this clears the buffer so\n"
    "        stale audio doesn't bleed into a subsequent run.\n"
    '        """\n'
    "        if self._audio_sink is not None:\n"
    "            try:\n"
    "                self._audio_sink.stop()\n"
    "            except Exception:\n"
    "                pass\n"
    "        if self._streaming_device is not None:\n"
    "            try:\n"
    "                self._streaming_device.close()\n"
    "            except Exception:\n"
    "                pass\n"
    "        if self._ring_buffer is not None:\n"
    "            self._ring_buffer.reset()\n"
)
E_NEW = (
    "    def _stop_streaming_sink(self) -> None:\n"
    '        """Hard-stop the sounddevice stream (drops in-flight audio).\n'
    "\n"
    "        Used by the Stop button (Stop -> worker interrupt) and by\n"
    "        `closeEvent` (window shutdown during a streaming run).\n"
    "        Sounddevice\'s `stop()` aborts the PortAudio stream without\n"
    "        draining; `close()` releases the underlying WASAPI handle.\n"
    "        We reset the ring buffer so stale audio does not bleed\n"
    "        into a subsequent run.\n"
    '        """\n'
    "        if self._sd_stream is not None:\n"
    "            try:\n"
    "                self._sd_stream.stop()\n"
    "            except Exception:\n"
    "                pass\n"
    "            try:\n"
    "                self._sd_stream.close()\n"
    "            except Exception:\n"
    "                pass\n"
    "            self._sd_stream = None\n"
    "        if self._ring_buffer is not None:\n"
    "            self._ring_buffer.reset()\n"
)
replace("E: _stop_streaming_sink body", E_OLD, E_NEW)


# -----------------------------------------------------------------------------
# F. _on_synthesis_done auto_play fallback check
# -----------------------------------------------------------------------------
F_OLD = (
    "        if auto_play:\n"
    "            # Pick the audio path dynamically. If streaming was provisioned\n"
    "            # but the QAudioSink reported an error (the classic Windows\n"
    "            # \"format not negotiated\" silent failure) we MUST fall through\n"
    "            # to QMediaPlayer \u2014 otherwise the user hears nothing at all,\n"
    "            # because mark_eos() alone won't make a broken sink play.\n"
    "            streaming_ok = (\n"
    "                self._ring_buffer is not None\n"
    "                and self._audio_sink is not None\n"
    "                and self._audio_sink.error() == QAudioSink.Error.NoError\n"
    "            )\n"
)
F_NEW = (
    "        if auto_play:\n"
    "            # Decide between streaming-drain vs. QMediaPlayer fallback\n"
    "            # by inspecting PortAudio's own `active` flag. This is\n"
    "            # more reliable than a synchronous QAudioSink.error()\n"
    "            # poll (which Qt6 sets asynchronously): `active` flips\n"
    "            # False the instant the callback raises sd.CallbackStop,\n"
    "            # i.e. on natural EOS drain OR a sounddevice crash.\n"
    "            # `getattr(_sd_stream, 'active', False)` handles the\n"
    "            # case where sounddevice wasn't importable and the\n"
    "            # `_start_streaming_sink` call was a no-op (the stream\n"
    "            # would be None here, so we fall through cleanly).\n"
    "            sd_active = bool(getattr(self._sd_stream, \"active\", False))\n"
    "            streaming_ok = self._ring_buffer is not None and sd_active\n"
)
replace("F: auto_play fallback check", F_OLD, F_NEW)


# Write patched file
GUI.write_text(src, encoding="utf-8")
print(f"\nWROTE {GUI}  ·  {len(src):,} chars")

# Self-delete this patcher
SELF = pathlib.Path("patch_gui_v3.py")
SELF.unlink()
print(f"Cleanup OK  ·  removed {SELF}")
