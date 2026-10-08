"""Command-line interface.

    smart-clip https://youtu.be/VIDEO --start 1:30 --end 2:45 -q 1080p
    smart-clip https://youtu.be/VIDEO -q audio-320k --audio-format m4a
    smart-clip --batch jobs.txt -o ~/Clips
    smart-clip https://youtu.be/VIDEO --info
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .core import (
    AUDIO_FORMATS,
    QUALITY_PRESETS,
    VIDEO_CONTAINERS,
    ClipError,
    ClipRequest,
    build_ydl_options,
    ffmpeg_available,
    human_count,
    human_duration,
    parse_batch,
    parse_info,
    parse_timestamp,
    progress_from_hook,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="smart-clip", description="Download exact clips (or full videos / audio) from YouTube.")
    p.add_argument("url", nargs="?", help="video URL")
    p.add_argument("-s", "--start", help="clip start (SS, MM:SS or HH:MM:SS)")
    p.add_argument("-e", "--end", help="clip end")
    p.add_argument("-q", "--quality", default="1080p", choices=QUALITY_PRESETS)
    p.add_argument("-f", "--format", default="mp4", choices=VIDEO_CONTAINERS, help="video container")
    p.add_argument("--audio-format", default="mp3", choices=AUDIO_FORMATS)
    p.add_argument("-o", "--output", default=".", help="output folder")
    p.add_argument("--template", default="%(title)s", help="file name template")
    p.add_argument("--subs", help="subtitle languages, e.g. en,hi")
    p.add_argument("--rate-limit", help="e.g. 2M")
    p.add_argument("--cookies-from-browser", metavar="BROWSER")
    p.add_argument("--batch", metavar="FILE", help="file with one 'URL [START END]' per line")
    p.add_argument("--info", action="store_true", help="only print video details")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _bar(d: dict) -> None:
    pr = progress_from_hook(d)
    if pr.status == "downloading":
        filled = int(pr.percent / 4)
        sys.stdout.write(f"\r  [{'#' * filled}{'.' * (25 - filled)}] {pr.percent:5.1f}%  {pr.speed:>10}  ETA {pr.eta or '--'}   ")
        sys.stdout.flush()
    elif pr.status == "processing":
        sys.stdout.write("\r  processing with ffmpeg…" + " " * 40)
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import yt_dlp

    if not args.url and not args.batch:
        build_parser().print_help()
        return 2

    if args.info:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            v = parse_info(ydl.extract_info(args.url, download=False), args.url)
        print(f"{v.title}\n  channel : {v.channel}\n  length  : {human_duration(v.duration)}"
              f"\n  views   : {human_count(v.view_count)}\n  quality : up to {v.best_height}p"
              f"\n  subs    : {', '.join(v.subtitles[:15]) or 'none'}")
        return 0

    common = dict(
        quality=args.quality, output_dir=os.path.expanduser(args.output), video_format=args.format,
        audio_format=args.audio_format, subtitles=tuple((args.subs or "").split(",")) if args.subs else (),
        rate_limit=args.rate_limit, cookies_browser=args.cookies_from_browser, filename_template=args.template,
    )
    try:
        if args.batch:
            with open(args.batch, encoding="utf-8") as fh:
                parsed = parse_batch(fh.read(), args.quality, common["output_dir"])
            for p in parsed:
                if p.error:
                    print(f"skip line {p.line_no}: {p.error}", file=sys.stderr)
            jobs = [ClipRequest(p.request.url, p.request.start, p.request.end, **common) for p in parsed if p.request]
        else:
            start = parse_timestamp(args.start) if args.start else None
            end = parse_timestamp(args.end) if args.end else None
            jobs = [ClipRequest(args.url, start, end, **common)]
    except ClipError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not ffmpeg_available():
        print("warning: ffmpeg not found; clips, HD merges and audio conversion need it.", file=sys.stderr)
    os.makedirs(common["output_dir"], exist_ok=True)

    failed = 0
    for i, req in enumerate(jobs, 1):
        span = f" {human_duration(req.start)}→{human_duration(req.end)}" if req.is_clip else ""
        print(f"[{i}/{len(jobs)}] {req.url}{span}")
        opts = build_ydl_options(req, progress_hook=_bar)
        opts["quiet"] = True
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([req.url])
            print("\r  ✓ done" + " " * 60)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"\r  ✕ {str(exc).replace('ERROR: ', '')[:200]}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
