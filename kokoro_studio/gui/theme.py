# -*- coding: utf-8 -*-
"""Shared theme, QSS, and helper constants for the Kokoro Studio GUI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kokoro_studio.engine import DEFAULT_VOICE, OUTPUT_FORMATS

# When running headless (no PySide6), the module should still import cleanly.
try:
    from PySide6.QtCore import QStandardPaths
    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False


# ===========================================================================
# Theme constants
# ===========================================================================

THEME_DARK = "dark"
THEME_LIGHT = "light"

_THEME_NAMES = {THEME_DARK: "Dark", THEME_LIGHT: "Light"}

def theme_display_name(mode: str) -> str:
    return _THEME_NAMES.get(mode, "Dark")


# ===========================================================================
# Dark theme QSS
# ===========================================================================

QSS_DARK = """
* {
    font-family: 'Segoe UI', 'Inter', -apple-system, system-ui, sans-serif;
}

/* ── Base ─────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: #0E1015;
    color: #E4E7EB;
}

/* ── Panels / Cards ───────────────────────────────── */
QFrame#Panel {
    background-color: #181B22;
    border: 1px solid #242833;
    border-radius: 10px;
}

QFrame#PanelCompact {
    background-color: #181B22;
    border: 1px solid #242833;
    border-radius: 8px;
}

QFrame#Header {
    background-color: transparent;
    border: none;
}

QFrame#ToolbarGroup {
    background-color: transparent;
    border: none;
}

/* ── Typography ───────────────────────────────────── */
QLabel#H1 {
    color: #F0F2F5;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.4px;
}
QLabel#Subtitle {
    color: #7C8196;
    font-size: 11px;
    font-weight: 400;
}
QLabel#SectionTitle {
    color: #636882;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.8px;
    text-transform: uppercase;
}
QLabel#Counter {
    color: #636882;
    font-size: 11px;
    font-weight: 500;
}
QLabel#VoiceReadout {
    color: #E4E7EB;
    font-size: 13px;
    font-weight: 600;
}

/* ── Badges ───────────────────────────────────────── */
QLabel#Badge {
    color: #FFFFFF;
    font-weight: 700;
    font-size: 9px;
    letter-spacing: 1.5px;
    padding: 3px 10px;
    border-radius: 5px;
}

/* ── Feature indicator dot ────────────────────────── */
QLabel#FeatureDot {
    color: #7B61FF;
    font-size: 18px;
    font-weight: bold;
}

/* ── Editor ───────────────────────────────────────── */
QPlainTextEdit {
    background-color: #20242D;
    color: #E4E7EB;
    border: 1px solid #2C303E;
    border-radius: 8px;
    padding: 16px;
    selection-background-color: #7B61FF;
    selection-color: #FFFFFF;
    font-family: 'Consolas', 'Cascadia Code', 'JetBrains Mono', 'Menlo', monospace;
    font-size: 12px;
    line-height: 1.5;
}
QPlainTextEdit:focus {
    border: 1px solid #7B61FF;
}

/* ── Voice List ───────────────────────────────────── */
QListWidget {
    background-color: #1C2029;
    color: #E4E7EB;
    border: 1px solid #2C303E;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    border-radius: 6px;
    padding: 8px 10px;
    margin: 2px 0px;
}
QListWidget::item:hover {
    background-color: #232732;
}
QListWidget::item:selected {
    background-color: #7B61FF;
    color: #FFFFFF;
}
QListWidget::item QLabel {
    background-color: transparent;
    color: #E4E7EB;
}
QListWidget::item:selected QLabel {
    color: #FFFFFF;
}

/* ── Search Bar ───────────────────────────────────── */
QLineEdit#VoiceSearch {
    background-color: #1C2029;
    color: #9DA0B0;
    border: 1px solid #2C303E;
    border-radius: 8px;
    padding: 8px 12px 8px 34px;
    font-size: 12px;
    selection-background-color: #7B61FF;
    selection-color: #FFFFFF;
}
QLineEdit#VoiceSearch:focus {
    border: 1px solid #7B61FF;
    color: #E4E7EB;
}

/* ── Action Button Bar ────────────────────────────── */
QFrame#ActionBar {
    background-color: #181B22;
    border: 1px solid #242833;
    border-radius: 10px;
}

/* ── Buttons ──────────────────────────────────────── */
QPushButton {
    background-color: #20242D;
    color: #E4E7EB;
    border: 1px solid #2C303E;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #2A2E3B;
    border-color: #3A3F52;
}
QPushButton:pressed {
    background-color: #181B22;
}
QPushButton:disabled {
    color: #545975;
    border-color: #242833;
    background-color: #181B22;
}

/* Primary action */
QPushButton[role="primary"] {
    background-color: #7B61FF;
    color: #FFFFFF;
    border: 1px solid #7B61FF;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 24px;
    letter-spacing: 0.3px;
}
QPushButton[role="primary"]:hover {
    background-color: #8B75FF;
    border-color: #8B75FF;
}
QPushButton[role="primary"]:pressed {
    background-color: #6B51E5;
}
QPushButton[role="primary"]:disabled {
    background-color: #3A3068;
    border-color: #3A3068;
    color: #8B85B0;
}

/* Danger */
QPushButton[role="danger"] {
    background-color: #E5484D;
    color: #FFFFFF;
    border: 1px solid #E5484D;
}
QPushButton[role="danger"]:hover {
    background-color: #F25F63;
    border-color: #F25F63;
}
QPushButton[role="danger"]:disabled {
    background-color: #5C282A;
    border-color: #5C282A;
    color: #A08080;
}

/* Ghost / flat */
QPushButton[role="ghost"] {
    background-color: transparent;
    border: 1px solid transparent;
}
QPushButton[role="ghost"]:hover {
    background-color: #232732;
    border-color: #2C303E;
}
QPushButton[role="ghost"]:disabled {
    background-color: transparent;
    border-color: transparent;
    color: #545975;
}

/* Feature icon button (compact) */
QPushButton[role="feature"] {
    background-color: #1C2029;
    color: #9DA0B0;
    border: 1px solid #2C303E;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton[role="feature"]:hover {
    background-color: #232732;
    color: #E4E7EB;
    border-color: #3A3F52;
}
QPushButton[role="feature"]:pressed {
    background-color: #181B22;
}
QPushButton[role="feature"]:disabled {
    color: #545975;
    border-color: #242833;
}

/* ── Inputs ───────────────────────────────────────── */
QDoubleSpinBox, QComboBox, QLineEdit, QSpinBox {
    background-color: #20242D;
    color: #E4E7EB;
    border: 1px solid #2C303E;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #7B61FF;
    font-size: 12px;
}
QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #7B61FF;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #20242D;
    color: #E4E7EB;
    border: 1px solid #2C303E;
    selection-background-color: #7B61FF;
    padding: 4px;
    outline: none;
}

/* ── Checkboxes ───────────────────────────────────── */
QCheckBox {
    color: #9DA0B0;
    font-size: 12px;
    font-weight: 500;
    spacing: 6px;
}
QCheckBox:hover {
    color: #E4E7EB;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3A3F52;
    border-radius: 4px;
    background-color: #20242D;
}
QCheckBox::indicator:checked {
    background-color: #7B61FF;
    border-color: #7B61FF;
}
QCheckBox::indicator:hover {
    border-color: #7B61FF;
}

/* ── Sliders ──────────────────────────────────────── */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background-color: #2C303E;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #7B61FF;
    border: none;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #8B75FF;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::sub-page:horizontal {
    background-color: #7B61FF;
    border-radius: 2px;
}

/* ── Progress Bar ─────────────────────────────────── */
QProgressBar {
    background-color: #20242D;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 8px;
}
QProgressBar::chunk {
    background-color: #7B61FF;
    border-radius: 4px;
}

/* ── Status Bar ───────────────────────────────────── */
QStatusBar {
    background-color: #0E1015;
    color: #7C8196;
    border-top: 1px solid #1C1F28;
    font-size: 12px;
    padding: 2px 12px;
}
QStatusBar QLabel {
    color: #9DA0B0;
    padding: 0 8px;
    font-size: 12px;
}
QStatusBar QProgressBar {
    max-height: 6px;
    min-height: 6px;
    min-width: 120px;
    max-width: 120px;
}

/* ── Splitter ─────────────────────────────────────── */
QSplitter::handle {
    background-color: transparent;
}

/* ── Tooltips ─────────────────────────────────────── */
QToolTip {
    background-color: #1C2029;
    color: #E4E7EB;
    border: 1px solid #2C303E;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12px;
}

/* ── Scrollbars ───────────────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3A3F52;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #545975;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
}
QScrollBar:horizontal {
    background: transparent;
    height: 6px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #3A3F52;
    border-radius: 3px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #545975;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: none;
}
"""


# ===========================================================================
# Light theme QSS
# ===========================================================================

QSS_LIGHT = """
* {
    font-family: 'Segoe UI', 'Inter', -apple-system, system-ui, sans-serif;
}

/* ── Base ─────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: #F0F1F5;
    color: #1D1D23;
}

/* ── Panels / Cards ───────────────────────────────── */
QFrame#Panel {
    background-color: #FFFFFF;
    border: 1px solid #E2E3E8;
    border-radius: 10px;
}

QFrame#PanelCompact {
    background-color: #FFFFFF;
    border: 1px solid #E2E3E8;
    border-radius: 8px;
}

QFrame#ToolbarGroup {
    background-color: transparent;
    border: none;
}

/* ── Typography ───────────────────────────────────── */
QLabel#H1 {
    color: #0A0A0F;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.4px;
}
QLabel#Subtitle {
    color: #8E8E99;
    font-size: 11px;
    font-weight: 400;
}
QLabel#SectionTitle {
    color: #9A9AA8;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.8px;
    text-transform: uppercase;
}
QLabel#Counter {
    color: #9A9AA8;
    font-size: 11px;
    font-weight: 500;
}
QLabel#VoiceReadout {
    color: #1D1D23;
    font-size: 13px;
    font-weight: 600;
}

/* ── Badges ───────────────────────────────────────── */
QLabel#Badge {
    color: #FFFFFF;
    font-weight: 700;
    font-size: 9px;
    letter-spacing: 1.5px;
    padding: 3px 10px;
    border-radius: 5px;
}

/* ── Feature dot ──────────────────────────────────── */
QLabel#FeatureDot {
    color: #7B61FF;
    font-size: 18px;
    font-weight: bold;
}

/* ── Editor ───────────────────────────────────────── */
QPlainTextEdit {
    background-color: #FCFCFD;
    color: #1D1D23;
    border: 1px solid #E2E3E8;
    border-radius: 8px;
    padding: 16px;
    selection-background-color: #7B61FF;
    selection-color: #FFFFFF;
    font-family: 'Consolas', 'Cascadia Code', 'JetBrains Mono', 'Menlo', monospace;
    font-size: 12px;
    line-height: 1.5;
}
QPlainTextEdit:focus {
    border: 1px solid #7B61FF;
}

/* ── Voice List ───────────────────────────────────── */
QListWidget {
    background-color: #FCFCFD;
    color: #1D1D23;
    border: 1px solid #E2E3E8;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    border-radius: 6px;
    padding: 8px 10px;
    margin: 2px 0px;
}
QListWidget::item:hover {
    background-color: #F3F3F7;
}
QListWidget::item:selected {
    background-color: #7B61FF;
    color: #FFFFFF;
}
QListWidget::item QLabel {
    background-color: transparent;
    color: #1D1D23;
}
QListWidget::item:selected QLabel {
    color: #FFFFFF;
}

/* ── Search Bar ───────────────────────────────────── */
QLineEdit#VoiceSearch {
    background-color: #FCFCFD;
    color: #6B6B78;
    border: 1px solid #E2E3E8;
    border-radius: 8px;
    padding: 8px 12px 8px 34px;
    font-size: 12px;
    selection-background-color: #7B61FF;
    selection-color: #FFFFFF;
}
QLineEdit#VoiceSearch:focus {
    border: 1px solid #7B61FF;
    color: #1D1D23;
}

/* ── Action Button Bar ────────────────────────────── */
QFrame#ActionBar {
    background-color: #FFFFFF;
    border: 1px solid #E2E3E8;
    border-radius: 10px;
}

/* ── Buttons ──────────────────────────────────────── */
QPushButton {
    background-color: #FCFCFD;
    color: #1D1D23;
    border: 1px solid #E2E3E8;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #F3F3F7;
    border-color: #D0D0D8;
}
QPushButton:pressed {
    background-color: #E8E8EE;
}
QPushButton:disabled {
    color: #B0B0BA;
    border-color: #E8E8EE;
    background-color: #F8F8FA;
}

/* Primary action */
QPushButton[role="primary"] {
    background-color: #7B61FF;
    color: #FFFFFF;
    border: 1px solid #7B61FF;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 24px;
    letter-spacing: 0.3px;
}
QPushButton[role="primary"]:hover {
    background-color: #8B75FF;
    border-color: #8B75FF;
}
QPushButton[role="primary"]:pressed {
    background-color: #6B51E5;
}
QPushButton[role="primary"]:disabled {
    background-color: #D8D0FF;
    border-color: #D8D0FF;
    color: #8B85B0;
}

/* Danger */
QPushButton[role="danger"] {
    background-color: #E5484D;
    color: #FFFFFF;
    border: 1px solid #E5484D;
}
QPushButton[role="danger"]:hover {
    background-color: #F25F63;
    border-color: #F25F63;
}
QPushButton[role="danger"]:disabled {
    background-color: #F5C0C2;
    border-color: #F5C0C2;
    color: #A08080;
}

/* Ghost / flat */
QPushButton[role="ghost"] {
    background-color: transparent;
    border: 1px solid transparent;
}
QPushButton[role="ghost"]:hover {
    background-color: #F3F3F7;
    border-color: #E2E3E8;
}
QPushButton[role="ghost"]:disabled {
    background-color: transparent;
    border-color: transparent;
    color: #B0B0BA;
}

/* Feature icon button (compact) */
QPushButton[role="feature"] {
    background-color: transparent;
    color: #6B6B78;
    border: 1px solid #E2E3E8;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton[role="feature"]:hover {
    background-color: #F3F3F7;
    color: #1D1D23;
    border-color: #D0D0D8;
}
QPushButton[role="feature"]:pressed {
    background-color: #E8E8EE;
}
QPushButton[role="feature"]:disabled {
    color: #B0B0BA;
    border-color: #E8E8EE;
}

/* ── Inputs ───────────────────────────────────────── */
QDoubleSpinBox, QComboBox, QLineEdit, QSpinBox {
    background-color: #FCFCFD;
    color: #1D1D23;
    border: 1px solid #E2E3E8;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #7B61FF;
    font-size: 12px;
}
QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #7B61FF;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #FCFCFD;
    color: #1D1D23;
    border: 1px solid #E2E3E8;
    selection-background-color: #7B61FF;
    padding: 4px;
    outline: none;
}

/* ── Checkboxes ───────────────────────────────────── */
QCheckBox {
    color: #6B6B78;
    font-size: 12px;
    font-weight: 500;
    spacing: 6px;
}
QCheckBox:hover {
    color: #1D1D23;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #D0D0D8;
    border-radius: 4px;
    background-color: #FCFCFD;
}
QCheckBox::indicator:checked {
    background-color: #7B61FF;
    border-color: #7B61FF;
}
QCheckBox::indicator:hover {
    border-color: #7B61FF;
}

/* ── Sliders ──────────────────────────────────────── */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background-color: #E2E3E8;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #7B61FF;
    border: none;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #8B75FF;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::sub-page:horizontal {
    background-color: #7B61FF;
    border-radius: 2px;
}

/* ── Progress Bar ─────────────────────────────────── */
QProgressBar {
    background-color: #E2E3E8;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 8px;
}
QProgressBar::chunk {
    background-color: #7B61FF;
    border-radius: 4px;
}

/* ── Status Bar ───────────────────────────────────── */
QStatusBar {
    background-color: #F0F1F5;
    color: #6B6B78;
    border-top: 1px solid #E2E3E8;
    font-size: 12px;
    padding: 2px 12px;
}
QStatusBar QLabel {
    color: #6B6B78;
    padding: 0 8px;
    font-size: 12px;
}
QStatusBar QProgressBar {
    max-height: 6px;
    min-height: 6px;
    min-width: 120px;
    max-width: 120px;
}

/* ── Splitter ─────────────────────────────────────── */
QSplitter::handle {
    background-color: transparent;
}

/* ── Tooltips ─────────────────────────────────────── */
QToolTip {
    background-color: #FCFCFD;
    color: #1D1D23;
    border: 1px solid #E2E3E8;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12px;
}

/* ── Scrollbars ───────────────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #D0D0D8;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #B0B0BA;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
}
QScrollBar:horizontal {
    background: transparent;
    height: 6px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #D0D0D8;
    border-radius: 3px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #B0B0BA;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: none;
}
"""


# ===========================================================================
# Dialog QSS — dark
# ===========================================================================

SETTINGS_QSS_DARK = """
QDialog {
    background-color: #0F1115;
}

QTabWidget::pane {
    border: 1px solid #252932;
    background-color: #1A1D24;
    border-radius: 0px;
    top: 0px;
}
QTabBar {
    background-color: transparent;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background-color: transparent;
    color: #9DA0A8;
    padding: 9px 18px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #1A1D24;
    color: #E8EAED;
    border-bottom: 2px solid #7B61FF;
}
QTabBar::tab:hover:!selected {
    color: #E8EAED;
}

QLabel#SettingsH1 {
    color: #FFFFFF;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
}
QLabel#SettingsBlock {
    color: #E8EAED;
    font-size: 12px;
    line-height: 1.6;
}
QLabel#AddrLabel {
    color: #6B7280;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
}

QTableWidget {
    background-color: #1F2329;
    color: #E8EAED;
    border: 1px solid #252932;
    border-radius: 8px;
    gridline-color: #252932;
}
QHeaderView::section {
    background-color: #1A1D24;
    color: #6B7280;
    border: none;
    border-bottom: 1px solid #252932;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 1.2px;
}

QLineEdit#AddressReadOnly {
    background-color: #252932;
    color: #E8EAED;
    border: 1px solid #2F3340;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #7B61FF;
}
"""


# ===========================================================================
# Dialog QSS — light
# ===========================================================================

SETTINGS_QSS_LIGHT = """
QDialog {
    background-color: #F2F2F7;
}

QTabWidget::pane {
    border: 1px solid #D1D1D6;
    background-color: #FFFFFF;
    border-radius: 0px;
    top: 0px;
}
QTabBar {
    background-color: transparent;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background-color: transparent;
    color: #8E8E93;
    padding: 9px 18px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border-bottom: 2px solid #7B61FF;
}
QTabBar::tab:hover:!selected {
    color: #1C1C1E;
}

QLabel#SettingsH1 {
    color: #000000;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
}
QLabel#SettingsBlock {
    color: #1C1C1E;
    font-size: 12px;
    line-height: 1.6;
}
QLabel#AddrLabel {
    color: #8E8E93;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
}

QTableWidget {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 8px;
    gridline-color: #E5E5EA;
}
QHeaderView::section {
    background-color: #F2F2F7;
    color: #8E8E93;
    border: none;
    border-bottom: 1px solid #D1D1D6;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 1.2px;
}

QLineEdit#AddressReadOnly {
    background-color: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #7B61FF;
}
"""


# ===========================================================================
# Convenience: pick the right QSS by theme mode
# ===========================================================================

def get_qss(mode: str) -> str:
    """Return the main application QSS for *mode* (dark or light)."""
    if mode == THEME_LIGHT:
        return QSS_LIGHT
    return QSS_DARK


def get_settings_qss(mode: str) -> str:
    """Return the settings-dialog QSS for *mode* (dark or light)."""
    if mode == THEME_LIGHT:
        return SETTINGS_QSS_LIGHT
    return SETTINGS_QSS_DARK


# ===========================================================================
# Helpers
# ===========================================================================

# Fixed phrases played when the user clicks "Preview selected voice". Each
# lang_code in LANG_CODES has a phrase in its own language.
PREVIEW_PHRASES = {
    "a": "Hello! This is a quick preview of my voice in American English.",
    "b": "Hello! This is a quick preview of my voice in British English.",
    "i": "Ciao! Questa è una breve anteprima della mia voce in Italiano.",
    "e": "¡Hola! Esta es una breve muestra de mi voz en español.",
    "f": "Bonjour ! Voici un court aperçu de ma voix en français.",
    "h": "Namaste! Yeh meri awaaz ka ek chhota preview hai.",
    "j": "こんにちは。これが日本語の私の声の短いプレビューです。",
    "z": "你好!这是我的中文声音的简短预览。",
    "p": "Olá! Esta é uma pequena amostra da minha voz em português.",
}


def preview_phrase_for_lang(lang_code: str) -> str:
    return PREVIEW_PHRASES.get(lang_code, PREVIEW_PHRASES["a"])


def default_output_dir() -> Path:
    """Return <Documents>/KokoroStudio (auto-create). Falls back gracefully."""
    if _HAS_PYSIDE6:
        try:
            docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        except Exception:
            docs = ""
    else:
        docs = ""
    base = Path(docs) if docs else Path.home() / "Documents"
    folder = base / "KokoroStudio"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path.cwd()
    return folder


def default_output_path(voice: str, fmt: str = "wav") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_voice = voice.replace("/", "_").replace("\\\\", "_")
    if fmt not in OUTPUT_FORMATS:
        fmt = "wav"
    return str(default_output_dir() / f"Kokoro_{safe_voice}_{ts}.{fmt}")


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{int(seconds * 1000)} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {s:05.2f}s"


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


# SSML-lite Help dialog content (Phase 2).
SSML_HELP_SAMPLE = """\
SSML-lite controls (Phase 2)

Type the literal markup into the editor. Markers
expand once the "Apply SSML" checkbox on the controls
panel is ON.

  <break time="1.5s"/>          Insert a 1.5-second silence.
  <break time="500ms"/>          Millisecond precision is accepted.

  <emphasis>word</emphasis>      Slows down the wrapped word
                                (effective rate: 0.85x of
                                base speed).

  <prosody rate="fast">...</prosody>
                                Speeds up the wrapped phrase.
  <prosody rate="0.8">...</prosody>
                                Numeric multipliers also work
                                (0.8 = 80% of base speed).

  Valid rate tokens:     x-slow (0.6), slow (0.8),
                         medium (1.0), fast (1.4),
                         x-fast (1.8).
  Numeric rate range:    0.5 .. 2.0  (clipped to safe band).

Notes:

  * SSML-lite and multi-speaker dialogue are mutually
    exclusive. When dialogue mode is on, SSML is silently
    ignored -- the chip turns amber to warn you.
  * The chip above the Generate button shows a
    one-line summary ("1 break + 2 emphasis + 1 prosody")
    that updates as you type.
  * Plain text without markers works as usual; toggling
    the checkbox on by accident has zero side-effects.
"""

# Short TTS samples (kept distinct from the long prose help-text docs
# so the Insert-sample button in the help dialogs drops a runnable
# script into the editor instead of documentation).
DIALOGUE_HELP_TTS_SAMPLE = (
    "[af_sky]: Hi traveller!\n"
    "[af_nicole]: Greetings, friend.\n"
    "[af_bella]: Let our tale begin.\n"
    "And this line uses the default voice again."
)

SSML_HELP_TTS_SAMPLE = (
    'Hello <break time="0.4s"/> I can pause, '
    '<emphasis>emphasise</emphasis>, and '
    '<prosody rate="fast">speak at speed</prosody>.'
)
