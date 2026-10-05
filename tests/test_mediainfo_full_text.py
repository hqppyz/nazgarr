from nazgarr.library.mediainfo import extract_full_text


def test_extract_full_text_returns_report_for_readable_file(tmp_path):
    path = tmp_path / "x.mkv"
    path.write_bytes(b"not a real video" * 50)

    text = extract_full_text(str(path))

    assert text is not None
    assert "General" in text
    assert "Complete name" in text


def test_extract_full_text_returns_none_for_missing_file():
    assert extract_full_text("/nonexistent/path/x.mkv") is None


def test_summarize_reads_what_a_tracker_preview_shows():
    from pathlib import Path

    from pymediainfo import MediaInfo

    from nazgarr.library.mediainfo import summarize

    xml = (Path(__file__).parent / "fixtures" / "mediainfo_remux.xml").read_text()
    summary = summarize(MediaInfo(xml), "17.Again.mkv")

    assert summary["general"] == {"format": "Matroska", "duration_ms": 6087000, "overall_bit_rate": 20900000,
                                  "file_size": 15998700000}
    video = summary["video"]
    assert (video["format"], video["bit_depth"], video["width"], video["height"]) == ("VC-1", 8, 1920, 1080)
    assert (video["display_aspect_ratio"], video["frame_rate_num"], video["frame_rate_den"]) == ("16:9", 24000, 1001)
    assert [(a["language"], a["format"], a["channels"], a["default"]) for a in summary["audio"]] == [
        ("en", "MLP FBA", 6, True), ("en", "AC-3", 6, False), ("it", "AC-3", 6, False),
    ]
    assert [(s["language"], s["forced"]) for s in summary["subtitles"]] == [("en", False), ("it", True)]


def test_mediainfo_is_read_once_per_file_until_the_file_changes(tmp_path, monkeypatch):
    """Analisi, pack misti, screenshot e Unique ID leggono lo stesso video:
    una lettura per file (anche attraverso un hardlink), di nuovo solo se
    il file cambia."""
    import os

    from nazgarr.library import mediainfo as mediainfo_util

    mediainfo_util.clear_cache()
    calls = []
    real = mediainfo_util.MediaInfo.parse
    monkeypatch.setattr(mediainfo_util.MediaInfo, "parse",
                        lambda path, **kw: calls.append((os.path.basename(path), kw.get("output"))) or real(path, **kw))
    video = tmp_path / "x.mkv"
    video.write_bytes(b"not a real video" * 50)
    link = tmp_path / "Renamed.mkv"
    os.link(video, link)

    mediainfo_util.extract_summary(str(video))
    mediainfo_util.compute_unique_id(str(video))
    mediainfo_util.parse(str(link))  # stesso inode: stessa voce
    mediainfo_util.extract_full_text(str(video))
    mediainfo_util.extract_full_text(str(video))
    assert calls == [("x.mkv", None), ("x.mkv", "STRING")]

    video.write_bytes(b"changed content" * 60)
    mediainfo_util.parse(str(video))
    assert len(calls) == 3
    mediainfo_util.clear_cache()
