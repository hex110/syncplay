"""
Syncplay Dark Theme Engine
==========================

Centralised theming using QStyleFactory("Fusion") + a custom QPalette + global QSS.

Usage:
    from syncplay.ui.theme import apply_theme
    apply_theme(QApplication.instance())

This replaces all scattered isDarkMode checks and inline style constants.
"""

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt


# ── Colour Palette ──────────────────────────────────────────────────────────

class Colors:
    """Design-system colour tokens. Reference these instead of hex literals."""
    BG_BASE      = "#202225"   # App background
    BG_SURFACE   = "#2f3136"   # Panels, cards, group boxes
    BG_INPUT     = "#40444b"   # Text inputs, list items
    BG_ELEVATED  = "#36393f"   # Elevated surfaces, tooltips

    BRAND        = "#5865F2"   # Primary action (blurple)
    BRAND_HOVER  = "#4752C4"   #  – hover state
    BRAND_ACTIVE = "#3C45A5"   #  – pressed state

    SUCCESS      = "#3BA55C"   # Ready / success
    SUCCESS_HOVER= "#2D8049"
    DANGER       = "#ED4245"   # Disconnect / error
    DANGER_HOVER = "#C03537"

    TEXT_MAIN    = "#dcddde"   # Primary text
    TEXT_MUTED   = "#96989d"   # Secondary / placeholder text
    TEXT_LINK    = "#00AFF4"   # Hyperlinks

    BORDER       = "#202225"   # Subtle borders between panels
    BORDER_INPUT = "#040405"   # Input field borders
    SCROLLBAR    = "#202225"   # Scrollbar track
    SCROLLBAR_TH = "#4f545c"   # Scrollbar thumb

    SEPARATOR    = "#3e4046"   # Splitter handles, dividers

    # Semantic user-list colours
    DIFFERENT_FILE  = "#E94F64"
    NO_FILE         = "#00AFF4"
    UNTRUSTED       = "#882fbc"
    NOT_CONTROLLER  = "#96989d"


# ── QPalette ────────────────────────────────────────────────────────────────

def _build_dark_palette() -> QtGui.QPalette:
    """Build a QPalette matching the Discord/VS Code dark aesthetic."""
    p = QtGui.QPalette()

    # Window / Widget backgrounds
    p.setColor(QtGui.QPalette.Window,          QtGui.QColor(Colors.BG_BASE))
    p.setColor(QtGui.QPalette.WindowText,      QtGui.QColor(Colors.TEXT_MAIN))
    p.setColor(QtGui.QPalette.Base,            QtGui.QColor(Colors.BG_INPUT))
    p.setColor(QtGui.QPalette.AlternateBase,   QtGui.QColor(Colors.BG_SURFACE))
    p.setColor(QtGui.QPalette.ToolTipBase,     QtGui.QColor(Colors.BG_ELEVATED))
    p.setColor(QtGui.QPalette.ToolTipText,     QtGui.QColor(Colors.TEXT_MAIN))

    # Text
    p.setColor(QtGui.QPalette.Text,            QtGui.QColor(Colors.TEXT_MAIN))
    p.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(Colors.TEXT_MUTED))
    p.setColor(QtGui.QPalette.BrightText,      QtGui.QColor("#ffffff"))

    # Buttons
    p.setColor(QtGui.QPalette.Button,          QtGui.QColor(Colors.BG_SURFACE))
    p.setColor(QtGui.QPalette.ButtonText,      QtGui.QColor(Colors.TEXT_MAIN))

    # Selections
    p.setColor(QtGui.QPalette.Highlight,       QtGui.QColor(Colors.BRAND))
    p.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))

    # Links
    p.setColor(QtGui.QPalette.Link,            QtGui.QColor(Colors.TEXT_LINK))
    p.setColor(QtGui.QPalette.LinkVisited,     QtGui.QColor(Colors.BRAND))

    # Disabled states
    p.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText,  QtGui.QColor(Colors.TEXT_MUTED))
    p.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text,        QtGui.QColor(Colors.TEXT_MUTED))
    p.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText,  QtGui.QColor(Colors.TEXT_MUTED))

    return p


# ── Global QSS ─────────────────────────────────────────────────────────────

DARK_QSS = f"""
/* ===================================================================
   Syncplay Global Dark Theme — QSS
   =================================================================== */

/* ── Base widgets ─────────────────────────────────────────────────── */

QMainWindow, QDialog {{
    background-color: {Colors.BG_BASE};
    color: {Colors.TEXT_MAIN};
}}

QFrame {{
    border: none;
}}

QSplitter::handle {{
    background-color: {Colors.SEPARATOR};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}

/* ── Labels ───────────────────────────────────────────────────────── */

QLabel {{
    color: {Colors.TEXT_MAIN};
    background: transparent;
}}

QLabel#sectionLabel {{
    color: {Colors.TEXT_MUTED};
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    padding: 6px 4px 4px 4px;
    letter-spacing: 0.5px;
}}

/* ── Inputs ───────────────────────────────────────────────────────── */

QLineEdit, QComboBox, QSpinBox {{
    background-color: {Colors.BG_INPUT};
    color: {Colors.TEXT_MAIN};
    border: 1px solid {Colors.BORDER_INPUT};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {Colors.BRAND};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {Colors.BRAND};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: {Colors.BG_SURFACE};
    color: {Colors.TEXT_MAIN};
    selection-background-color: {Colors.BRAND};
    border: 1px solid {Colors.BORDER_INPUT};
    outline: none;
}}

/* ── Text Browser (Chat / Log) ────────────────────────────────────── */

QTextBrowser, QTextEdit {{
    background-color: {Colors.BG_SURFACE};
    color: {Colors.TEXT_MAIN};
    border: 1px solid {Colors.BORDER};
    border-radius: 4px;
    padding: 4px;
    selection-background-color: {Colors.BRAND};
}}

/* ── Lists & Trees ────────────────────────────────────────────────── */

QListWidget, QTreeView {{
    background-color: {Colors.BG_SURFACE};
    color: {Colors.TEXT_MAIN};
    border: 1px solid {Colors.BORDER};
    border-radius: 4px;
    outline: none;
    padding: 2px;
}}

QListWidget::item, QTreeView::item {{
    padding: 4px 6px;
    border-radius: 3px;
}}

QListWidget::item:selected, QTreeView::item:selected {{
    background-color: {Colors.BG_INPUT};
    color: {Colors.TEXT_MAIN};
}}

QListWidget::item:hover, QTreeView::item:hover {{
    background-color: {Colors.BG_INPUT};
}}

QTreeView::branch {{
    background: transparent;
}}

QHeaderView::section {{
    background-color: {Colors.BG_SURFACE};
    color: {Colors.TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {Colors.SEPARATOR};
    padding: 4px 8px;
    font-weight: 600;
}}

/* ── Group Boxes ──────────────────────────────────────────────────── */

QGroupBox {{
    background-color: {Colors.BG_SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
    color: {Colors.TEXT_MAIN};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: {Colors.TEXT_MUTED};
}}

QGroupBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {Colors.TEXT_MUTED};
    background: transparent;
}}

QGroupBox::indicator:checked {{
    background-color: {Colors.BRAND};
    border-color: {Colors.BRAND};
}}

/* ── Scroll Bars ──────────────────────────────────────────────────── */

QScrollBar:vertical {{
    background: {Colors.SCROLLBAR};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {Colors.SCROLLBAR_TH};
    min-height: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {Colors.TEXT_MUTED};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: {Colors.SCROLLBAR};
    height: 8px;
    margin: 0;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background: {Colors.SCROLLBAR_TH};
    min-width: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {Colors.TEXT_MUTED};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Menu Bar / Menus ─────────────────────────────────────────────── */

QMenuBar {{
    background-color: {Colors.BG_BASE};
    color: {Colors.TEXT_MAIN};
    border-bottom: 1px solid {Colors.SEPARATOR};
    padding: 2px 0px;
}}

QMenuBar::item {{
    padding: 4px 10px;
    border-radius: 3px;
    background: transparent;
}}

QMenuBar::item:selected {{
    background-color: {Colors.BG_INPUT};
}}

QMenu {{
    background-color: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_MAIN};
    border: 1px solid {Colors.BORDER_INPUT};
    border-radius: 4px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 3px;
}}

QMenu::item:selected {{
    background-color: {Colors.BRAND};
    color: white;
}}

QMenu::separator {{
    height: 1px;
    background: {Colors.SEPARATOR};
    margin: 4px 8px;
}}

/* ── Tooltips ─────────────────────────────────────────────────────── */

QToolTip {{
    background-color: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_MAIN};
    border: 1px solid {Colors.BORDER_INPUT};
    border-radius: 4px;
    padding: 6px 8px;
}}

/* ── Message Boxes / Dialogs ──────────────────────────────────────── */

QMessageBox {{
    background-color: {Colors.BG_SURFACE};
}}

/* ===================================================================
   Button Tiers
   =================================================================== */

/* ── Default / Tier 2 (Secondary) ────────────────────────────────── */

QPushButton {{
    background-color: transparent;
    color: {Colors.TEXT_MAIN};
    border: 1px solid {Colors.BG_INPUT};
    border-radius: 4px;
    padding: 5px 14px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {Colors.BG_INPUT};
    border-color: {Colors.TEXT_MUTED};
}}

QPushButton:pressed {{
    background-color: {Colors.BG_BASE};
}}

QPushButton:disabled {{
    color: {Colors.TEXT_MUTED};
    border-color: {Colors.BORDER};
}}

/* ── Tier 1 (Primary — the Happy Path) ───────────────────────────── */

QPushButton[buttonTier="primary"] {{
    background-color: {Colors.BRAND};
    color: white;
    border: none;
    font-weight: 700;
    padding: 6px 18px;
}}

QPushButton[buttonTier="primary"]:hover {{
    background-color: {Colors.BRAND_HOVER};
}}

QPushButton[buttonTier="primary"]:pressed {{
    background-color: {Colors.BRAND_ACTIVE};
}}

/* Primary button in "checked/ready" state → green */
QPushButton[buttonTier="primary"]:checked {{
    background-color: {Colors.SUCCESS};
}}

QPushButton[buttonTier="primary"]:checked:hover {{
    background-color: {Colors.SUCCESS_HOVER};
}}

/* ── Tier 3 (Tertiary / Ghost) ───────────────────────────────────── */

QPushButton[buttonTier="tertiary"] {{
    background-color: transparent;
    border: none;
    padding: 4px 6px;
    border-radius: 4px;
}}

QPushButton[buttonTier="tertiary"]:hover {{
    background-color: {Colors.BG_INPUT};
}}

QPushButton[buttonTier="tertiary"]:pressed {{
    background-color: {Colors.BG_BASE};
}}

/* ── Danger variant ──────────────────────────────────────────────── */

QPushButton[buttonTier="danger"] {{
    background-color: {Colors.DANGER};
    color: white;
    border: none;
    font-weight: 700;
    padding: 6px 18px;
}}

QPushButton[buttonTier="danger"]:hover {{
    background-color: {Colors.DANGER_HOVER};
}}

/* ===================================================================
   Control Deck (Zone C)
   =================================================================== */

QFrame#controlDeck {{
    background-color: {Colors.BG_SURFACE};
    border-top: 1px solid {Colors.SEPARATOR};
    padding: 6px 10px;
}}

/* ===================================================================
   Section panels
   =================================================================== */

QFrame#panelZoneA, QFrame#panelZoneB {{
    background-color: {Colors.BG_BASE};
    border: none;
}}
"""


# ── Public API ──────────────────────────────────────────────────────────────

def apply_theme(app: QtWidgets.QApplication) -> None:
    """Apply the Syncplay dark theme globally.

    Call this once, right after QApplication creation and *before*
    constructing any windows.

    Args:
        app: The running QApplication instance.
    """
    # 1) Use the Fusion style as a consistent cross-platform base
    app.setStyle(QtWidgets.QStyleFactory.create("Fusion"))

    # 2) Apply our custom dark palette
    app.setPalette(_build_dark_palette())

    # 3) Layer the global QSS on top for fine-grained control
    app.setStyleSheet(DARK_QSS)
