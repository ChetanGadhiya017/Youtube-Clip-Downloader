from smart_clip_downloader.history import History


def test_history_roundtrip(tmp_path):
    h = History(tmp_path / "h.json", limit=2)
    assert h.load() == []
    h.add(title="a")
    h.add(title="b")
    h.add(title="c")
    assert [e["title"] for e in h.load()] == ["c", "b"]
    h.clear()
    assert h.load() == []
