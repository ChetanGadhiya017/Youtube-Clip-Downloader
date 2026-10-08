"""Light and dark Qt style sheets."""

from __future__ import annotations

from pathlib import Path

ICONS = (Path(__file__).parent / "assets" / "icons").as_posix()

PALETTES = {
    "light": {
        "bg": "#f4f6fb", "surface": "#ffffff", "surface2": "#f8fafc", "ink": "#0f172a", "ink2": "#334155",
        "muted": "#64748b", "line": "#e2e8f0", "line2": "#cbd5e1", "brand": "#e11d48", "brand2": "#be123c",
        "brandSoft": "#ffe4e6", "ok": "#16a34a", "warn": "#d97706", "err": "#dc2626", "track": "#e2e8f0",
    },
    "dark": {
        "bg": "#0b1120", "surface": "#111827", "surface2": "#0f172a", "ink": "#e5e7eb", "ink2": "#cbd5e1",
        "muted": "#94a3b8", "line": "#1f2937", "line2": "#334155", "brand": "#f43f5e", "brand2": "#e11d48",
        "brandSoft": "#4c0519", "ok": "#4ade80", "warn": "#fbbf24", "err": "#f87171", "track": "#1f2937",
    },
}


def stylesheet(name: str) -> str:
    c = PALETTES.get(name, PALETTES["light"])
    return f"""
    QWidget {{ background: {c['bg']}; color: {c['ink']}; font-size: 10pt; }}
    QToolTip {{ background: {c['ink']}; color: {c['bg']}; border: 0; padding: 4px 6px; }}
    QFrame#card, QFrame#jobCard {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 12px; }}
    QFrame#jobCard[state="done"] {{ border-left: 4px solid {c['ok']}; }}
    QFrame#jobCard[state="failed"] {{ border-left: 4px solid {c['err']}; }}
    QFrame#jobCard[state="paused"] {{ border-left: 4px solid {c['warn']}; }}
    QFrame#jobCard[state="downloading"], QFrame#jobCard[state="processing"] {{ border-left: 4px solid {c['brand']}; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-size: 13pt; font-weight: 700; }}
    QLabel#appTitle {{ font-size: 15pt; font-weight: 800; }}
    QLabel#muted, QLabel#subtitle {{ color: {c['muted']}; }}
    QLabel#section {{ color: {c['muted']}; font-weight: 700; font-size: 8.5pt; letter-spacing: 1px; }}
    QLabel#badge {{ background: {c['brandSoft']}; color: {c['brand']}; border-radius: 8px; padding: 2px 8px; font-weight: 600; }}
    QLabel#warning {{ background: {c['brandSoft']}; color: {c['brand']}; border-radius: 8px; padding: 6px 10px; }}
    QLabel#thumb {{ background: {c['surface2']}; border-radius: 10px; color: {c['muted']}; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
        background: {c['surface']}; border: 1px solid {c['line2']}; border-radius: 8px; padding: 6px 8px;
        selection-background-color: {c['brand']}; selection-color: white;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {c['brand']}; }}
    QLineEdit#urlBar {{ font-size: 11pt; padding: 9px 12px; border-radius: 10px; }}
    QLineEdit[invalid="true"] {{ border: 1px solid {c['err']}; }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox::down-arrow {{ image: url({ICONS}/chevron-{'dark' if name == 'dark' else 'light'}.svg); width: 12px; height: 12px; margin-right: 8px; }}
    QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['line2']}; selection-background-color: {c['brandSoft']}; selection-color: {c['ink']}; }}
    QPushButton {{
        background: {c['surface']}; border: 1px solid {c['line2']}; border-radius: 8px; padding: 7px 14px; font-weight: 600;
    }}
    QPushButton:hover {{ border-color: {c['brand']}; }}
    QPushButton:disabled {{ color: {c['muted']}; border-color: {c['line']}; }}
    QPushButton#primary {{ background: {c['brand']}; color: white; border: 1px solid {c['brand']}; }}
    QPushButton#primary:hover {{ background: {c['brand2']}; }}
    QPushButton#primary:disabled {{ background: {c['line2']}; border-color: {c['line2']}; color: {c['muted']}; }}
    QPushButton#flat, QToolButton {{ background: transparent; border: 0; padding: 4px 6px; border-radius: 6px; }}
    QPushButton#flat:hover, QToolButton:hover {{ background: {c['brandSoft']}; }}
    QCheckBox {{ background: transparent; spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1.5px solid {c['line2']}; border-radius: 5px; background: {c['surface']}; }}
    QCheckBox::indicator:checked {{ background: {c['brand']}; border-color: {c['brand']}; image: url({ICONS}/check.svg); }}
    QCheckBox::indicator:disabled {{ background: {c['line']}; }}
    QProgressBar {{ background: {c['track']}; border: 0; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {c['brand']}; border-radius: 4px; }}
    QProgressBar[state="done"]::chunk {{ background: {c['ok']}; }}
    QProgressBar[state="paused"]::chunk {{ background: {c['warn']}; }}
    QTabWidget::pane {{ border: 0; }}
    QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {c['muted']}; font-weight: 600; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['ink']}; border-bottom: 2px solid {c['brand']}; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {c['line2']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QTableWidget {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 10px; gridline-color: {c['line']}; }}
    QHeaderView::section {{ background: {c['surface2']}; color: {c['muted']}; border: 0; border-bottom: 1px solid {c['line']}; padding: 6px; font-weight: 700; }}
    QTableWidget::item:selected {{ background: {c['brandSoft']}; color: {c['ink']}; }}
    QDialog {{ background: {c['bg']}; }}
    QGroupBox {{ border: 1px solid {c['line']}; border-radius: 10px; margin-top: 14px; padding: 10px; font-weight: 700; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['muted']}; }}
    QStatusBar {{ color: {c['muted']}; }}
    """


def color(name: str, key: str) -> str:
    return PALETTES.get(name, PALETTES["light"])[key]
