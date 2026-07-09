# 🎙  Kokoro Studio

> **Local, free, fast, private neural text-to-speech** · powered by [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
>
> FREE · OFFLINE · PRIVATE · FAST · NO CREDITS

A PySide6 desktop GUI for the [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
text-to-speech model. Kokoro Studio gives you a clean, dark-themed
workbench for generating natural-sounding speech in 9 languages, with
29 built-in voice presets, multi-format export, and a growing set of
audiobook / batch features.

See `PLAN.md` for the full roadmap.

---

## ✨ Features (Phase 1)

| Status | Feature |
| --- | --- |
| ✅ | **29 built-in voices** in American & British English, with grade / gender / language metadata |
| ✅ | **Multi-format export** — WAV, FLAC, OGG (via `soundfile`), MP3 (via `lameenc`, no FFmpeg required) |
| ✅ | **Document import** — open `.txt` / `.pdf` / `.epub` files; drag-and-drop onto the editor |
| ✅ | **Pronunciation dictionary** — case-sensitive, whole-word, longest-rule-first substitutions persisted to JSON |
| ✅ | **Speed control** — 0.1× to 3.0× via coupled slider + spinbox |
| ✅ | **Background synthesis** — UI stays responsive while Kokoro generates |
| ✅ | **Real-time streaming playback** *(Phase 2)* — hear audio as it generates, ~200 ms after clicking Generate |
| ✅ | **In-app playback** — generated audio plays immediately via `QMediaPlayer` |
| ✅ | **Stop / cancel** — clean cancellation of in-flight generations |

Roadmap items (Phase 2+) live in `PLAN.md`.

---

## 📦 Install

### 1. Clone the repository

```bash
git clone <repo-url> kokoro-studio
cd kokoro-studio
```

### 2. Install Python dependencies

A Python 3.10+ environment is recommended. From the project root:

```bash
pip install -r requirements.txt
```

This pulls in:

- `PySide6` — the GUI framework
- `kokoro` — the TTS engine + voice packs
- `soundfile` — FLAC / OGG / WAV I/O
- `numpy` — audio array handling
- `lameenc` — pure-Python MP3 encoding (no FFmpeg needed)
- `pypdf`, `ebooklib`, `beautifulsoup4`, `lxml` — document parsers

> **First-run note**: `kokoro` downloads the 300 MB voice + acoustic
> model on first use. Subsequent launches start instantly.

### 3. Launch

```bash
python -m kokoro_studio
```

Or, from the project root:

```bash
python -m kokoro_studio.gui
```

---

## 🖱️ Quick start

1. **Pick a voice** from the left panel (29 English presets, sorted by grade).
2. **Type or paste** text into the editor — or **drop a `.txt` / `.pdf` / `.epub` file** onto it.
3. **Choose an output format** (WAV / MP3 / FLAC / OGG) and an output path.
4. **Click Generate**. The progress bar turns indeterminate; the status bar
   shows live chunk counts. Audio plays automatically when the file is written.
5. **Edit your pronunciation dictionary** via the *Dict…* button in the
   action row, and toggle *Apply rules* on or off.

> **Tip**: the *Preview selected voice* button under the voice list
> generates a short fixed-phrase sample in the current voice and
> auto-plays it — useful for browsing the catalog.

---

## 🗂️ Project structure

```
kokoro_studio/
├── __init__.py              # package metadata
├── __main__.py              # `python -m kokoro_studio` entry point
├── engine.py                # Kokoro-82M wrapper + multi-format audio writer
├── document_loader.py       # TXT / PDF / EPUB parsers
├── pronunciation.py         # pronunciation dictionary (load / save / apply)
└── gui.py                   # PySide6 main window

tests/
├── test_engine.py           # smoke tests for save_audio + engine signature
├── test_document_loader.py  # TXT round-trip + EPUB spine + error paths
└── test_pronunciation.py    # substitution semantics + JSON schema

docs/                       # additional documentation
examples/                    # sample text inputs
OLD/                        # legacy experiments (gitignored)
```

---

## 🧪 Development

### Run the test suite

```bash
python -m pytest tests/ -v
```

Or just the smoke checks (no pytest needed):

```bash
python -m tests.smoke
```

### Editable install

```bash
pip install -e .
```

This registers the `kokoro-studio` console script so you can launch
the app with `kokoro-studio` from anywhere.

---

## 📋 Roadmap

See [`PLAN.md`](./PLAN.md) for the full feature roadmap. Phase 1
("Quick Wins") is shipped; Phase 2 ("The ElevenLabs Feel" — real-time
streaming, multi-speaker dialogue, voice blending, SSML-lite) is
next up.

---

## 📜 License

This project is released under the **Kokoro Studio Source-Available
License** (see `LICENSE`). The license:

- Permits personal, educational, **and commercial** use
- Permits modifications and redistribution
- Requires the original copyright notice and donation info to be
  preserved in any redistribution
- Reserves the right to sell the original Software to the Licensor

If you redistribute the project, keep the `LICENSE` and `DONATIONS.md`
files intact. See `LICENSE` for the full text.

---

## ☕ Donations

Donations are appreciated and help sustain the project. See
[`DONATIONS.md`](./DONATIONS.md) for the current list of channels.

---

## 🙏 Acknowledgements

- The [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model by
  hexgrad and the Kokoro contributors.
- The [PySide6](https://wiki.qt.io/Qt_for_Python) team for Qt for Python.
- All the open-source libraries this project depends on — see
  `requirements.txt` for the full list.
