import json
from pathlib import Path
from types import SimpleNamespace

from pymediainfo import MediaInfo

from app import upload_profiles
from app.mediainfo_util import summarize
from app.models import TrackerUploadProfile
from app.upload_naming import build_name, detect, release_values, resolution_format, with_tracker_language
from tests.upload_helpers import make_tracker

MEDIAINFO = summarize(MediaInfo((Path(__file__).parent / "fixtures" / "mediainfo_remux.xml").read_text()), "x.mkv")
# Le regole di ITT con la lingua del suo tracker, come nella proposta vera.
ITT_RULES = with_tracker_language(upload_profiles._load_bundled_profile("itt")["upload"]["naming"], "it")


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
    assert (values["audio_languages"], values["subs_languages"], values["bit_depth"]) == ("ITA ENG", "ITA ENG", "8bit")
    assert build_name(ITT_RULES, values) == (
        "17 Again - Ritorno al liceo 2009 1080p FullHD VU REMUX TrueHD 5.1 DD 5.1 ITA ENG SUBS VC-1-MaTiTa"
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


def test_format_is_the_resolution_in_letters_and_follows_the_override():
    assert [resolution_format(r) for r in ("4320p", "2160p", "1080i", "1080p", "720p", "576p", "480p", None)] == [
        "UHD", "UHD", "FullHD", "FullHD", "HD", "SD", "SD", None,
    ]
    detected = detect("Movie.2019.2160p.WEB-DL.DDP5.1.H.265-GRP")
    rules = {"templates": {"default": "{title} {year} {format} {resolution} {group}"}}

    assert release_values(_job(), detected, None, {}, rules)["format"] == "UHD"
    values = release_values(_job(), detected, None, {"resolution": "720p"}, rules)
    assert build_name(rules, values) == "17 Again 2009 HD 720p-GRP"


def test_sources_are_written_as_in_the_tracker_rules():
    assert [detect(name)["source"] for name in (
        "Movie.2010.1080p.3D.BluRay.x264-GRP", "Movie.2010.1080p.HDDVD.x264-GRP", "Show.S01E01.2160p.UHDTV.x265-GRP",
        "Movie.2010.2160p.UHDRip.x265-GRP", "Movie.2010.PAL.DVD9-GRP", "Movie.2010.2160p.UHD.BluRay.x265-GRP",
    )] == ["3D BluRay", "HDDVD", "UHDTV", "UHDRip", "PAL DVD", "BluRay"]
    # Un DVD senza PAL/NTSC nel nome: lo dice la risoluzione.
    values = release_values(_job(), detect("Movie.2010.DVDRip.x264-GRP"), None, {"resolution": "576p"}, None)
    assert values["source"] == "PAL DVD"


def test_web_releases_get_the_service_abbreviation_and_mux_types():
    amazon = detect("Show.S01E01.1080p.AMZN.WEB-DL.DDP5.1.H.264-GRP")
    timvision = detect("Show.S01E01.1080p.TIMV.WEB-DL.H.264-GRP")  # guessit non conosce TIMvision
    # Una parola del titolo non è un servizio.
    title_only = detect("Max.2020.1080p.WEB-DL.H.264-GRP")

    assert (amazon["service"], timvision["service"], title_only["service"]) == ("AMZN", "TIMV", None)
    assert detect("Show.S01E01.720p.iP.WEBMux-GRP")["type"] == "WEBMUX"
    assert detect("Show.S01E01.1080p.NF.DLMux-GRP")["type"] == "DLMUX"
    assert detect("Movie.2010.1080p.BluRay.x264-GRP")["service"] is None


def test_source_full_is_the_service_for_web_the_disc_for_a_full_disc_and_the_source_otherwise():
    web = release_values(_job(), detect("Movie.2019.1080p.NF.WEB-DL.H.264-GRP"), None, {}, None)
    remux = release_values(_job(), detect("Movie.2019.2160p.UHD.BluRay.REMUX.HEVC-GRP"), None, {}, None)
    disc = release_values(_job(), detect("Movie.2019.2160p.UHD.BluRay.REMUX.HEVC-GRP"), None, {"type": "DISC"}, None)

    assert (web["source_full"], remux["source_full"], disc["source_full"]) == ("NF", "BluRay", "UHD Blu-ray")


def test_itt_names_follow_the_wiki_source_and_format():
    web = release_values(_job(), detect("Movie.2009.1080p.NF.WEB-DL.DDP5.1.H.264-GRP"), None, {}, ITT_RULES)
    encode = release_values(_job(), detect("Movie.2009.720p.BluRay.DD5.1.x264-GRP"), None, {}, ITT_RULES)

    assert build_name(ITT_RULES, web) == "17 Again 2009 1080p FullHD NF WEB-DL DD+ 5.1 H.264-GRP"
    assert build_name(ITT_RULES, encode) == "17 Again 2009 720p SD BluRay DD 5.1 x264-GRP"
    assert (web["format"], encode["format"]) == ("FullHD", "SD")  # ITT non ha HD


def test_an_untouched_bundled_description_moves_to_the_current_one(db_session):
    bundled = upload_profiles._load_bundled_profile("itt")["upload"]
    old = bundled["replaces_description_templates"][0]
    tracker = make_tracker(db_session, "itt", with_profile=False)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    assert "mediainfo" not in profile.description_template

    profile.description_template = old
    db_session.commit()
    assert upload_profiles.sync_description_templates(db_session) == ["itt"]
    assert profile.description_template == bundled["description_template"]

    # Modificata dall'utente: non si tocca.
    profile.description_template = old + "mine"
    db_session.commit()
    assert upload_profiles.sync_description_templates(db_session) == []
    assert profile.description_template == old + "mine"


def test_itt_subs_follow_the_tracker_language():
    def subs(audio: list[str], subtitles: list[str]) -> str | None:
        mediainfo = {
            "video": {}, "audio": [{"language": lang} for lang in audio],
            "subtitles": [{"language": lang} for lang in subtitles],
        }
        return release_values(_job(), detect("Movie.2009.1080p.BluRay.x264-GRP"), mediainfo, {}, ITT_RULES)["subs"]

    # Audio già in italiano: solo SUB/SUBS, secondo le lingue (non le tracce).
    assert subs(["it", "en"], ["en"]) == "SUB"
    assert subs(["it"], ["it", "it"]) == "SUB"
    assert subs(["it", "en"], ["it", "en"]) == "SUBS"
    # Audio non in italiano e un sottotitolo italiano: la lingua.
    assert subs(["en"], ["it"]) == "SUB ITA"
    assert subs(["en"], ["it", "en", "fr"]) == "SUBS ITA"
    # Nessun sottotitolo italiano: senza lingua. Nessun sottotitolo: niente.
    assert subs(["en"], ["en", "fr"]) == "SUBS"
    assert subs(["en"], []) is None


def test_the_tracker_language_replaces_the_one_in_the_rules():
    rules = with_tracker_language({"audio_languages": {"style": "primary_first", "primary": "ENG"}}, "it")

    assert (rules["title_language"], rules["language"], rules["audio_languages"]["primary"]) == ("it", "ITA", "ITA")
    assert with_tracker_language({"title": "local"}, None) == {"title": "local"}


def test_atmos_comes_once_after_all_the_audio_codecs():
    def track(language, fmt, channels, features=None):
        return {"language": language, "format": fmt, "channels": channels, "format_additional_features": features}

    series = {"video": {}, "subtitles": [], "audio": [
        {**track("en", "E-AC-3", 6, "JOC"), "default": True}, track("it", "E-AC-3", 6), track("es", "E-AC-3", 6),
    ]}
    remux = {"video": {}, "subtitles": [], "audio": [
        {**track("en", "MLP FBA", 8, "16-ch"), "default": True}, track("it", "E-AC-3", 6), track("en", "DTS", 6, "XLL"),
    ]}
    detected = detect("Movie.2009.1080p.BluRay.x264-GRP")

    assert release_values(_job(), detected, series, {}, ITT_RULES)["audio_all"] == "DD+ 5.1 Atmos"
    values = release_values(_job(), detected, remux, {}, ITT_RULES)
    assert values["audio_all"] == "TrueHD 7.1 DD+ 5.1 DTS-HD MA 5.1 Atmos"
    # La traccia principale da sola resta codec, canali, oggetto.
    assert values["audio"] == "TrueHD 7.1 Atmos"
