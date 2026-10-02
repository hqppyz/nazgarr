from nazgarr.mediainfo_util import extract_full_text


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

    from nazgarr.mediainfo_util import summarize

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
