"""Custom widgets: time-range slider, video preview card and queue job card."""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .core import format_timestamp, human_count, human_duration


# --------------------------------------------------------------------------- range slider
class RangeSlider(QWidget):
    """Two-handle slider over [0, duration] seconds."""

    rangeChanged = pyqtSignal(float, float)

    HANDLE = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 0.0
        self.start = 0.0
        self.end = 0.0
        self._drag = None
        self.colors = {"track": "#e2e8f0", "range": "#e11d48", "handle": "#ffffff", "text": "#64748b"}
        self.setMinimumHeight(46)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setEnabled(False)

    def set_colors(self, **kw) -> None:
        self.colors.update(kw)
        self.update()

    def set_duration(self, seconds: float | None) -> None:
        self.duration = float(seconds or 0)
        self.start, self.end = 0.0, self.duration
        self.setEnabled(self.duration > 0)
        self.update()

    def set_range(self, start: float, end: float, emit: bool = False) -> None:
        if self.duration <= 0:
            return
        self.start = max(0.0, min(start, self.duration))
        self.end = max(self.start, min(end, self.duration))
        self.update()
        if emit:
            self.rangeChanged.emit(self.start, self.end)

    # geometry
    def _x(self, t: float) -> float:
        w = self.width() - 2 * (self.HANDLE + 2)
        return self.HANDLE + 2 + (t / self.duration * w if self.duration else 0)

    def _t(self, x: float) -> float:
        w = self.width() - 2 * (self.HANDLE + 2)
        return max(0.0, min(self.duration, (x - self.HANDLE - 2) / w * self.duration)) if w > 0 else 0.0

    def paintEvent(self, _):  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = 16
        left, right = self._x(0), self._x(self.duration) if self.duration else self.width() - self.HANDLE - 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.colors["track"]))
        p.drawRoundedRect(QRectF(left, cy - 3, right - left, 6), 3, 3)
        if self.duration > 0:
            xs, xe = self._x(self.start), self._x(self.end)
            p.setBrush(QColor(self.colors["range"]))
            p.drawRoundedRect(QRectF(xs, cy - 3, xe - xs, 6), 3, 3)
            for x in (xs, xe):
                p.setPen(QPen(QColor(self.colors["range"]), 2.5))
                p.setBrush(QColor(self.colors["handle"]))
                p.drawEllipse(QPointF(x, cy), self.HANDLE, self.HANDLE)
            p.setPen(QColor(self.colors["text"]))
            f = QFont(self.font())
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.drawText(QRectF(0, cy + 12, self.width(), 16), Qt.AlignLeft, "0:00")
            p.drawText(QRectF(0, cy + 12, self.width(), 16), Qt.AlignRight, human_duration(self.duration))
            sel = f"{human_duration(self.start)} → {human_duration(self.end)}  ({human_duration(self.end - self.start)})"
            p.drawText(QRectF(0, cy + 12, self.width(), 16), Qt.AlignHCenter, sel)
        p.end()

    def mousePressEvent(self, e):  # noqa: N802
        if self.duration <= 0:
            return
        x = e.pos().x()
        ds, de = abs(x - self._x(self.start)), abs(x - self._x(self.end))
        self._drag = "start" if ds < de or (ds == de and x < self._x(self.start)) else "end"
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is None:
            near = self.duration > 0 and min(abs(e.pos().x() - self._x(self.start)), abs(e.pos().x() - self._x(self.end))) < 12
            self.setCursor(Qt.SizeHorCursor if near else Qt.ArrowCursor)
            return
        t = round(self._t(e.pos().x()))
        if self._drag == "start":
            self.start = min(t, self.end - 1) if self.end >= 1 else 0
        else:
            self.end = max(t, self.start + 1) if self.start + 1 <= self.duration else self.duration
        self.update()
        self.rangeChanged.emit(self.start, self.end)

    def mouseReleaseEvent(self, _):  # noqa: N802
        self._drag = None


# --------------------------------------------------------------------------- preview card
class VideoCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(14)
        self.thumb = QLabel("🎬")
        self.thumb.setObjectName("thumb")
        self.thumb.setFixedSize(224, 126)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("font-size: 28pt;")
        lay.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel("Paste a YouTube link above and press Fetch")
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        self.meta = QLabel("You'll see the title, length and available qualities here.")
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)
        badges = QHBoxLayout()
        badges.setSpacing(6)
        self.badge_q = QLabel()
        self.badge_q.setObjectName("badge")
        self.badge_s = QLabel()
        self.badge_s.setObjectName("badge")
        for b in (self.badge_q, self.badge_s):
            b.hide()
            badges.addWidget(b)
        badges.addStretch()
        col.addWidget(self.title)
        col.addWidget(self.meta)
        col.addLayout(badges)
        col.addStretch()
        lay.addLayout(col, 1)

    def set_loading(self, url: str) -> None:
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("Loading…")
        self.title.setText("Fetching video details…")
        self.meta.setText(url)
        self.badge_q.hide()
        self.badge_s.hide()

    def set_error(self, message: str) -> None:
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("⚠")
        self.badge_q.hide()
        self.badge_s.hide()
        self.title.setText("Couldn't load this video")
        self.meta.setText(message)

    def set_info(self, info) -> None:
        self.title.setText(info.title)
        bits = [b for b in (info.channel, human_duration(info.duration) if info.duration else "",
                            f"{human_count(info.view_count)} views" if info.view_count else "",
                            _date(info.upload_date)) if b]
        self.meta.setText("  ·  ".join(bits))
        if info.best_height:
            self.badge_q.setText(f"up to {info.best_height}p")
            self.badge_q.show()
        if info.subtitles:
            self.badge_s.setText(f"CC · {len(info.subtitles)} languages")
            self.badge_s.show()
        self.thumb.setText("🎬")

    def set_thumbnail(self, data: bytes) -> None:
        pm = QPixmap()
        if pm.loadFromData(data):
            self.thumb.setPixmap(_rounded(pm.scaled(self.thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation),
                                          self.thumb.size(), 10))


def _date(s: str | None) -> str:
    if not s or len(s) != 8:
        return ""
    return f"{s[6:8]}-{s[4:6]}-{s[:4]}"


def _rounded(pm: QPixmap, size, radius: int) -> QPixmap:
    out = QPixmap(size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
    p.setClipPath(path)
    x = (pm.width() - size.width()) // 2
    y = (pm.height() - size.height()) // 2
    p.drawPixmap(-x, -y, pm)
    p.end()
    return out


# --------------------------------------------------------------------------- job card
class JobCard(QFrame):
    pauseClicked = pyqtSignal(int)
    resumeClicked = pyqtSignal(int)
    cancelClicked = pyqtSignal(int)
    retryClicked = pyqtSignal(int)
    openClicked = pyqtSignal(int)
    removeClicked = pyqtSignal(int)

    def __init__(self, job_id: int, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.job_id = job_id
        self.setObjectName("jobCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight: 700;")
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(8)
        self.status = QLabel("Queued")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.title.setWordWrap(True)
        for lbl in (self.title, self.sub, self.status):
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lbl.setMinimumWidth(0)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        col.addWidget(self.bar)
        col.addWidget(self.status)
        lay.addLayout(col, 1)

        self.buttons = {}
        for key, text, tip, sig in (
            ("pause", "⏸", "Pause", self.pauseClicked),
            ("resume", "▶", "Resume", self.resumeClicked),
            ("retry", "↻", "Retry", self.retryClicked),
            ("open", "📂", "Show in folder", self.openClicked),
            ("cancel", "✕", "Cancel", self.cancelClicked),
            ("remove", "🗑", "Remove from list", self.removeClicked),
        ):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.setFixedSize(34, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=sig: s.emit(self.job_id))
            lay.addWidget(b)
            self.buttons[key] = b
        self.set_state("queued", "Queued")

    def set_state(self, state: str, text: str) -> None:
        self.setProperty("state", state)
        self.bar.setProperty("state", state)
        for w in (self, self.bar):
            w.style().unpolish(w)
            w.style().polish(w)
        self.status.setText(text)
        visible = {
            "queued": {"cancel"},
            "starting": {"pause", "cancel"},
            "downloading": {"pause", "cancel"},
            "processing": {"cancel"},
            "paused": {"resume", "cancel"},
            "done": {"open", "remove"},
            "failed": {"retry", "remove"},
            "cancelled": {"retry", "remove"},
        }.get(state, {"cancel"})
        for k, b in self.buttons.items():
            b.setVisible(k in visible)
        if state == "done":
            self.bar.setValue(1000)

    def set_progress(self, percent: float, text: str) -> None:
        self.bar.setValue(int(percent * 10))
        self.status.setText(text)


def time_range_text(req) -> str:
    if req.is_clip:
        return f"{format_timestamp(req.start)} → {format_timestamp(req.end)}"
    return "Full video"
