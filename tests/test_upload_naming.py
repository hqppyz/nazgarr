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
    # Due tracce DD 5.1 (inglese e italiano): una volta sola.
    assert (values["audio"], values["audio_all"]) == ("TrueHD 5.1", "TrueHD 5.1 DD 5.1")
    assert (values["audio_codec"], values["audio_channels"], values["audio_atmos"]) == ("TrueHD", "5.1", None)
    assert (values["audio_languages"], values["subs_languages"], values["bit_depth"]) == ("ITA ENG", "ENG ITA", "8bit")
    assert build_name(ITT_RULES, values) == (
        "17 Again - Ritorno al liceo 2009 1080p REMUX VU VC-1 ITA ENG TrueHD 5.1 DD 5.1-MaTiTa"
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


def test_multi_above_a_number_of_languages_also_for_all_and_subtitles():
    from app.upload_naming import _languages_value

    tracks = [{"language": code} for code in ("en", "it", "fr")]
    assert _languages_value(tracks, {"style": "all", "multi_from": 3}) == "MULTI"
    assert _languages_value(tracks[:2], {"style": "all", "multi_from": 3}) == "ENG ITA"
    assert _languages_value(tracks, {"style": "primary_first", "primary": "ITA", "multi_from": 3}) == "ITA MULTI"


def test_one_pattern_with_type_labels_that_can_hold_variables():
    rules = {"templates": {"default": "{title} {resolution} {type} {video_codec} {group}"},
             "type_labels": {"REMUX": "{source} REMUX VU", "ENCODE": ""}}
    base = {"title": "Dune", "resolution": "2160p", "source": "UHD BluRay", "video_codec": "HEVC", "group": "G"}

    assert build_name(rules, {**base, "type": "REMUX"}) == "Dune 2160p UHD BluRay REMUX VU HEVC-G"
    assert build_name(rules, {**base, "type": "ENCODE"}) == "Dune 2160p HEVC-G"
    # Senza etichetta del profilo: quella di default, non la chiave.
    assert build_name(rules, {**base, "type": "WEBDL"}) == "Dune 2160p WEB-DL HEVC-G"
    # Un pattern specifico vuoto usa quello principale.
    assert build_name({**rules, "templates": {**rules["templates"], "WEBDL": " "}}, {**base, "type": "WEBDL"}) == (
        "Dune 2160p WEB-DL HEVC-G"
    )


def test_subs_writes_a_label_with_the_languages_and_can_be_turned_off():
    detected = detect("Movie.2009.1080p.BluRay.REMUX-GRP")
    rules = {"templates": {"default": "{title} {resolution} {subs} {group}"}}

    values = release_values(_job(), detected, MEDIAINFO, {}, rules)
    assert build_name(rules, values) == "17 Again 1080p SUBS ENG ITA-GRP"
    off = {**rules, "subs_format": ""}
    assert build_name(off, release_values(_job(), detected, MEDIAINFO, {}, off)) == "17 Again 1080p-GRP"
    legacy = {**rules, "subs_label": "SUBS"}  # regole scritte prima di subs_format
    assert build_name(legacy, release_values(_job(), detected, MEDIAINFO, {}, legacy)) == "17 Again 1080p SUBS-GRP"


def test_series_use_their_own_pattern_when_there_is_one():
    rules = {"templates": {"default": "{title} {year} {resolution} {group}",
                           "tv": "{title} {season} {resolution} {group}",
                           "REMUX": "{title} {year} REMUX {group}"}}
    base = {"title": "Severance", "year": 2022, "season": "S02", "resolution": "1080p", "group": "G"}

    assert build_name(rules, {**base, "content_type": "tv", "type": "REMUX"}) == "Severance S02 1080p-G"
    movie = {**base, "content_type": "movie", "type": "REMUX", "season": None}
    assert build_name(rules, movie) == "Severance 2022 REMUX-G"
    no_tv = {"templates": {"default": rules["templates"]["default"]}}
    assert build_name(no_tv, {**base, "content_type": "tv"}) == "Severance 2022 S02 1080p-G"
