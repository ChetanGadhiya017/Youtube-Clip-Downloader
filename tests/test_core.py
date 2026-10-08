import pytest

from smart_clip_downloader.core import (
    ClipError,
    ClipRequest,
    build_ydl_options,
    format_selector,
    format_timestamp,
    output_template,
    parse_batch,
    parse_timestamp,
    progress_from_hook,
)


@pytest.mark.parametrize(
    "text, seconds",
    [("45", 45), ("1:30", 90), ("01:02:03", 3723), ("0:00:05.5", 5.5), (" 2:00 ", 120)],
)
def test_parse_timestamp_valid(text, seconds):
    assert parse_timestamp(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "1:75", "1:61:00", "-5"])
def test_parse_timestamp_invalid(text):
    with pytest.raises(ClipError):
        parse_timestamp(text)


def test_format_timestamp_roundtrip():
    assert format_timestamp(3723) == "01:02:03"
    assert parse_timestamp(format_timestamp(4000)) == 4000


def test_clip_request_validation():
    with pytest.raises(ClipError):
        ClipRequest("")
    with pytest.raises(ClipError):
        ClipRequest("not a url")
    with pytest.raises(ClipError):
        ClipRequest("https://youtu.be/x", 10, 5)
    with pytest.raises(ClipError):
        ClipRequest("https://youtu.be/x", 10, None)
    with pytest.raises(ClipError):
        ClipRequest("https://youtu.be/x", quality="999p")
    assert ClipRequest("https://youtu.be/x", 1, 2).is_clip
    assert not ClipRequest("https://youtu.be/x").is_clip


def test_parse_batch_mixed_lines():
    text = """
    # comment
    https://youtu.be/a 0:30 1:00
    https://youtu.be/b 1:00:00-1:00:30
    https://youtu.be/c
    https://youtu.be/d 2:00 1:00
    nonsense here
    """
    out = parse_batch(text, "720p", "/tmp")
    ok = [p.request for p in out if p.request]
    bad = [p for p in out if p.error]
    assert [r.url[-1] for r in ok] == ["a", "b", "c"]
    assert ok[1].start == 3600 and ok[1].end == 3630
    assert not ok[2].is_clip
    assert len(bad) == 2


def test_format_selector_falls_back():
    assert "height<=720" in format_selector("720p")
    assert format_selector("audio-128k") == "bestaudio/best"
    assert format_selector("best").startswith("bestvideo")


def test_output_template_includes_range_for_clips(tmp_path):
    clip = ClipRequest("https://youtu.be/x", 90, 150, output_dir=str(tmp_path))
    assert "[00.01.30-00.02.30]" in output_template(clip)
    full = ClipRequest("https://youtu.be/x", output_dir=str(tmp_path))
    assert "[" not in output_template(full)


def test_build_options_clip_uses_download_ranges():
    req = ClipRequest("https://youtu.be/x", 10, 20, quality="1080p")
    opts = build_ydl_options(req)
    assert "download_ranges" in opts and opts["force_keyframes_at_cuts"]
    assert "download_sections" not in opts
    ranges = list(opts["download_ranges"]({}, None))
    assert ranges[0]["start_time"] == 10 and ranges[0]["end_time"] == 20
    assert opts["merge_output_format"] == "mp4"


def test_build_options_audio():
    opts = build_ydl_options(ClipRequest("https://youtu.be/x", quality="audio-320k"))
    pp = opts["postprocessors"][0]
    assert pp["key"] == "FFmpegExtractAudio" and pp["preferredquality"] == "320"
    assert "download_ranges" not in opts


def test_options_are_accepted_by_yt_dlp():
    yt_dlp = pytest.importorskip("yt_dlp")
    opts = build_ydl_options(ClipRequest("https://youtu.be/x", 1, 2))
    with yt_dlp.YoutubeDL(opts):
        pass


def test_progress_from_hook():
    p = progress_from_hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200, "speed": 2_097_152, "eta": 65})
    assert p.percent == 25 and p.speed == "2.0 MB/s" and p.eta == "00:01:05"
    assert progress_from_hook({"status": "finished"}).percent == 100
    assert progress_from_hook({"status": "downloading", "downloaded_bytes": 5}).percent == 0
