import pytest

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
    real = mediainfo_util._run_isolated
    monkeypatch.setattr(mediainfo_util, "_run_isolated",
                        lambda path, kind: calls.append((os.path.basename(path), kind)) or real(path, kind))
    video = tmp_path / "x.mkv"
    video.write_bytes(b"not a real video" * 50)
    link = tmp_path / "Renamed.mkv"
    os.link(video, link)

    mediainfo_util.extract_summary(str(video))
    mediainfo_util.compute_unique_id(str(video))
    mediainfo_util.parse(str(link))  # stesso inode: stessa voce
    mediainfo_util.extract_full_text(str(video))
    mediainfo_util.extract_full_text(str(video))
    assert calls == [("x.mkv", "object"), ("x.mkv", "text")]

    video.write_bytes(b"changed content" * 60)
    mediainfo_util.parse(str(video))
    assert len(calls) == 3
    mediainfo_util.clear_cache()


def test_the_parse_runs_in_a_child_and_its_crash_or_hang_is_only_an_error(tmp_path, monkeypatch):
    """libmediainfo è codice nativo che legge file da fuori: un suo crash
    chiudeva tutto il processo, e il worker al riavvio riprendeva lo stesso
    job (audit 2026-10-18). Nel figlio, crash e blocchi sono un None."""
    from pymediainfo import MediaInfo

    from nazgarr.library import mediainfo as mediainfo_util

    video = tmp_path / "x.mkv"
    video.write_bytes(b"not a real video" * 50)
    in_process = MediaInfo.parse(str(video))
    isolated = mediainfo_util.parse(str(video))
    assert isolated.to_data() == in_process.to_data()  # le stesse tracce di prima

    mediainfo_util.clear_cache()
    crash = "import os, signal\nos.kill(os.getpid(), signal.SIGSEGV)\n"
    monkeypatch.setattr(mediainfo_util, "_CHILD", crash)
    assert mediainfo_util.extract_summary(str(video)) is None
    assert mediainfo_util.compute_unique_id(str(video)) is None  # e il processo dei test è ancora qui

    monkeypatch.setattr(mediainfo_util, "_CHILD", "import time\ntime.sleep(30)\n")
    monkeypatch.setattr(mediainfo_util, "PARSE_TIMEOUT_SECONDS", 0.5)
    try:
        mediainfo_util.parse(str(video))
    except mediainfo_util.MediaInfoFailed as exc:
        assert "did not finish" in str(exc)
    else:
        raise AssertionError("un blocco deve scadere")


def test_a_huge_report_from_the_child_is_cut_off_not_buffered(tmp_path, monkeypatch):
    """Il tetto sull'uscita del figlio scattava dopo che subprocess.run
    l'aveva tenuta tutta in memoria (audit 2026-10-18): un file costruito
    per far scrivere a libmediainfo un report enorme arrivava intero nel
    processo di Nazgarr. Ora si legge a pezzi e il figlio si ferma appena
    passa il tetto."""
    import tracemalloc

    from nazgarr.library import mediainfo as mediainfo_util

    mediainfo_util.clear_cache()
    video = tmp_path / "x.mkv"
    video.write_bytes(b"not a real video" * 50)
    flood = "import sys\nfor _ in range(256):\n    sys.stdout.buffer.write(b'x' * 1048576)\n"  # 256 MB
    monkeypatch.setattr(mediainfo_util, "_CHILD", flood)
    monkeypatch.setattr(mediainfo_util, "MAX_OUTPUT_BYTES", 1024 * 1024)

    tracemalloc.start()
    try:
        with pytest.raises(mediainfo_util.MediaInfoFailed, match="bigger than 1 MB"):
            mediainfo_util.parse(str(video))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024
    assert mediainfo_util.extract_full_text(str(video)) is None  # per chi chiama è solo "niente MediaInfo"


def test_only_the_last_lines_of_the_child_errors_are_kept(tmp_path, monkeypatch):
    from nazgarr.library import mediainfo as mediainfo_util

    mediainfo_util.clear_cache()
    video = tmp_path / "x.mkv"
    video.write_bytes(b"not a real video" * 50)
    noisy = "import sys\nsys.stderr.write('noise\\n' * 1000000)\nsys.stderr.write('the real error\\n')\nsys.exit(3)\n"
    monkeypatch.setattr(mediainfo_util, "_CHILD", noisy)

    with pytest.raises(mediainfo_util.MediaInfoFailed, match=r"exit code 3\): the real error"):
        mediainfo_util.parse(str(video))
