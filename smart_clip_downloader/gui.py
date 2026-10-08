"""Main window."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QThreadPool, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QShortcut,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .core import (
    AUDIO_FORMATS,
    QUALITY_PRESETS,
    VIDEO_CONTAINERS,
    ClipError,
    ClipRequest,
    extract_urls,
    ffmpeg_available,
    format_timestamp,
    human_duration,
    is_playlist_url,
    parse_batch,
    parse_timestamp,
)
from .history import History
from .settings import AppSettings, SettingsDialog
from .theme import color, stylesheet
from .widgets import JobCard, RangeSlider, VideoCard, time_range_text
from .workers import DownloadJob, InfoJob, ThumbJob

ICONS = Path(__file__).parent / "assets" / "icons"


def icon(name: str) -> QIcon:
    return QIcon(str(ICONS / f"{name}.png"))


def card(*widgets_or_layouts, title: str | None = None) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        t = QLabel(title.upper())
        t.setObjectName("section")
        lay.addWidget(t)
    for w in widgets_or_layouts:
        (lay.addLayout if hasattr(w, "addWidget") and not isinstance(w, QWidget) else lay.addWidget)(w)
    return f


class Job:
    __slots__ = ("id", "req", "card", "state", "worker", "file", "title")

    def __init__(self, job_id: int, req: ClipRequest, card_: JobCard, title: str):
        self.id, self.req, self.card, self.title = job_id, req, card_, title
        self.state = "queued"
        self.worker: DownloadJob | None = None
        self.file: str | None = None


class BatchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add many clips")
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        hint = QLabel("One job per line:  <b>URL</b>  ·  <b>URL START END</b>  ·  <b>URL START-END</b>"
                      "<br>Times can be SS, MM:SS or HH:MM:SS. Lines starting with # are ignored.")
        hint.setObjectName("muted")
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText("https://youtu.be/abc123 0:30 1:15\nhttps://youtu.be/xyz789 1:02:00-1:03:30\n"
                                    "https://youtu.be/full_video")
        lay.addWidget(hint)
        lay.addWidget(self.box, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add to queue")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None, history: History | None = None):
        super().__init__()
        self.settings = settings or AppSettings()
        self.history = history or History()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(8)
        self.jobs: dict[int, Job] = {}
        self.pending: list[int] = []
        self.next_id = 1
        self.info = None
        self.last_clip = ""
        self.session_done = 0
        self.session_failed = 0

        self.setWindowTitle("Smart Clip Downloader")
        self.setWindowIcon(icon("download"))
        self.resize(1240, 780)
        self.setAcceptDrops(True)
        self._build()
        self._apply_theme()
        self._load_prefs()
        self._refresh_history()
        self._update_status()
        self._setup_tray()

        QApplication.clipboard().dataChanged.connect(self._on_clipboard)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: (self.url.setFocus(), self.url.selectAll()))
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.add_current)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)

    # ================================================================== layout
    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 10)
        outer.setSpacing(12)

        # header
        head = QHBoxLayout()
        t = QLabel("🎬  Smart Clip Downloader")
        t.setObjectName("appTitle")
        sub = QLabel("Download exactly the part of a video you need")
        sub.setObjectName("subtitle")
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        tcol.addWidget(t)
        tcol.addWidget(sub)
        head.addLayout(tcol)
        head.addStretch()
        self.theme_btn = QPushButton("🌙")
        self.theme_btn.setObjectName("flat")
        self.theme_btn.setToolTip("Toggle light/dark theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        sbtn = QPushButton("⚙  Settings")
        sbtn.clicked.connect(self.open_settings)
        head.addWidget(self.theme_btn)
        head.addWidget(sbtn)
        outer.addLayout(head)

        self.ffmpeg_warn = QLabel("⚠  ffmpeg was not found. It's needed to cut clips, merge HD video and convert audio. "
                                  "Install it (Windows: <b>winget install Gyan.FFmpeg</b>) and restart the app.")
        self.ffmpeg_warn.setObjectName("warning")
        self.ffmpeg_warn.setWordWrap(True)
        self.ffmpeg_warn.setVisible(not ffmpeg_available())
        outer.addWidget(self.ffmpeg_warn)

        # url bar
        bar = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setObjectName("urlBar")
        self.url.setPlaceholderText("Paste a YouTube video or playlist link…   (or drag a link onto this window)")
        self.url.returnPressed.connect(self.fetch)
        paste = QPushButton("Paste")
        paste.clicked.connect(self._paste)
        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.setObjectName("primary")
        self.fetch_btn.clicked.connect(self.fetch)
        bar.addWidget(self.url, 1)
        bar.addWidget(paste)
        bar.addWidget(self.fetch_btn)
        outer.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        # ---------------- left column: preview + options
        left = QVBoxLayout()
        left.setSpacing(12)
        self.preview = VideoCard()
        left.addWidget(self.preview)

        self.clip_cb = QCheckBox("Download only a part of the video")
        self.clip_cb.setChecked(True)
        self.clip_cb.toggled.connect(self._toggle_clip)
        self.slider = RangeSlider()
        self.slider.rangeChanged.connect(self._slider_moved)
        self.start_in = QLineEdit()
        self.start_in.setPlaceholderText("Start  e.g. 1:30")
        self.end_in = QLineEdit()
        self.end_in.setPlaceholderText("End  e.g. 2:45")
        for w in (self.start_in, self.end_in):
            w.editingFinished.connect(self._times_typed)
            w.textChanged.connect(lambda _=None, x=w: self._mark(x, True))
        times = QHBoxLayout()
        times.addWidget(QLabel("From"))
        times.addWidget(self.start_in)
        times.addWidget(QLabel("to"))
        times.addWidget(self.end_in)
        self.len_lbl = QLabel("")
        self.len_lbl.setObjectName("muted")
        times.addWidget(self.len_lbl)
        self.range_card = card(self.clip_cb, self.slider, times, title="Time range")
        left.addWidget(self.range_card)

        self.quality = QComboBox()
        self.quality.addItems(QUALITY_PRESETS)
        self.quality.currentTextChanged.connect(self._quality_changed)
        self.vformat = QComboBox()
        self.vformat.addItems(VIDEO_CONTAINERS)
        self.aformat = QComboBox()
        self.aformat.addItems(AUDIO_FORMATS)
        self.subs_cb = QCheckBox("Subtitles")
        self.subs_cb.setToolTip("Download and embed subtitles (languages in Settings)")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.addWidget(QLabel("Quality"), 0, 0)
        grid.addWidget(self.quality, 0, 1)
        self.vlabel = QLabel("Video format")
        self.alabel = QLabel("Audio format")
        grid.addWidget(self.vlabel, 0, 2)
        grid.addWidget(self.vformat, 0, 3)
        grid.addWidget(self.alabel, 0, 2)
        grid.addWidget(self.aformat, 0, 3)
        grid.addWidget(self.subs_cb, 1, 0, 1, 2)
        self.folder_lbl = QLabel()
        self.folder_lbl.setObjectName("muted")
        self.folder_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(self.folder_lbl, 1, 2, 1, 2)
        left.addWidget(card(grid, title="Output"))

        actions = QHBoxLayout()
        self.add_btn = QPushButton("＋  Add to queue")
        self.add_btn.setToolTip("Ctrl+Enter")
        self.add_btn.clicked.connect(self.add_current)
        self.now_btn = QPushButton("⬇  Download now")
        self.now_btn.setObjectName("primary")
        self.now_btn.clicked.connect(lambda: self.add_current(front=True))
        batch = QPushButton("Add many…")
        batch.clicked.connect(self.open_batch)
        actions.addWidget(batch)
        actions.addStretch()
        actions.addWidget(self.add_btn)
        actions.addWidget(self.now_btn)
        left.addLayout(actions)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setMinimumWidth(560)
        body.addWidget(lw, 5)

        # ---------------- right column: queue + history
        self.tabs = QTabWidget()
        body.addWidget(self.tabs, 4)

        qpage = QWidget()
        ql = QVBoxLayout(qpage)
        ql.setContentsMargins(0, 8, 0, 0)
        qbar = QHBoxLayout()
        for text, slot in (("Pause all", self.pause_all), ("Resume all", self.resume_all),
                           ("Clear finished", self.clear_finished)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            qbar.addWidget(b)
        qbar.addStretch()
        open_dir = QPushButton("📂 Folder")
        open_dir.clicked.connect(lambda: self._open_path(self.settings.get("folder")))
        qbar.addWidget(open_dir)
        ql.addLayout(qbar)
        self.queue_box = QVBoxLayout()
        self.queue_box.setSpacing(8)
        self.empty = QLabel("Your queue is empty.\nFetch a video and press <b>Download now</b>.")
        self.empty.setTextFormat(Qt.RichText)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("muted")
        self.queue_box.addWidget(self.empty)
        self.queue_box.addStretch()
        qw = QWidget()
        qw.setLayout(self.queue_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(qw)
        ql.addWidget(scroll, 1)
        self.tabs.addTab(qpage, "Queue")

        hpage = QWidget()
        hl = QVBoxLayout(hpage)
        hl.setContentsMargins(0, 8, 0, 0)
        hbar = QHBoxLayout()
        self.hsearch = QLineEdit()
        self.hsearch.setPlaceholderText("Search history…")
        self.hsearch.textChanged.connect(self._refresh_history)
        again = QPushButton("Download again")
        again.clicked.connect(self._history_again)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_history)
        hbar.addWidget(self.hsearch, 1)
        hbar.addWidget(again)
        hbar.addWidget(clear)
        hl.addLayout(hbar)
        self.htable = QTableWidget(0, 4)
        self.htable.setHorizontalHeaderLabels(["When", "Title", "Range", "Result"])
        self.htable.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3):
            self.htable.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.htable.verticalHeader().setVisible(False)
        self.htable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.htable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.htable.doubleClicked.connect(self._history_open)
        hl.addWidget(self.htable, 1)
        self.tabs.addTab(hpage, "History")

        self.statusBar().showMessage("Ready")
        self._toggle_clip(True)
        self._quality_changed(self.quality.currentText())

    # ================================================================== preferences & theme
    def _load_prefs(self) -> None:
        s = self.settings
        self.quality.setCurrentText(s.get("quality"))
        self.vformat.setCurrentText(s.get("video_format"))
        self.aformat.setCurrentText(s.get("audio_format"))
        self.folder_lbl.setText(f"Saving to: {s.get('folder')}")

    def _save_prefs(self) -> None:
        self.settings.set("quality", self.quality.currentText())
        self.settings.set("video_format", self.vformat.currentText())
        self.settings.set("audio_format", self.aformat.currentText())

    def _theme_name(self) -> str:
        t = self.settings.get("theme")
        if t == "system":
            return "dark" if QApplication.palette().window().color().lightness() < 128 else "light"
        return t

    def _apply_theme(self) -> None:
        name = self._theme_name()
        QApplication.instance().setStyleSheet(stylesheet(name))
        self.slider.set_colors(track=color(name, "track"), range=color(name, "brand"),
                               handle=color(name, "surface"), text=color(name, "muted"))
        self.theme_btn.setText("☀" if name == "dark" else "🌙")

    def toggle_theme(self) -> None:
        self.settings.set("theme", "light" if self._theme_name() == "dark" else "dark")
        self._apply_theme()

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec_():
            self._apply_theme()
            self._load_prefs()
            self._pump()
            self.statusBar().showMessage("Settings saved", 3000)

    # ================================================================== fetch & preview
    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        urls = extract_urls(text)
        self.url.setText(urls[0] if urls else text.strip())
        self.fetch()

    def fetch(self) -> None:
        url = self.url.text().strip()
        if not url:
            return
        found = extract_urls(url)
        if found:
            url = found[0]
            self.url.setText(url)
        elif not url.startswith("http"):
            self.preview.set_error("That doesn't look like a link. Paste a full https:// address.")
            return
        self.info = None
        self.preview.set_loading(url)
        self.slider.set_duration(0)
        self.fetch_btn.setEnabled(False)
        self.statusBar().showMessage("Fetching video details…")
        job = InfoJob(url, self.settings.get("cookies_browser") or None)
        job.signals.video.connect(self._on_info)
        job.signals.playlist.connect(self._on_playlist)
        job.signals.failed.connect(self._on_info_failed)
        self.pool.start(job)

    def _on_info(self, info) -> None:
        self.fetch_btn.setEnabled(True)
        self.info = info
        self.preview.set_info(info)
        if info.thumbnail:
            tj = ThumbJob(info.thumbnail, info.url)
            tj.signals.done.connect(lambda key, data: self.info and key == self.info.url and self.preview.set_thumbnail(data))
            self.pool.start(tj)
        current = self.quality.currentText()
        self.quality.blockSignals(True)
        self.quality.clear()
        self.quality.addItems(info.available_qualities())
        self.quality.setCurrentText(current if current in info.available_qualities() else "best")
        self.quality.blockSignals(False)
        self._quality_changed(self.quality.currentText())
        if info.duration and not info.is_live:
            self.slider.set_duration(info.duration)
            s, e = self._typed_times()
            if s is not None and e is not None and e <= info.duration:
                self.slider.set_range(s, e)
            else:
                self.start_in.setText("0:00")
                self.end_in.setText(human_duration(info.duration))
        self.subs_cb.setEnabled(bool(info.subtitles))
        self.statusBar().showMessage("Ready: choose a range and press Download now", 5000)

    def _on_playlist(self, title: str, entries: list) -> None:
        self.fetch_btn.setEnabled(True)
        self.preview.set_error(f"Playlist: {title} ({len(entries)} videos)")
        if not entries:
            return
        r = QMessageBox.question(self, "Playlist", f"<b>{title}</b> has {len(entries)} videos.<br><br>"
                                 "Add all of them to the queue as full videos with the current quality?")
        if r == QMessageBox.Yes:
            added = 0
            for u, t in entries:
                req = self._build_request(u, None, None, title=t, silent=True)
                if req:
                    self._enqueue(req, t)
                    added += 1
            self.statusBar().showMessage(f"Added {added} videos from the playlist", 5000)

    def _on_info_failed(self, msg: str) -> None:
        self.fetch_btn.setEnabled(True)
        self.preview.set_error(msg)
        self.statusBar().showMessage("Could not fetch details. You can still type a range and download.", 6000)

    # ================================================================== range
    def _toggle_clip(self, on: bool) -> None:
        for w in (self.slider, self.start_in, self.end_in, self.len_lbl):
            w.setEnabled(on and (w is not self.slider or self.slider.duration > 0))

    def _slider_moved(self, s: float, e: float) -> None:
        self.start_in.setText(human_duration(s))
        self.end_in.setText(human_duration(e))
        self.len_lbl.setText(f"= {human_duration(e - s)}")

    def _typed_times(self):
        try:
            s = parse_timestamp(self.start_in.text()) if self.start_in.text().strip() else None
            e = parse_timestamp(self.end_in.text()) if self.end_in.text().strip() else None
            return s, e
        except ClipError:
            return None, None

    def _mark(self, w: QLineEdit, ok: bool) -> None:
        w.setProperty("invalid", "false" if ok else "true")
        w.style().unpolish(w)
        w.style().polish(w)

    def _times_typed(self) -> None:
        for w in (self.start_in, self.end_in):
            try:
                if w.text().strip():
                    parse_timestamp(w.text())
                self._mark(w, True)
            except ClipError:
                self._mark(w, False)
        s, e = self._typed_times()
        if s is not None and e is not None and e > s:
            self.len_lbl.setText(f"= {human_duration(e - s)}")
            if self.slider.duration:
                self.slider.set_range(s, e)
        elif s is not None and e is not None:
            self._mark(self.end_in, False)
            self.len_lbl.setText("end ≤ start")

    def _quality_changed(self, q: str) -> None:
        audio = q.startswith("audio-")
        self.vlabel.setVisible(not audio)
        self.vformat.setVisible(not audio)
        self.alabel.setVisible(audio)
        self.aformat.setVisible(audio)
        self.subs_cb.setVisible(not audio)

    # ================================================================== queue
    def _build_request(self, url, start, end, title=None, silent=False) -> ClipRequest | None:
        s = self.settings
        try:
            folder = s.get("folder")
            os.makedirs(folder, exist_ok=True)
            return ClipRequest(
                url, start, end,
                quality=self.quality.currentText(),
                output_dir=folder,
                video_format=self.vformat.currentText(),
                audio_format=self.aformat.currentText(),
                subtitles=self._subtitle_langs(),
                embed_metadata=s.get("embed_metadata"),
                embed_thumbnail=s.get("embed_thumbnail"),
                rate_limit=s.get("rate_limit") or None,
                cookies_browser=s.get("cookies_browser") or None,
                filename_template=s.get("filename_template"),
                title=title,
            )
        except (ClipError, OSError) as exc:
            if not silent:
                QMessageBox.warning(self, "Can't add this download", str(exc))
            return None

    def _subtitle_langs(self) -> tuple:
        if self.subs_cb.isChecked() and self.subs_cb.isEnabled():
            return tuple(self.settings.get("subtitle_langs").split(","))
        return ()

    def add_current(self, front: bool = False) -> None:
        url = self.url.text().strip()
        if not url:
            self.url.setFocus()
            self.statusBar().showMessage("Paste a link first", 3000)
            return
        start = end = None
        if self.clip_cb.isChecked():
            s, e = self._typed_times()
            full = self.slider.duration and s == 0 and e is not None and abs(e - self.slider.duration) < 1
            if (s is None) != (e is None) or (s is None and (self.start_in.text() or self.end_in.text())):
                QMessageBox.warning(self, "Check the times", "Enter both a start and an end time (e.g. 1:30 and 2:45).")
                return
            if s is not None and e <= s:
                QMessageBox.warning(self, "Check the times", "The end time must be after the start time.")
                return
            if s is not None and not full:
                if self.slider.duration and e > self.slider.duration + 1:
                    QMessageBox.warning(self, "Check the times",
                                        f"The video is only {human_duration(self.slider.duration)} long.")
                    return
                start, end = s, e
        title = self.info.title if self.info and self.info.url and url in (self.info.url, self.url.text().strip()) else None
        req = self._build_request(url, start, end, title=title)
        if req:
            self._save_prefs()
            self._enqueue(req, title or url, front=front)
            self.tabs.setCurrentIndex(0)

    def open_batch(self) -> None:
        dlg = BatchDialog(self)
        if not dlg.exec_():
            return
        parsed = parse_batch(dlg.box.toPlainText(), self.quality.currentText(), self.settings.get("folder"))
        bad = [p for p in parsed if p.error]
        n = 0
        for p in parsed:
            if p.request:
                req = self._build_request(p.request.url, p.request.start, p.request.end, silent=True)
                if req:
                    self._enqueue(req, req.url)
                    n += 1
        msg = f"Added {n} job(s)."
        if bad:
            msg += "\n\nSkipped:\n" + "\n".join(f"Line {b.line_no}: {b.error}" for b in bad[:10])
            QMessageBox.information(self, "Batch", msg)
        self.statusBar().showMessage(f"Added {n} job(s)", 4000)

    def _enqueue(self, req: ClipRequest, title: str, front: bool = False) -> None:
        jid = self.next_id
        self.next_id += 1
        sub = f"{time_range_text(req)}  ·  {req.quality}  ·  {req.audio_format if req.is_audio else req.video_format}"
        if req.subtitles:
            sub += "  ·  CC"
        c = JobCard(jid, title, sub)
        c.pauseClicked.connect(self.pause_job)
        c.resumeClicked.connect(self.resume_job)
        c.cancelClicked.connect(self.cancel_job)
        c.retryClicked.connect(self.resume_job)
        c.openClicked.connect(self.open_job)
        c.removeClicked.connect(self.remove_job)
        self.empty.hide()
        self.queue_box.insertWidget(0 if front else self.queue_box.count() - 1, c)
        self.jobs[jid] = Job(jid, req, c, title)
        if front:
            self.pending.insert(0, jid)
        else:
            self.pending.append(jid)
        self._pump()

    def _active(self) -> int:
        return sum(1 for j in self.jobs.values() if j.worker is not None)

    def _pump(self) -> None:
        limit = self.settings.get("parallel")
        while self.pending and self._active() < limit:
            jid = self.pending.pop(0)
            job = self.jobs.get(jid)
            if not job or job.state != "queued":
                continue
            w = DownloadJob(jid, job.req)
            w.signals.progress.connect(self._on_progress)
            w.signals.title.connect(self._on_title)
            w.signals.file.connect(self._on_file)
            w.signals.finished.connect(self._on_finished)
            job.worker = w
            job.state = "starting"
            job.card.set_state("starting", "Starting…")
            self.pool.start(w)
        self._update_status()

    def _on_progress(self, jid: int, pct: float, status: str, speed: str, eta: str) -> None:
        job = self.jobs.get(jid)
        if not job or job.worker is None:
            return
        if status == "processing":
            job.state = "processing"
            job.card.set_state("processing", "Processing with ffmpeg…")
            job.card.bar.setValue(1000)
            return
        if status == "downloading":
            if job.state != "downloading":
                job.state = "downloading"
                job.card.set_state("downloading", "Downloading…")
            bits = [f"{pct:.0f}%"] + [b for b in (speed, f"ETA {eta}" if eta else "") if b]
            job.card.set_progress(pct, "  ·  ".join(bits))

    def _on_title(self, jid: int, title: str) -> None:
        job = self.jobs.get(jid)
        if job:
            job.title = title
            job.card.title.setText(title)

    def _on_file(self, jid: int, path: str) -> None:
        job = self.jobs.get(jid)
        if job:
            job.file = path

    def _on_finished(self, jid: int, outcome: str, message: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            self._pump()
            return
        job.worker = None
        job.state = outcome
        text = {"done": "✓ Saved" + (f": {Path(job.file).name}" if job.file else ""),
                "paused": "Paused · press ▶ to resume",
                "cancelled": "Cancelled"}.get(outcome, f"✕ {message}")
        job.card.set_state(outcome, text)
        if outcome in ("done", "failed"):
            self.history.add(title=job.title, url=job.req.url, range=time_range_text(job.req), quality=job.req.quality,
                             result="done" if outcome == "done" else message, folder=job.req.output_dir,
                             file=job.file or "", start=job.req.start, end=job.req.end)
            self._refresh_history()
            if outcome == "done":
                self.session_done += 1
            else:
                self.session_failed += 1
        self._pump()
        if self._active() == 0 and not self.pending and outcome in ("done", "failed"):
            self._notify_finished()

    def pause_job(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if not job:
            return
        if job.worker:
            job.worker.pause.set()
            job.card.status.setText("Pausing…")
        elif job.state == "queued":
            job.state = "paused"
            job.card.set_state("paused", "Paused")
            if jid in self.pending:
                self.pending.remove(jid)
        self._update_status()

    def resume_job(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if not job or job.worker:
            return
        job.state = "queued"
        job.card.set_state("queued", "Queued")
        self.pending.append(jid)
        self._pump()

    def cancel_job(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if not job:
            return
        if job.worker:
            job.worker.cancel.set()
            job.card.status.setText("Cancelling…")
        else:
            job.state = "cancelled"
            job.card.set_state("cancelled", "Cancelled")
            if jid in self.pending:
                self.pending.remove(jid)
        self._update_status()

    def remove_job(self, jid: int) -> None:
        job = self.jobs.pop(jid, None)
        if job:
            job.card.setParent(None)
            job.card.deleteLater()
        self.empty.setVisible(not self.jobs)

    def open_job(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if job:
            self._open_path(job.file or job.req.output_dir, select=bool(job.file))

    def pause_all(self) -> None:
        for jid, j in list(self.jobs.items()):
            if j.state in ("queued", "starting", "downloading"):
                self.pause_job(jid)

    def resume_all(self) -> None:
        for jid, j in list(self.jobs.items()):
            if j.state == "paused":
                self.resume_job(jid)

    def clear_finished(self) -> None:
        for jid, j in list(self.jobs.items()):
            if j.state in ("done", "cancelled", "failed"):
                self.remove_job(jid)

    # ================================================================== history
    def _refresh_history(self, *_):
        q = self.hsearch.text().lower().strip() if hasattr(self, "hsearch") else ""
        items = [h for h in self.history.load() if not q or q in (h.get("title", "") + h.get("url", "")).lower()]
        self._hitems = items
        self.htable.setRowCount(len(items))
        for r, h in enumerate(items):
            res = h.get("result", "")
            vals = [h.get("time", ""), h.get("title") or h.get("url", ""), h.get("range", ""),
                    "✓ done" if res == "done" else f"✕ {res}"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 1:
                    it.setToolTip(h.get("url", ""))
                self.htable.setItem(r, c, it)

    def _selected_history(self):
        rows = {i.row() for i in self.htable.selectedIndexes()}
        return [self._hitems[r] for r in sorted(rows) if r < len(self._hitems)]

    def _history_again(self) -> None:
        for h in self._selected_history():
            req = self._build_request(h["url"], h.get("start"), h.get("end"), title=h.get("title"), silent=True)
            if req:
                self._enqueue(req, h.get("title") or h["url"])
        self.tabs.setCurrentIndex(0)

    def _history_open(self, index) -> None:
        h = self._hitems[index.row()]
        if h.get("file") and os.path.exists(h["file"]):
            self._open_path(h["file"], select=True)
        elif h.get("folder"):
            self._open_path(h["folder"])

    def _clear_history(self) -> None:
        ask = QMessageBox.question(self, "Clear history", "Remove all history entries? Your files are not deleted.")
        if ask == QMessageBox.Yes:
            self.history.clear()
            self._refresh_history()

    # ================================================================== misc
    def _open_path(self, path: str, select: bool = False) -> None:
        if not path:
            return
        if select and sys.platform.startswith("win") and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])  # noqa: S603,S607
            return
        target = path if os.path.isdir(path) else os.path.dirname(path)
        os.makedirs(target, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _update_status(self) -> None:
        active = self._active()
        queued = sum(1 for j in self.jobs.values() if j.state == "queued")
        parts = [f"{active} downloading", f"{queued} queued", f"{self.session_done} done this session"]
        if self.session_failed:
            parts.append(f"{self.session_failed} failed")
        parts.append("ffmpeg ✓" if ffmpeg_available() else "ffmpeg missing")
        self.statusBar().showMessage("   ·   ".join(parts))

    def _setup_tray(self) -> None:
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull()
                                        else self.style().standardIcon(QStyle.SP_ArrowDown), self)
            self.tray.setToolTip("Smart Clip Downloader")
            self.tray.activated.connect(lambda *_: (self.showNormal(), self.activateWindow()))
            self.tray.show()

    def _notify_finished(self) -> None:
        msg = f"{self.session_done} download(s) finished"
        if self.session_failed:
            msg += f", {self.session_failed} failed"
        self.statusBar().showMessage(msg, 8000)
        if self.tray and self.settings.get("notify") and not self.isActiveWindow():
            self.tray.showMessage("Smart Clip Downloader", msg, QSystemTrayIcon.Information, 5000)

    def _on_clipboard(self) -> None:
        if not self.settings.get("clipboard_watch"):
            return
        urls = extract_urls(QApplication.clipboard().text())
        if urls and urls[0] != self.last_clip:
            self.last_clip = urls[0]
            if urls[0] != self.url.text().strip():
                self.url.setText(urls[0])
                self.fetch()
                self.statusBar().showMessage("Link picked up from the clipboard", 4000)

    def dragEnterEvent(self, e):  # noqa: N802 - Qt API
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        text = e.mimeData().text() or " ".join(u.toString() for u in e.mimeData().urls())
        urls = extract_urls(text)
        if not urls:
            self.statusBar().showMessage("No YouTube link in what you dropped", 4000)
            return
        if len(urls) == 1 or is_playlist_url(urls[0]):
            self.url.setText(urls[0])
            self.fetch()
        else:
            for u in urls:
                req = self._build_request(u, None, None, silent=True)
                if req:
                    self._enqueue(req, u)
            self.statusBar().showMessage(f"Added {len(urls)} links to the queue", 4000)

    def closeEvent(self, event):  # noqa: N802
        running = [j for j in self.jobs.values() if j.worker]
        if running and QMessageBox.question(
                self, "Downloads in progress",
                f"{len(running)} download(s) are running. Pause them and quit? "
                "Full videos resume next time you add them.") != QMessageBox.Yes:
            event.ignore()
            return
        for j in running:
            j.worker.pause.set()
        self.pool.waitForDone(4000)
        if self.tray:
            self.tray.hide()
        super().closeEvent(event)


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Smart Clip Downloader")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        win.url.setText(sys.argv[1])
        QTimer.singleShot(200, win.fetch)
    return app.exec_()


__all__ = ["MainWindow", "main", "format_timestamp"]
