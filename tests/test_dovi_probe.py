import json
import types

from nazgarr.upload import dovi_probe
from nazgarr.upload.naming import dv_profile, hdr_full


def _ffprobe(monkeypatch, output: dict | None):
    calls = []
    monkeypatch.setattr(dovi_probe.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def run(command, **kwargs):
        calls.append(command)
        return types.SimpleNamespace(stdout=json.dumps(output) if output is not None else "", returncode=0)

    monkeypatch.setattr(dovi_probe.subprocess, "run", run)
    return calls


def _summary(**video):
    return {"video": {"format": "HEVC", "bit_depth": 10, **video}}


def test_dolby_vision_in_the_stream_completes_what_mediainfo_saw(monkeypatch):
    # MediaInfo: solo HDR10+ (manca il dvcC); ffprobe: l'RPU nel primo fotogramma
    # e il record di configurazione con il profilo.
    _ffprobe(monkeypatch, {"streams": [{"side_data_list": []}], "frames": [{"side_data_list": [
        {"side_data_type": "Dolby Vision RPU Data"},
        {"side_data_type": "DOVI configuration record", "dv_profile": 7},
    ]}]})
    summary = _summary(hdr_format="SMPTE ST 2094 App 4", hdr_format_compatibility="HDR10+ Profile B")

    assert dovi_probe.complete(summary, "/x.mkv") is True
    assert hdr_full(summary["video"]) == "DV.P7.HDR10+"
    assert dv_profile(summary["video"]) == 7 and summary["video"]["dolby_vision_from_stream"]


def test_only_the_rpu_gives_profile_5_or_just_dv(monkeypatch):
    _ffprobe(monkeypatch, {"frames": [{"side_data_list": [
        {"side_data_type": "Dolby Vision Metadata", "vdr_rpu_profile": 0}]}]})
    summary = _summary()
    dovi_probe.complete(summary, "/x.mkv")
    assert hdr_full(summary["video"]) == "DV.P5"

    # Profilo RPU 1: l'8 senza enhancement layer, il 7 con (come lo stima dovi_tool).
    for residual_off, expected in ((1, "DV.P8.HDR10"), (0, "DV.P7.HDR10")):
        _ffprobe(monkeypatch, {"frames": [{"side_data_list": [
            {"side_data_type": "Dolby Vision Metadata", "vdr_rpu_profile": 1,
             "disable_residual_flag": residual_off}]}]})
        summary = _summary(hdr_format="SMPTE ST 2086", hdr_format_compatibility="HDR10")
        dovi_probe.complete(summary, "/x.mkv")
        assert hdr_full(summary["video"]) == expected

    _ffprobe(monkeypatch, {"frames": [{"side_data_list": [{"side_data_type": "Dolby Vision RPU Data"}]}]})
    summary = _summary(hdr_format="SMPTE ST 2086", hdr_format_compatibility="HDR10")
    dovi_probe.complete(summary, "/x.mkv")
    assert hdr_full(summary["video"]) == "DV.HDR10"  # profilo non leggibile: da completare a mano


def test_ffprobe_runs_only_when_mediainfo_missed_it_and_the_video_can_have_it(monkeypatch):
    calls = _ffprobe(monkeypatch, {"frames": []})
    assert dovi_probe.complete(_summary(hdr_format="Dolby Vision, Version 1.0, dvhe.08.06"), "/x.mkv") is False
    assert dovi_probe.complete({"video": {"format": "AVC", "bit_depth": 8}}, "/x.mkv") is False
    assert dovi_probe.complete({"video": None}, "/x.mkv") is False
    assert calls == []
    # HEVC 10 bit senza DV nel flusso: si guarda, non cambia niente.
    summary = _summary(hdr_format="SMPTE ST 2086")
    assert dovi_probe.complete(summary, "/x.mkv") is False and len(calls) == 1
    assert summary["video"]["hdr_format"] == "SMPTE ST 2086"


def test_without_ffprobe_or_with_garbage_nothing_changes(monkeypatch):
    monkeypatch.setattr(dovi_probe.shutil, "which", lambda name: None)
    assert dovi_probe.complete(_summary(), "/x.mkv") is False
    _ffprobe(monkeypatch, None)
    assert dovi_probe.complete(_summary(), "/x.mkv") is False
