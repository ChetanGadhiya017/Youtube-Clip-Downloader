"""PyQt5 user interface.

Downloads run in a QThreadPool (one QRunnable per job). Workers never touch
widgets directly — they emit Qt signals, which Qt delivers on the GUI thread.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .core import (
    QUALITY_PRESETS,
    ClipError,
    ClipRequest,
    build_ydl_options,
    ffmpeg_available,
    format_timestamp,
    parse_batch,
    parse_timestamp,
    progress_from_hook,
)
from .history import History

ICONS = Path(__file__).parent / "assets" / "icons"
COLS = ["Video", "Range", "Status", "Progress", "Speed", "ETA"]


def icon(name: str) -> QIcon:
    return QIcon(str(ICONS / f"{name}.png"))


class WorkerSignals(QObject):
    progress = pyqtSignal(int, float, str, str, str)  # row, percent, status, speed, eta
    title = pyqtSignal(int, str)
    done = pyqtSignal(int, bool, str)  # row, ok, message


class _SilentLogger:
    def debug(self, msg):
        pass

    warning = info = error = debug


class DownloadJob(QRunnable):
    def __init__(self, row: int, req: ClipRequest, cancel: threading.Event):
        super().__init__()
        self.row, self.req, self.cancel = row, req, cancel
        self.signals = WorkerSignals()

    def _hook(self, d: dict) -> None:
        if self.cancel.is_set():
            from yt_dlp.utils import DownloadCancelled

            raise DownloadCancelled("Cancelled by user")
        info = d.get("info_dict") or {}
        if info.get("title"):
            self.signals.title.emit(self.row, info["title"])
        p = progress_from_hook(d)
        self.signals.progress.emit(self.row, p.percent, p.status, p.speed, p.eta)

    def run(self) -> None:
        import yt_dlp

        if self.cancel.is_set():
            self.signals.done.emit(self.row, False, "Cancelled")
            return
        try:
            opts = build_ydl_options(self.req, progress_hook=self._hook)
            opts["logger"] = _SilentLogger()  # errors are shown in the UI instead
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self.req.url])
            self.signals.done.emit(self.row, True, "Done")
        except Exception as exc:  # noqa: BLE001 - surface any yt-dlp error to the user
            msg = "Cancelled" if self.cancel.is_set() else str(exc).replace("ERROR: ", "")
            self.signals.done.emit(self.row, False, msg)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Smart Clip Downloader v{__version__}")
        self.setWindowIcon(icon("download"))
        self.resize(980, 680)

        self.settings = QSettings("ChetanGadhiya", "SmartClipDownloader")
        self.history = History()
        self.pool = QThreadPool(self)
        self.cancel_event = threading.Event()
        self.active = 0
        self.requests: dict[int, ClipRequest] = {}

        tabs = QTabWidget()
        tabs.addTab(self._build_download_tab(), icon("download"), "Download")
        tabs.addTab(self._build_history_tab(), "History")
        root = QVBoxLayout(self)
        root.addWidget(tabs)

        if not ffmpeg_available():
            self.log("⚠️ ffmpeg was not found on PATH. Clip cutting and audio extraction "
                     "need it — see README → Installation.")
        self._refresh_history()

    # ---------- UI construction ----------
    def _build_download_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Quick add
        single = QGroupBox("Add a clip")
        form = QFormLayout(single)
        self.url_input = QLineEdit(placeholderText="https://www.youtube.com/watch?v=…")
        self.start_input = QLineEdit(placeholderText="e.g. 1:30  (blank = whole video)")
        self.end_input = QLineEdit(placeholderText="e.g. 2:45")
        times = QHBoxLayout()
        times.addWidget(QLabel("Start"))
        times.addWidget(self.start_input)
        times.addWidget(QLabel("End"))
        times.addWidget(self.end_input)
        add_btn = QPushButton("Add to batch ↓")
        add_btn.clicked.connect(self.add_single)
        times.addWidget(add_btn)
        form.addRow("YouTube URL", self.url_input)
        form.addRow("Time range", times)
        layout.addWidget(single)

        # Batch
        batch = QGroupBox("Batch — one job per line:  URL   or   URL START END")
        bl = QVBoxLayout(batch)
        self.batch_box = QPlainTextEdit()
        self.batch_box.setPlaceholderText(
            "https://youtu.be/abc123 0:30 1:15\nhttps://youtu.be/xyz789 1:02:00-1:03:30\nhttps://youtu.be/full_video"
        )
        self.batch_box.setFixedHeight(90)
        bl.addWidget(self.batch_box)
        layout.addWidget(batch)

        # Options
        opts = QHBoxLayout()
        self.quality_box = QComboBox()
        self.quality_box.addItems(QUALITY_PRESETS)
        self.quality_box.setCurrentText(self.settings.value("quality", "1080p"))
        self.folder_input = QLineEdit(self.settings.value("folder", str(Path.home() / "Downloads")))
        browse = QPushButton(icon("folder"), "Browse")
        browse.clicked.connect(self.browse_folder)
        self.parallel_spin = QSpinBox(minimum=1, maximum=5)
        self.parallel_spin.setValue(int(self.settings.value("parallel", 2)))
        opts.addWidget(QLabel("Quality"))
        opts.addWidget(self.quality_box)
        opts.addWidget(QLabel("Save to"))
        opts.addWidget(self.folder_input, 1)
        opts.addWidget(browse)
        opts.addWidget(QLabel("Parallel"))
        opts.addWidget(self.parallel_spin)
        layout.addLayout(opts)

        # Actions
        actions = QHBoxLayout()
        self.start_btn = QPushButton(icon("download"), "Start downloads")
        self.start_btn.clicked.connect(self.start_downloads)
        self.cancel_btn = QPushButton(icon("pause"), "Cancel all")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_all)
        open_btn = QPushButton(icon("folder"), "Open folder")
        open_btn.clicked.connect(self.open_folder)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.cancel_btn)
        actions.addStretch()
        actions.addWidget(open_btn)
        layout.addLayout(actions)

        # Queue
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 4, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(3, 160)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        self.log_box = QPlainTextEdit(readOnly=True)
        self.log_box.setFixedHeight(90)
        layout.addWidget(self.log_box)
        return tab

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Time", "Title / URL", "Range", "Quality", "Result"])
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        clear = QPushButton("Clear history")
        clear.clicked.connect(self._clear_history)
        layout.addWidget(self.history_table)
        layout.addWidget(clear, alignment=Qt.AlignRight)
        return tab

    # ---------- helpers ----------
    def log(self, text: str) -> None:
        self.log_box.appendPlainText(text)

    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select download folder", self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)

    def open_folder(self) -> None:
        folder = self.folder_input.text()
        if not os.path.isdir(folder):
            return
        if sys.platform.startswith("win"):
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])

    def add_single(self) -> None:
        url = self.url_input.text().strip()
        start, end = self.start_input.text().strip(), self.end_input.text().strip()
        try:
            if start or end:
                ClipRequest(url, parse_timestamp(start), parse_timestamp(end))
            else:
                ClipRequest(url)
        except ClipError as exc:
            QMessageBox.warning(self, "Invalid clip", str(exc))
            return
        line = " ".join(x for x in (url, start, end) if x)
        self.batch_box.appendPlainText(line)
        for w in (self.url_input, self.start_input, self.end_input):
            w.clear()

    def _set_cell(self, row: int, col: int, text: str) -> None:
        self.table.setItem(row, col, QTableWidgetItem(text))

    # ---------- download flow ----------
    def start_downloads(self) -> None:
        folder = self.folder_input.text().strip()
        if not folder:
            QMessageBox.warning(self, "No folder", "Choose a folder to save downloads.")
            return
        os.makedirs(folder, exist_ok=True)

        quality = self.quality_box.currentText()
        parsed = parse_batch(self.batch_box.toPlainText(), quality, folder)
        if self.url_input.text().strip():  # allow one-off use without the batch box
            self.add_single()
            parsed = parse_batch(self.batch_box.toPlainText(), quality, folder)

        errors = [p for p in parsed if p.error]
        jobs = [p.request for p in parsed if p.request]
        for e in errors:
            self.log(f"⚠️ Line {e.line_no}: {e.error}  →  {e.raw}")
        if not jobs:
            self.log("Nothing to download. Add a URL above.")
            return

        self.settings.setValue("folder", folder)
        self.settings.setValue("quality", quality)
        self.settings.setValue("parallel", self.parallel_spin.value())

        self.cancel_event = threading.Event()
        self.pool.setMaxThreadCount(self.parallel_spin.value())
        self.table.setRowCount(0)
        self.requests.clear()

        for req in jobs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.requests[row] = req
            self._set_cell(row, 0, req.url)
            rng = f"{format_timestamp(req.start)} → {format_timestamp(req.end)}" if req.is_clip else "full video"
            self._set_cell(row, 1, rng)
            self._set_cell(row, 2, "queued")
            bar = QProgressBar()
            bar.setValue(0)
            self.table.setCellWidget(row, 3, bar)

            job = DownloadJob(row, req, self.cancel_event)
            job.signals.progress.connect(self.on_progress)
            job.signals.title.connect(lambda r, t: self._set_cell(r, 0, t))
            job.signals.done.connect(self.on_done)
            self.pool.start(job)

        self.active = len(jobs)
        self.batch_box.clear()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log(f"🔽 Started {len(jobs)} job(s), {self.parallel_spin.value()} at a time.")

    def cancel_all(self) -> None:
        self.cancel_event.set()
        self.log("⏹ Cancelling…")

    def on_progress(self, row: int, percent: float, status: str, speed: str, eta: str) -> None:
        bar = self.table.cellWidget(row, 3)
        if bar:
            bar.setValue(int(percent))
        self._set_cell(row, 2, status)
        self._set_cell(row, 4, speed)
        self._set_cell(row, 5, eta)

    def on_done(self, row: int, ok: bool, message: str) -> None:
        bar = self.table.cellWidget(row, 3)
        if bar and ok:
            bar.setValue(100)
        short = message.split(";")[0].split(" (caused by")[0][:90]
        self._set_cell(row, 2, "✅ done" if ok else f"❌ {short}")
        if not ok:
            self.log(f"❌ Job {row + 1}: {message}")
        self._set_cell(row, 4, "")
        self._set_cell(row, 5, "")

        req = self.requests.get(row)
        title_item = self.table.item(row, 0)
        if req:
            self.history.add(
                title=title_item.text() if title_item else req.url,
                url=req.url,
                range=self.table.item(row, 1).text(),
                quality=req.quality,
                result="done" if ok else message,
                folder=req.output_dir,
            )
        self.active -= 1
        if self.active <= 0:
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.log("All jobs finished.")
            self._refresh_history()

    def _refresh_history(self) -> None:
        items = self.history.load()
        self.history_table.setRowCount(len(items))
        for r, h in enumerate(items):
            for c, key in enumerate(["time", "title", "range", "quality", "result"]):
                self.history_table.setItem(r, c, QTableWidgetItem(str(h.get(key, ""))))

    def _clear_history(self) -> None:
        self.history.clear()
        self._refresh_history()

    def closeEvent(self, event):  # Qt override
        self.cancel_event.set()
        self.pool.waitForDone(3000)
        super().closeEvent(event)


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    return app.exec_()
