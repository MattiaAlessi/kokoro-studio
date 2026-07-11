#!/usr/bin/env python3
"""Atomic-batch discoverability patcher for kokoro_studio/gui.py.

Strategy (read all -> assert anchors -> apply all replaces -> write once):
  1. Read whole file. If CRLF, normalise to LF for matching.
  2. Verify each of the 8 anchors matches EXACTLY once.  Abort if not.
  3. Apply all 8 .replace() calls in memory.
  4. If CRLF, re-stamp CRLF; write bytes back once.

This pattern is all-or-nothing: a crash mid-way leaves the file unchanged.
"""
import sys
from pathlib import Path

GUI = Path("kokoro_studio/gui.py")
raw = GUI.read_bytes()
crlf = raw.count(b"\r\n") > (raw.count(b"\n") / 2)
text = raw.decode("utf-8")
if crlf:
    text_n = text.replace("\r\n", "\n")
else:
    text_n = text

# Defensive: strip any stray CR characters (in case the file has a mix of
# CRLF and LF for any reason).  Doing this on both the text and the patcher
# strings ensures the byte-level .count() comparison works.
import re
text_n = re.sub(r'\r\n?', '\n', text_n)
print(f"Loaded {GUI}: {len(raw):,} bytes, EOL={'CRLF' if crlf else 'LF'}")

LIGHTBULB = "\U0001F4A1"   # 💡

# ---------------------------------------------------------------------------
# Patch 1 -- module-level TTS samples after SSML_HELP_SAMPLE
# ---------------------------------------------------------------------------
P1_OLD = (
    "  * Plain text without markers works as usual; toggling\n"
    "    the checkbox on by accident has zero side-effects.\n"
    "\"\"\"\n"
)
P1_NEW = P1_OLD + (
    "\n"
    "# Short TTS samples (kept distinct from the long prose help-text docs\n"
    "# so the Insert-sample button in the help dialogs drops a runnable\n"
    "# script into the editor instead of documentation).\n"
    "DIALOGUE_HELP_TTS_SAMPLE = (\n"
    "    \"[af_sky]: Hi traveller!\\n\"\n"
    "    \"[af_nicole]: Greetings, friend.\\n\"\n"
    "    \"[af_bella]: Let our tale begin.\\n\"\n"
    "    \"And this line uses the default voice again.\"\n"
    ")\n"
    "\n"
    "SSML_HELP_TTS_SAMPLE = (\n"
    "    'Hello <break time=\"0.4s\"/> I can pause, '\n"
    "    '<emphasis>emphasise</emphasis>, and '\n"
    "    '<prosody rate=\"fast\">speak at speed</prosody>.'\n"
    ")\n"
)

# ---------------------------------------------------------------------------
# Patch 2 -- About-tab mentions SSML-lite controls
# ---------------------------------------------------------------------------
P2_OLD = (
    "            \"<b>multi-speaker dialogue mode</b>, and a growing set of audiobook / batch features.<br><br>\"\n"
)
P2_NEW = (
    "            \"<b>multi-speaker dialogue mode</b>, <b>SSML-lite controls</b>, and a growing set of audiobook / batch features.<br><br>\"\n"
)

# ---------------------------------------------------------------------------
# Patch 3 -- banner placeholder in __init__
# ---------------------------------------------------------------------------
P3_OLD = "        self._ssml_checkbox = None  # type: ignore[assignment]\n"
P3_NEW = (
    "        self._ssml_checkbox = None  # type: ignore[assignment]\n"
    "        # Discoverability banner: persistent QLabel above the editor.\n"
    "        # Hidden once the user has typed more than ~30 characters.\n"
    "        self._discoverability_banner = None  # type: ignore[assignment]\n"
)

# ---------------------------------------------------------------------------
# Patch 4 -- banner QLabel widget in _build_editor_panel
# ---------------------------------------------------------------------------
P4_OLD = (
    "        self._counter_label.setObjectName(\"Counter\")\n"
    "        header_row.addWidget(self._counter_label)\n"
    "        layout.addLayout(header_row)\n"
)
BANNER_HTML = (
    "<html>" + LIGHTBULB + " Try <b>SSML-lite controls</b> "
    "(<code>&lt;break&gt;</code>, <code>&lt;emphasis&gt;</code>, "
    "<code>&lt;prosody&gt;</code>) &mdash; tick <i>Apply SSML</i> on the right.<br>"
    "&nbsp;&nbsp;&nbsp;&nbsp;Or start a line with "
    "<code>[voice_name]:</code> for <b>Multi-Speaker Dialogue</b>.</html>"
)
P4_NEW = P4_OLD + (
    "\n"
    "        # Discoverability banner (Phase 2 power features).\n"
    "        self._discoverability_banner = QLabel(\n"
    "            " + repr(BANNER_HTML) + "\n"
    "        )\n"
    "        self._discoverability_banner.setObjectName(\"DiscoverabilityBanner\")\n"
    "        self._discoverability_banner.setStyleSheet(\n"
    "            \"QLabel#DiscoverabilityBanner {\"\n"
    "            \"color: #4338ca;\"\n"
    "            \"background-color: rgba(99,102,241,0.08);\"\n"
    "            \"border: 1px solid rgba(99,102,241,0.25);\"\n"
    "            \"border-radius: 6px;\"\n"
    "            \"padding: 6px 10px;\"\n"
    "            \"font-size: 11px;\"\n"
    "            \"}\"\n"
    "        )\n"
    "        self._discoverability_banner.setTextInteractionFlags(\n"
    "            Qt.TextInteractionFlag.TextSelectableByMouse\n"
    "        )\n"
    "        layout.addWidget(self._discoverability_banner)\n"
)

# ---------------------------------------------------------------------------
# Patch 5 -- tiny "?" ghost button in row2 after SSML checkbox
# ---------------------------------------------------------------------------
P5_OLD = (
    "        row2.addSpacing(12)\n"
    "        row2.addWidget(self._ssml_checkbox)\n"
    "\n"
    "        # Streaming playback toggle"
)
P5_NEW = (
    "        row2.addSpacing(12)\n"
    "        row2.addWidget(self._ssml_checkbox)\n"
    "        # Tiny '?' ghost button sat next to Apply SSML so users can\n"
    "        # open the SSML-lite help dialog without hunting through menus.\n"
    "        self._ssml_action_help_btn = QPushButton(\"?\")\n"
    "        self._ssml_action_help_btn.setProperty(\"role\", \"ghost\")\n"
    "        self._ssml_action_help_btn.setFixedSize(28, 26)\n"
    "        self._ssml_action_help_btn.setToolTip(\"Open SSML-lite help\")\n"
    "        self._ssml_action_help_btn.clicked.connect(self._on_ssml_help_clicked)\n"
    "        row2.addWidget(self._ssml_action_help_btn)\n"
    "\n"
    "        # Streaming playback toggle"
)

# ---------------------------------------------------------------------------
# Patch 6 -- banner auto-hide connector in _wire_signals
# File uses 8-space class-method indent + doubled indent (16space) inside
# the .connect( lambda: ... ) argument block. Anchor stays byte-exact.
# ---------------------------------------------------------------------------
P6_OLD = (
    "        self._editor.textChanged.connect(  # SSML-GUI-E10\n"
    "            lambda: self._refresh_ssml_chip(\n"
    "                self._editor.toPlainText()\n"
    "            )\n"
    "        )\n"
)
P6_NEW = (
    "        self._editor.textChanged.connect(  # SSML-GUI-E10\n"
    "            lambda: self._refresh_ssml_chip(\n"
    "                self._editor.toPlainText()\n"
    "            )\n"
    "        )\n"
    "        # Discoverability banner auto-hide: once the user has typed\n"
    "        # more than ~30 characters we assume they got the hint. The\n"
    "        # isVisible() guard short-circuits so post-hide keystrokes\n"
    "        # are cheap no-ops (no toPlainText() string copy).\n"
    "        if self._discoverability_banner is not None:\n"
    "            _banner = self._discoverability_banner\n"
    "            _ed = self._editor\n"
    "            self._editor.textChanged.connect(\n"
    "                lambda _b=_banner, _e=_ed: (\n"
    "                    _b.setVisible(False)\n"
    "                    if (\n"
    "                        _b.isVisible()\n"
    "                        and len(_e.toPlainText()) > 30\n"
    "                    )\n"
    "                    else None\n"
    "                )\n"
    "            )\n"
)

# ---------------------------------------------------------------------------
# Patch 7 -- dialogue help dialog: Insert-sample button.
# KEEP sample.setPlainText(DIALOGUE_HELP_SAMPLE) so the prose help-doc
# remains in the preview (educational). Only change is the new button.
# ---------------------------------------------------------------------------
P7_OLD = (
    "        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
    "        sample.setMinimumHeight(180)\n"
    "        root.addWidget(sample, 1)\n"
    "\n"
    "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn.setText(\"Got it\")\n"
    "        close_btn.setProperty(\"role\", \"primary\")\n"
    "        bbox.accepted.connect(dlg.accept)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
)
P7_NEW = (
    "        sample.setPlainText(DIALOGUE_HELP_SAMPLE)\n"
    "        sample.setMinimumHeight(180)\n"
    "        root.addWidget(sample, 1)\n"
    "\n"
    "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn.setText(\"Got it\")\n"
    "        close_btn.setProperty(\"role\", \"primary\")\n"
    "        bbox.accepted.connect(dlg.accept)\n"
    "        # Insert button: drops the runnable DIALOGUE_HELP_TTS_SAMPLE\n"
    "        # into the editor without the user copy-pasting by hand.\n"
    "        insert_btn = bbox.addButton(\n"
    "            \"Insert sample script\",\n"
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        # ActionRole buttons don't auto-close the modal dialog, so\n"
    "        # wire clicked -> dlg.accept().  This keeps the post-exec\n"
    "        # `clickedButton() is insert_btn` check working correctly.\n"
    "        insert_btn.clicked.connect(dlg.accept)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
    "        if bbox.clickedButton() is insert_btn:\n"
    "            self._editor.setPlainText(DIALOGUE_HELP_TTS_SAMPLE)\n"
)

# ---------------------------------------------------------------------------
# Patch 8 -- SSML help dialog: Insert + enable-SSML button.
# Symmetric to P7. KEEPS the prose help-doc preview unchanged.
# ---------------------------------------------------------------------------
P8_OLD = (
    "        sample.setPlainText(SSML_HELP_SAMPLE)\n"
    "        sample.setMinimumHeight(180)\n"
    "        root.addWidget(sample, 1)\n"
    "\n"
    "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn.setText(\"Got it\")\n"
    "        close_btn.setProperty(\"role\", \"primary\")\n"
    "        bbox.accepted.connect(dlg.accept)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
)
P8_NEW = (
    "        sample.setPlainText(SSML_HELP_SAMPLE)\n"
    "        sample.setMinimumHeight(180)\n"
    "        root.addWidget(sample, 1)\n"
    "\n"
    "        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)\n"
    "        close_btn.setText(\"Got it\")\n"
    "        close_btn.setProperty(\"role\", \"primary\")\n"
    "        bbox.accepted.connect(dlg.accept)\n"
    "        # Insert button: drops a runnable SSML-lite sample AND ticks\n"
    "        # the 'Apply SSML' checkbox so the tags take effect.\n"
    "        insert_btn = bbox.addButton(\n"
    "            \"Insert sample + enable SSML\",\n"
    "            QDialogButtonBox.ButtonRole.ActionRole,\n"
    "        )\n"
    "        insert_btn.clicked.connect(dlg.accept)\n"
    "        root.addWidget(bbox)\n"
    "\n"
    "        dlg.exec()\n"
    "        if bbox.clickedButton() is insert_btn:\n"
    "            self._editor.setPlainText(SSML_HELP_TTS_SAMPLE)\n"
    "            self._ssml_checkbox.setChecked(True)\n"
)

PATCHES = [
    ("E1 SSML_HELP_TTS_SAMPLE module-level", P1_OLD, P1_NEW),
    ("E2 About-tab SSML mention",            P2_OLD, P2_NEW),
    ("E3 __init__ banner placeholder",       P3_OLD, P3_NEW),
    ("E4 banner QLabel widget",              P4_OLD, P4_NEW),
    ("E5 '?' ghost button in row2",          P5_OLD, P5_NEW),
    ("E6 banner auto-hide connector",        P6_OLD, P6_NEW),
    ("E7 dialogue Insert button",            P7_OLD, P7_NEW),
    ("E8 SSML Insert button",                P8_OLD, P8_NEW),
]

# ---------------------------------------------------------------------------
# Verify each anchor matches exactly once.
# ---------------------------------------------------------------------------
print("\n[verify] asserting every anchor matches exactly once.")
for name, old, _new in PATCHES:
    n = text_n.count(old)
    if n != 1:
        if n == 0:
            print(f"  [FAIL] {name}: anchor NOT FOUND")
            print(f"          anchor head (60 chars): {old[:60]!r}")
        else:
            print(f"  [FAIL] {name}: matches {n} times (expected 1)")
        sys.exit(1)
    print(f"  [OK]   {name}")

# ---------------------------------------------------------------------------
# Apply all 8 replacements in memory.
# ---------------------------------------------------------------------------
print("\n[patch] applying 8 replacements in memory.")
for name, old, new in PATCHES:
    text_n = text_n.replace(old, new, 1)
    print(f"  [OK]   {name}")

# ---------------------------------------------------------------------------
# Re-stamp CRLF if needed, then write once.
# ---------------------------------------------------------------------------
if crlf:
    out_text = text_n.replace("\n", "\r\n")
else:
    out_text = text_n

GUI.write_bytes(out_text.encode("utf-8"))
print(f"\n[save] {GUI}: {len(out_text.encode('utf-8')):,} bytes written.")
print("Done.")
