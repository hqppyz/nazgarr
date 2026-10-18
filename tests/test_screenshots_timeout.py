"""Il tempo massimo dei comandi di ffmpeg (audit 2026-10-18): senza il
binario, con subprocess finto."""

import subprocess

import pytest

from nazgarr.upload import screenshots


@pytest.fixture
def video(monkeypatch, tmp_path):
    monkeypatch.setattr(screenshots, "_get_duration_seconds", lambda path: 100.0)
    return str(tmp_path / "video.mkv")


def test_a_stuck_ffmpeg_is_stopped_and_the_screenshot_skipped(monkeypatch, tmp_path, video):
    timeouts = []

    def run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        assert kwargs["stdin"] is subprocess.DEVNULL
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(screenshots.subprocess, "run", run)

    with pytest.raises(screenshots.ScreenshotError):
        screenshots.generate_screenshots(video, str(tmp_path / "shots"), count=2)
    assert timeouts and all(0 < t <= screenshots.COMMAND_TIMEOUT_SECONDS for t in timeouts)
    assert screenshots.luma_stats(str(tmp_path / "x.png")) is None


def test_all_the_screenshots_together_have_a_time_limit(monkeypatch, tmp_path, video):
    clock = [0.0]
    monkeypatch.setattr(screenshots.time, "monotonic", lambda: clock[0])
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        clock[0] += 500  # ogni comando arriva quasi al suo tempo massimo
        if any("signalstats" in str(a) for a in argv):
            return subprocess.CompletedProcess(argv, 0, b"", b"lavfi.signalstats.YAVG=90 YMIN=10 YMAX=220")
        with open(next(a for a in argv if str(a).endswith(".png")), "wb") as f:
            f.write(b"png")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(screenshots.subprocess, "run", run)

    paths = screenshots.generate_screenshots(video, str(tmp_path / "shots"), count=4)

    assert len(paths) == 1  # il primo (cattura e statistiche), poi il tempo è finito
    assert len(calls) == 2
