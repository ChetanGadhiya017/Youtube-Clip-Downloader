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


# ------------------------------------------------------------------ v3
from smart_clip_downloader.core import (  # noqa: E402
    extract_urls,
    human_count,
    human_duration,
    is_playlist_url,
    parse_info,
    parse_rate,
    playlist_entries,
    video_id,
)


def test_formats_subtitles_and_extras_in_options():
    req = ClipRequest("https://youtu.be/x", quality="720p", video_format="mkv", subtitles=("en", " hi "),
                      embed_thumbnail=True, rate_limit="2M", cookies_browser="firefox")
    opts = build_ydl_options(req)
    keys = [p["key"] for p in opts["postprocessors"]]
    assert opts["merge_output_format"] == "mkv"
    assert opts["subtitleslangs"] == ["en", "hi"] and "FFmpegEmbedSubtitle" in keys
    assert "EmbedThumbnail" in keys and "FFmpegMetadata" in keys
    assert opts["ratelimit"] == 2 * 1024 * 1024
    assert opts["cookiesfrombrowser"] == ("firefox",)
    assert opts["continuedl"] is True


def test_audio_format_choice():
    opts = build_ydl_options(ClipRequest("https://youtu.be/x", quality="audio-192k", audio_format="opus"))
    pp = opts["postprocessors"][0]
    assert pp == {"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "192"}
    assert "writesubtitles" not in opts


@pytest.mark.parametrize("kwargs", [
    {"video_format": "avi"}, {"audio_format": "aac"}, {"rate_limit": "fast"},
    {"filename_template": "../evil"}, {"filename_template": "C:/x"}, {"filename_template": "/abs"},
])
def test_invalid_v3_fields(kwargs):
    with pytest.raises(ClipError):
        ClipRequest("https://youtu.be/x", **kwargs)


def test_custom_filename_template(tmp_path):
    req = ClipRequest("https://youtu.be/x", 5, 9, output_dir=str(tmp_path), filename_template="%(uploader)s - %(title)s")
    assert output_template(req).endswith("%(uploader)s - %(title)s [00.00.05-00.00.09].%(ext)s")


def test_parse_rate():
    assert parse_rate("500K") == 512000 and parse_rate("1.5m") == int(1.5 * 1024**2) and parse_rate("100") == 100


def test_url_helpers():
    assert video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "dQw4w9WgXcQ"
    assert video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id("https://youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert is_playlist_url("https://www.youtube.com/playlist?list=PL123")
    assert is_playlist_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123")
    assert not is_playlist_url("https://youtu.be/dQw4w9WgXcQ")
    text = "see https://youtu.be/AAAAAAAAAAA, and (https://www.youtube.com/watch?v=BBBBBBBBBBB) https://youtu.be/AAAAAAAAAAA"
    assert extract_urls(text) == ["https://youtu.be/AAAAAAAAAAA", "https://www.youtube.com/watch?v=BBBBBBBBBBB"]
    assert extract_urls("https://example.com/video") == []


def test_parse_info_and_qualities():
    info = {
        "title": "Demo", "uploader": "Chan", "duration": 125, "thumbnail": "https://i/x.jpg",
        "formats": [{"height": 360, "vcodec": "avc"}, {"height": 1080, "vcodec": "vp9"}, {"height": None, "vcodec": "none"}],
        "subtitles": {"en": []}, "automatic_captions": {"hi": []}, "view_count": 1234567,
    }
    v = parse_info(info, "https://youtu.be/x")
    assert v.heights == [360, 1080] and v.best_height == 1080
    assert v.subtitles == ["en", "hi"] and v.channel == "Chan"
    q = v.available_qualities()
    assert "1080p" in q and "1440p" not in q and q[0] == "best" and "audio-320k" in q
    assert human_duration(125) == "02:05" and human_duration(3725) == "01:02:05"
    assert human_count(1234567) == "1.2M" and human_count(999) == "999"


def test_playlist_entries():
    info = {"entries": [{"id": "AAAAAAAAAAA", "title": "One", "url": "AAAAAAAAAAA"},
                        {"url": "https://www.youtube.com/watch?v=BBBBBBBBBBB", "title": "Two"}, None]}
    assert playlist_entries(info) == [
        ("https://www.youtube.com/watch?v=AAAAAAAAAAA", "One"),
        ("https://www.youtube.com/watch?v=BBBBBBBBBBB", "Two"),
    ]
