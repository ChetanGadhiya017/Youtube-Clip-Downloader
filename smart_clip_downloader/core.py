"""Pure, GUI-independent logic: time parsing, quality presets and yt-dlp options.

Everything here is unit-tested and can be reused from a CLI or another UI.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Callable, Optional

VIDEO_QUALITIES = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "4320p"]
AUDIO_QUALITIES = ["audio-64k", "audio-128k", "audio-192k", "audio-320k"]
QUALITY_PRESETS = ["best"] + VIDEO_QUALITIES + AUDIO_QUALITIES

_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)\s*$")


class ClipError(ValueError):
    """Raised for invalid user input (bad time format, empty URL, ...)."""


def parse_timestamp(value: str) -> float:
    """Convert ``SS``, ``MM:SS`` or ``HH:MM:SS`` (fractions allowed) to seconds.

    >>> parse_timestamp("1:02:03")
    3723.0
    >>> parse_timestamp("90")
    90.0
    """
    if value is None or not str(value).strip():
        raise ClipError("Time is empty")

    parts = str(value).strip().split(":")
    if len(parts) > 3 or not _TIME_RE.match(str(value)):
        raise ClipError(f"Invalid time '{value}'. Use HH:MM:SS, MM:SS or seconds.")

    try:
        numbers = [float(p) for p in parts]
    except ValueError as exc:  # pragma: no cover - regex guards this
        raise ClipError(f"Invalid time '{value}'") from exc

    *head, seconds = numbers
    if any(n < 0 for n in numbers):
        raise ClipError("Time cannot be negative")
    if head and seconds >= 60:
        raise ClipError(f"Seconds must be below 60 in '{value}'")
    if len(head) == 2 and head[1] >= 60:
        raise ClipError(f"Minutes must be below 60 in '{value}'")

    total = 0.0
    for n in head:
        total = total * 60 + n
    return total * 60 + seconds if head else seconds


def format_timestamp(seconds: float) -> str:
    """Seconds -> ``HH:MM:SS`` (used in file names and logs)."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class ClipRequest:
    """One clip to download. ``start``/``end`` of ``None`` mean whole video."""

    url: str
    start: Optional[float] = None
    end: Optional[float] = None
    quality: str = "best"
    output_dir: str = "."

    def __post_init__(self) -> None:
        self.url = (self.url or "").strip()
        if not self.url:
            raise ClipError("URL is empty")
        if not re.match(r"^https?://", self.url):
            raise ClipError(f"Not a valid URL: '{self.url}'")
        if self.quality not in QUALITY_PRESETS:
            raise ClipError(f"Unknown quality '{self.quality}'")
        if (self.start is None) != (self.end is None):
            raise ClipError("Give both start and end time, or neither for the full video")
        if self.start is not None and self.end <= self.start:
            raise ClipError("End time must be after start time")

    @property
    def is_clip(self) -> bool:
        return self.start is not None

    @property
    def is_audio(self) -> bool:
        return self.quality.startswith("audio-")


@dataclass
class ParsedLine:
    request: Optional[ClipRequest] = None
    error: Optional[str] = None
    line_no: int = 0
    raw: str = ""


def parse_batch(text: str, quality: str, output_dir: str) -> list[ParsedLine]:
    """Parse the batch box. One job per line::

        URL                          -> full video
        URL  START  END              -> clip (times as HH:MM:SS / MM:SS / seconds)
        URL  START-END               -> same, dash-separated

    Blank lines and lines starting with ``#`` are ignored.
    """
    results: list[ParsedLine] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) == 2 and "-" in tokens[1]:
            tokens = [tokens[0], *tokens[1].split("-", 1)]
        try:
            if len(tokens) == 1:
                req = ClipRequest(tokens[0], quality=quality, output_dir=output_dir)
            elif len(tokens) == 3:
                req = ClipRequest(
                    tokens[0],
                    parse_timestamp(tokens[1]),
                    parse_timestamp(tokens[2]),
                    quality=quality,
                    output_dir=output_dir,
                )
            else:
                raise ClipError("Expected 'URL' or 'URL START END'")
            results.append(ParsedLine(request=req, line_no=i, raw=line))
        except ClipError as exc:
            results.append(ParsedLine(error=str(exc), line_no=i, raw=line))
    return results


def format_selector(quality: str) -> str:
    """yt-dlp format string for a preset. Falls back gracefully when the exact
    resolution is unavailable (the original version required an exact match)."""
    if quality == "best":
        return "bestvideo*+bestaudio/best"
    if quality.startswith("audio-"):
        return "bestaudio/best"
    height = int(quality.rstrip("p"))
    return f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]/best"


def output_template(req: ClipRequest) -> str:
    """File name pattern. Clips get their time range appended so several clips
    of the same video never overwrite each other."""
    name = "%(title)s"
    if req.is_clip:
        name += f" [{format_timestamp(req.start).replace(':', '.')}-{format_timestamp(req.end).replace(':', '.')}]"
    return os.path.join(req.output_dir or ".", f"{name}.%(ext)s")


def build_ydl_options(
    req: ClipRequest,
    progress_hook: Optional[Callable[[dict], None]] = None,
    fragment_threads: int = 4,
) -> dict:
    """Translate a :class:`ClipRequest` into a yt-dlp options dict."""
    opts: dict = {
        "format": format_selector(req.quality),
        "outtmpl": output_template(req),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "concurrent_fragment_downloads": max(1, fragment_threads),
        "progress_hooks": [progress_hook] if progress_hook else [],
    }

    if req.is_audio:
        kbps = req.quality.split("-")[1].rstrip("k")
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": kbps}
        ]
    else:
        opts["merge_output_format"] = "mp4"

    if req.is_clip:
        # This is the correct yt-dlp API for partial downloads; the previous
        # 'download_sections' key is a CLI flag name and was silently ignored,
        # so the whole video was downloaded.
        from yt_dlp.utils import download_range_func

        opts["download_ranges"] = download_range_func(None, [(req.start, req.end)])
        opts["force_keyframes_at_cuts"] = True  # frame-accurate cut points

    return opts


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@dataclass
class Progress:
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    status: str = "queued"
    extra: dict = field(default_factory=dict)


def progress_from_hook(d: dict) -> Progress:
    """Normalise a yt-dlp progress dict (avoids parsing ANSI-coloured strings)."""
    status = d.get("status", "")
    if status == "finished":
        return Progress(percent=100.0, status="processing")
    if status != "downloading":
        return Progress(status=status or "unknown")

    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    done = d.get("downloaded_bytes") or 0
    percent = (done / total * 100.0) if total else 0.0

    speed = d.get("speed")
    eta = d.get("eta")
    return Progress(
        percent=max(0.0, min(percent, 100.0)),
        speed=f"{speed / 1_048_576:.1f} MB/s" if speed else "",
        eta=format_timestamp(eta) if eta is not None else "",
        status="downloading",
    )
