"""Background work: video info, thumbnails and downloads.

Workers never touch widgets. They talk to the GUI through Qt signals, which Qt
delivers on the GUI thread.
"""

from __future__ import annotations

import threading
import urllib.request

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal

from .core import ClipRequest, build_ydl_options, parse_info, playlist_entries, progress_from_hook


class _SilentLogger:
    def debug(self, msg):
        pass

    warning = info = error = debug


def _clean_error(exc: Exception) -> str:
    msg = str(exc).replace("ERROR: ", "").strip()
    msg = msg.split("; please report this issue")[0]
    if "Sign in to confirm your age" in msg or "age-restricted" in msg:
        return "Age-restricted video. Choose a browser under Settings → Cookies and try again."
    if "Private video" in msg:
        return "This video is private."
    if "Video unavailable" in msg:
        return "Video unavailable (removed or blocked in your region)."
    if "ffmpeg" in msg.lower() and "not found" in msg.lower():
        return "ffmpeg is not installed. See README → Installation."
    if any(k in msg for k in ("Unable to download", "Unable to connect", "getaddrinfo", "timed out",
                              "ProxyError", "Connection refused", "Network is unreachable")):
        return "Network error: check your internet connection."
    return msg[:300]


# --------------------------------------------------------------------------- info
class InfoSignals(QObject):
    video = pyqtSignal(object)          # VideoInfo
    playlist = pyqtSignal(str, list)    # title, [(url, title)]
    failed = pyqtSignal(str)


class InfoJob(QRunnable):
    def __init__(self, url: str, cookies_browser: str | None = None):
        super().__init__()
        self.url = url
        self.cookies_browser = cookies_browser
        self.signals = InfoSignals()

    def run(self) -> None:
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "logger": _SilentLogger(),
                "extract_flat": "in_playlist", "noplaylist": False}
        if self.cookies_browser:
            opts["cookiesfrombrowser"] = (self.cookies_browser,)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
            if info.get("_type") == "playlist":
                self.signals.playlist.emit(info.get("title") or "Playlist", playlist_entries(info))
            else:
                self.signals.video.emit(parse_info(info, self.url))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(_clean_error(exc))


# --------------------------------------------------------------------------- thumbnail
class ThumbSignals(QObject):
    done = pyqtSignal(str, bytes)


class ThumbJob(QRunnable):
    def __init__(self, url: str, key: str):
        super().__init__()
        self.url, self.key = url, key
        self.signals = ThumbSignals()

    def run(self) -> None:
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - https thumbnail from yt-dlp
                self.signals.done.emit(self.key, r.read(2_000_000))
        except Exception:  # noqa: BLE001 - a missing thumbnail is not an error
            pass


# --------------------------------------------------------------------------- download
class JobSignals(QObject):
    progress = pyqtSignal(int, float, str, str, str)  # job id, percent, status, speed, eta
    title = pyqtSignal(int, str)
    file = pyqtSignal(int, str)
    finished = pyqtSignal(int, str, str)  # job id, outcome (done/paused/cancelled/failed), message


class DownloadJob(QRunnable):
    """One download. ``pause`` and ``cancel`` are threading.Events owned by the queue."""

    def __init__(self, job_id: int, req: ClipRequest):
        super().__init__()
        self.job_id, self.req = job_id, req
        self.pause = threading.Event()
        self.cancel = threading.Event()
        self.signals = JobSignals()
        self._title_sent = False

    def _check_stop(self) -> None:
        if self.pause.is_set() or self.cancel.is_set():
            from yt_dlp.utils import DownloadCancelled

            raise DownloadCancelled("stopped")

    def _hook(self, d: dict) -> None:
        self._check_stop()
        info = d.get("info_dict") or {}
        if not self._title_sent and info.get("title"):
            self.signals.title.emit(self.job_id, info["title"])
            self._title_sent = True
        p = progress_from_hook(d)
        self.signals.progress.emit(self.job_id, p.percent, p.status, p.speed, p.eta)

    def _pp_hook(self, d: dict) -> None:
        if d.get("status") == "started":
            self.signals.progress.emit(self.job_id, 100.0, "processing", "", "")
        if d.get("status") == "finished":
            path = (d.get("info_dict") or {}).get("filepath")
            if path:
                self.signals.file.emit(self.job_id, path)

    def run(self) -> None:
        import yt_dlp

        if self.cancel.is_set():
            self.signals.finished.emit(self.job_id, "cancelled", "Cancelled")
            return
        try:
            opts = build_ydl_options(self.req, progress_hook=self._hook)
            opts["postprocessor_hooks"] = [self._pp_hook]
            opts["logger"] = _SilentLogger()
            self.signals.progress.emit(self.job_id, 0.0, "starting", "", "")
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self.req.url])
            self.signals.finished.emit(self.job_id, "done", "Done")
        except Exception as exc:  # noqa: BLE001
            if self.cancel.is_set():
                self.signals.finished.emit(self.job_id, "cancelled", "Cancelled")
            elif self.pause.is_set():
                self.signals.finished.emit(self.job_id, "paused", "Paused")
            else:
                self.signals.finished.emit(self.job_id, "failed", _clean_error(exc))
