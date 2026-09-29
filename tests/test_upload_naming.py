import json
from pathlib import Path
from types import SimpleNamespace

from pymediainfo import MediaInfo

from app import upload_profiles
from app.mediainfo_util import summarize
from app.models import TrackerUploadProfile
from app.upload_naming import build_name, detect, release_values
from tests.upload_helpers import make_tracker

MEDIAINFO = summarize(MediaInfo((Path(__file__).parent / "fixtures" / "mediainfo_remux.xml").read_text()), "x.mkv")
ITT_RULES = upload_profiles._load_bundled_profile("itt")["upload"]["naming"]


def _job(**extra):
    return SimpleNamespace(title="17 Again", year=2009, content_type="movie", kind="movie", seasons_json="[]",
                           episode=None, **extra)


def test_itt_remux_name_from_mediainfo_with_the_italian_title():
    detected = detect("17.Again.Ritorno.Al.Liceo.2009.REMUX.1080P.VU.AC3.ITA.TRUEHD.ENG.SUBS.ITA.ENG-MaTiTa")

    values = release_values(_job(), detected, MEDIAINFO, {}, ITT_RULES, local_title="17 Again - Ritorno al liceo")

    assert values["video_codec"] == "VC-1"
    assert (values["audio"], values["audio_all"]) == ("TrueHD 5.1", "TrueHD 5.1 DD 5.1 DD 5.1")
    assert (values["audio_codec"], values["audio_channels"], values["audio_atmos"]) == ("TrueHD", "5.1", None)
    assert (values["audio_languages"], values["subs_languages"], values["bit_depth"]) == ("ITA ENG", "ENG ITA", "8bit")
    assert build_name(ITT_RULES, values) == (
        "17 Again - Ritorno al liceo 2009 1080p REMUX VU VC-1 ITA ENG TrueHD 5.1 DD 5.1 DD 5.1-MaTiTa"
    )


def test_generic_rules_use_the_main_track_and_overrides_win():
    detected = detect("Movie.2009.1080p.BluRay.REMUX-GRP")
    template = "{title} {year} {resolution} {hdr} {video_codec} {audio} {audio_languages} {group}"
    rules = {"audio": "main", "audio_languages": {"style": "all"}, "sdr_label": "SDR",
             "templates": {"default": template}}

    values = release_values(_job(), detected, MEDIAINFO, {"group": "ME", "audio": "LPCM 2.0"}, rules)

    assert build_name(rules, values) == "17 Again 2009 1080p SDR VC-1 LPCM 2.0 ENG ITA-ME"


def test_without_mediainfo_the_name_fills_in():
    detected = detect("Movie.2019.2160p.WEB-DL.DDP5.1.Atmos.DV.HDR.H.265-GRP")

    values = release_values(_job(), detected, None, {}, None)

    assert (values["resolution"], values["audio"], values["hdr"], values["video_codec"]) == (
        "2160p", "DD+ 5.1 Atmos", "DV HDR", "H.265",
    )


def test_bundled_naming_rules_are_versioned(db_session, monkeypatch):
    tracker = make_tracker(db_session, "itt", with_profile=False)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    assert profile.naming_version == ITT_RULES["version"] and profile.naming_customized is False

    newer = {**ITT_RULES, "version": ITT_RULES["version"] + 1, "sdr_label": "SDR"}
    monkeypatch.setattr(upload_profiles, "_bundled_naming", lambda key: newer)

    # Non modificate dall'utente: si aggiornano da sole.
    assert upload_profiles.sync_naming_rules(db_session) == ["itt"]
    assert json.loads(profile.naming_rules_json)["sdr_label"] == "SDR"

    # Modificate: la versione nuova viene solo offerta...
    profile.naming_customized = True
    db_session.commit()
    newest = {**newer, "version": newer["version"] + 1}
    monkeypatch.setattr(upload_profiles, "_bundled_naming", lambda key: newest)
    assert upload_profiles.sync_naming_rules(db_session) == []
    assert profile.naming_update_available == newest["version"]
    # ...a meno che sia forzata.
    monkeypatch.setattr(upload_profiles, "_bundled_naming", lambda key: {**newest, "force": True})
    assert upload_profiles.sync_naming_rules(db_session) == ["itt"]
    refreshed = db_session.get(TrackerUploadProfile, tracker.id)
    assert (refreshed.naming_version, refreshed.naming_customized, refreshed.naming_update_available) == (
        newest["version"], False, None,
    )
