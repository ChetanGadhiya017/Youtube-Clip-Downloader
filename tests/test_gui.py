"""GUI behaviour with a fake downloader (no network). Runs headless."""

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5")
pytest.importorskip("pytestqt")

from PyQt5.QtCore import QSettings  # noqa: E402

from smart_clip_downloader import gui, workers  # noqa: E402
from smart_clip_downloader.core import VideoInfo  # noqa: E402
from smart_clip_downloader.history import History  # noqa: E402
from smart_clip_downloader.settings import AppSettings  # noqa: E402

RELEASE = threading.Event()


def fake_run(self):
    """Emit progress until RELEASE is set; honour pause/cancel like the real job."""
    self.signals.progress.emit(self.job_id, 0.0, "starting", "", "")
    self.signals.title.emit(self.job_id, f"Video {self.job_id}")
    pct = 0.0
    while not RELEASE.is_set():
        if self.cancel.is_set():
            self.signals.finished.emit(self.job_id, "cancelled", "Cancelled")
            return
        if self.pause.is_set():
            self.signals.finished.emit(self.job_id, "paused", "Paused")
            return
        pct = min(99.0, pct + 5)
        self.signals.progress.emit(self.job_id, pct, "downloading", "1.0 MB/s", "00:00:05")
        time.sleep(0.02)
    if "fail" in self.req.url:
        self.signals.finished.emit(self.job_id, "failed", "Video unavailable")
        return
    self.signals.file.emit(self.job_id, os.path.join(self.req.output_dir, f"video{self.job_id}.mp4"))
    self.signals.finished.emit(self.job_id, "done", "Done")


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    RELEASE.clear()
    monkeypatch.setattr(workers.DownloadJob, "run", fake_run)
    monkeypatch.setattr(gui.QMessageBox, "question", staticmethod(lambda *a, **k: gui.QMessageBox.Yes))
    monkeypatch.setattr(gui.QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    s = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    s.set("folder", str(tmp_path / "out"))
    s.set("parallel", 2)
    w = gui.MainWindow(s, History(tmp_path / "h.json"))
    qtbot.addWidget(w)
    yield w
    RELEASE.set()
    w.pool.waitForDone(2000)


def states(w):
    return [j.state for j in w.jobs.values()]


def test_add_clip_and_complete(win, qtbot):
    win.url.setText("https://youtu.be/AAAAAAAAAAA")
    win._on_info(VideoInfo(url="https://youtu.be/AAAAAAAAAAA", title="Demo", duration=600, heights=[720]))
    assert win.slider.duration == 600 and win.quality.findText("1080p") == -1
    win.start_in.setText("1:00")
    win.end_in.setText("1:30")
    win.add_current()
    job = next(iter(win.jobs.values()))
    assert job.req.start == 60 and job.req.end == 90
    qtbot.waitUntil(lambda: states(win) == ["downloading"], timeout=3000)
    RELEASE.set()
    qtbot.waitUntil(lambda: states(win) == ["done"], timeout=3000)
    assert job.file.endswith(".mp4")
    assert win.htable.rowCount() == 1 and win.session_done == 1


def test_full_range_means_full_video(win):
    win.url.setText("https://youtu.be/AAAAAAAAAAA")
    win._on_info(VideoInfo(url="https://youtu.be/AAAAAAAAAAA", title="Demo", duration=300))
    win.add_current()  # slider defaults to 0 → end
    assert not next(iter(win.jobs.values())).req.is_clip


def test_invalid_range_is_rejected(win):
    win.url.setText("https://youtu.be/AAAAAAAAAAA")
    win.start_in.setText("2:00")
    win.end_in.setText("1:00")
    win.add_current()
    assert not win.jobs


def test_parallel_limit_and_queue(win, qtbot):
    for i in range(4):
        req = win._build_request(f"https://youtu.be/{i:011d}", None, None)
        win._enqueue(req, f"v{i}")
    qtbot.waitUntil(lambda: sorted(states(win)).count("downloading") == 2, timeout=3000)
    assert states(win).count("queued") == 2


def test_pause_resume_cancel(win, qtbot):
    req = win._build_request("https://youtu.be/AAAAAAAAAAA", None, None)
    win._enqueue(req, "v")
    jid = next(iter(win.jobs))
    qtbot.waitUntil(lambda: win.jobs[jid].state == "downloading", timeout=3000)
    win.pause_job(jid)
    qtbot.waitUntil(lambda: win.jobs[jid].state == "paused", timeout=3000)
    win.resume_job(jid)
    qtbot.waitUntil(lambda: win.jobs[jid].state == "downloading", timeout=3000)
    win.cancel_job(jid)
    qtbot.waitUntil(lambda: win.jobs[jid].state == "cancelled", timeout=3000)
    win.clear_finished()
    assert not win.jobs and win.empty.isVisibleTo(win)


def test_failure_is_recorded(win, qtbot):
    win._enqueue(win._build_request("https://youtu.be/fail0000000", None, None), "bad")
    RELEASE.set()
    qtbot.waitUntil(lambda: states(win) == ["failed"], timeout=3000)
    assert "Video unavailable" in win.history.load()[0]["result"]


def test_playlist_adds_all(win):
    win._on_playlist("My list", [("https://youtu.be/AAAAAAAAAAA", "A"), ("https://youtu.be/BBBBBBBBBBB", "B")])
    assert len(win.jobs) == 2


def test_theme_toggle(win):
    before = win._theme_name()
    win.toggle_theme()
    assert win._theme_name() != before
