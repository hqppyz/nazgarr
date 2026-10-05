from nazgarr.library.exclusions import compile_exclusions, parse_custom_patterns, parse_preset_keys


def test_parse_custom_patterns_strips_blank_lines():
    assert parse_custom_patterns("*.nfo\n\n  *.sfv  \n") == ["*.nfo", "*.sfv"]


def test_parse_custom_patterns_handles_none_and_empty():
    assert parse_custom_patterns(None) == []
    assert parse_custom_patterns("") == []


def test_parse_preset_keys_splits_csv():
    assert parse_preset_keys("scene_junk, qbittorrent_incomplete") == ["scene_junk", "qbittorrent_incomplete"]


def test_custom_pattern_matches_extension_anywhere():
    exclusions = compile_exclusions("*.nfo", None)
    assert exclusions.is_excluded("Movie.2024/Movie.2024.nfo")
    assert not exclusions.is_excluded("Movie.2024/Movie.2024.mkv")


def test_custom_pattern_with_slash_matches_full_relative_path():
    exclusions = compile_exclusions("sample/*", None)
    assert exclusions.is_excluded("Movie.2024/sample/preview.mkv")
    assert not exclusions.is_excluded("Movie.2024/Movie.2024.mkv")


def test_no_patterns_excludes_nothing():
    # Stringa vuota salvata = l'utente ha scelto "nessun preset".
    exclusions = compile_exclusions(None, "")
    assert not exclusions.is_excluded("anything/at/all.nfo")


def test_presets_never_saved_enable_metadata_system_files_and_torrents_by_default():
    exclusions = compile_exclusions(None, None)
    assert exclusions.is_excluded("tv/Show/Season 01/Show - S01E01-thumb.jpg")
    assert exclusions.is_excluded("movies/Interstellar (2014)/poster.jpg")
    assert exclusions.is_excluded("movies/Interstellar (2014)/Interstellar.nfo")
    assert exclusions.is_excluded("movies/Interstellar (2014)/._Interstellar.mkv")  # AppleDouble di macOS
    assert exclusions.is_excluded("movies/Interstellar (2014)/Interstellar.torrent")
    assert not exclusions.is_excluded("movies/Interstellar (2014)/Interstellar.mkv")
    assert not exclusions.is_excluded("movies/Interstellar (2014)/Interstellar.en.srt")
    # Gli extra sono video veri: restano finché l'utente non accende il loro preset.
    assert not exclusions.is_excluded("movies/Interstellar (2014)/Featurettes/Black Hole.mkv")


def test_media_server_artwork_as_plex_and_jellyfin_name_it():
    # Plex "Local Media Assets" e Jellyfin: nomi fissi, numerati, col nome del
    # video e le miniature degli episodi; tutti immagini.
    exclusions = compile_exclusions(None, "media_server_metadata")
    for path in ("Avatar (2009)/cover.jpg", "Avatar (2009)/poster-2.png", "Avatar (2009)/Avatar (2009)-fanart.jpg",
                 "Avatar (2009)/backgroundSquare.jpg", "Avatar (2009)/clearlogo.png", "Batman Begins (2005)-1.jpg",
                 "Heroes/Season 01/Season01a.jpg", "Heroes/season-specials-poster.jpg",
                 "Heroes/Season 01/Heroes - s01e01 - Genesis.jpg", "Heroes/theme.mp3",
                 "Heroes/theme-music/main.flac", "Avatar (2009)/backdrops/theme.mkv", "Avatar (2009)/poster.tbn"):
        assert exclusions.is_excluded(path), path


def test_extras_as_plex_and_jellyfin_name_them():
    exclusions = compile_exclusions(None, "extras")
    for path in ("Avatar (2009)/Behind The Scenes/Performance Capture.mkv", "Avatar (2009)/Featurettes/x.mkv",
                 "Avatar (2009)/Bar Fight-deleted.mp4", "Avatar (2009)/Teaser Trailer-trailer.mp4",
                 "Avatar (2009)/Sigourney Weaver-interview.mp4", "Avatar (2009)/trailer.mp4",
                 "Avatar (2009)/Avatar.trailer.mkv"):
        assert exclusions.is_excluded(path), path
    assert not exclusions.is_excluded("Avatar (2009)/Avatar (2009).mkv")
    assert not exclusions.is_excluded("The.Big.Short.2015.1080p.BluRay-GRP/The.Big.Short.2015.mkv")


def test_system_files_of_macos_and_windows():
    exclusions = compile_exclusions(None, "system_files")
    for path in ("x/._Movie.mkv", "x/.DS_Store", "x/.AppleDouble/Movie.mkv", "x/Icon\r", ".Trashes/501/a.mkv",
                 "x/Thumbs.db", "x/desktop.ini", "$RECYCLE.BIN/S-1/a.mkv"):
        assert exclusions.is_excluded(path), path
    assert not exclusions.is_excluded("x/Movie.mkv")


def test_new_default_presets_reach_who_had_saved_their_choices(db_session):
    from nazgarr.core import settings_repo
    from nazgarr.core.db import migrate_new_default_exclusion_presets

    settings_repo.set_setting(db_session, "exclusion_presets", "media_server_metadata,scene_junk")

    assert migrate_new_default_exclusion_presets(db_session.get_bind()) is True
    assert migrate_new_default_exclusion_presets(db_session.get_bind()) is False
    db_session.expire_all()
    assert settings_repo.get_setting(db_session, "exclusion_presets") == (
        "media_server_metadata,scene_junk,system_files,torrent_files")


def test_preset_qbittorrent_incomplete():
    exclusions = compile_exclusions(None, "qbittorrent_incomplete")
    assert exclusions.is_excluded("Movie.2024/Movie.2024.mkv.!qb")
    assert not exclusions.is_excluded("Movie.2024/Movie.2024.mkv")


def test_preset_scene_junk_covers_samples_and_nfo():
    exclusions = compile_exclusions(None, "scene_junk")
    assert exclusions.is_excluded("Movie.2024/Movie.2024.nfo")
    assert exclusions.is_excluded("Movie.2024/sample/preview.mkv")
    assert not exclusions.is_excluded("Movie.2024/Movie.2024.mkv")


def test_custom_and_preset_patterns_combine():
    exclusions = compile_exclusions("*.custom-junk", "qbittorrent_incomplete")
    assert exclusions.is_excluded("x.custom-junk")
    assert exclusions.is_excluded("x.mkv.!qb")
    assert not exclusions.is_excluded("x.mkv")


def test_matching_is_case_insensitive():
    exclusions = compile_exclusions("*.NFO", None)
    assert exclusions.is_excluded("movie/readme.nfo")


def test_compiled_patterns_match_exactly_like_fnmatch():
    """Le espressioni regolari compilate danno gli stessi risultati di
    fnmatch pattern per pattern (la regola documentata in cima al modulo)."""
    import fnmatch

    from nazgarr.library.exclusions import PRESETS, CompiledExclusions

    patterns = [p for group in PRESETS.values() for p in group] + ["Extras/*", "*[1-3].mkv", "a?c.txt"]

    def reference(path):
        normalized = path.replace("\\", "/").lower()
        filename = normalized.rsplit("/", 1)[-1]
        for pattern in patterns:
            p = pattern.lower()
            if "/" not in p:
                if fnmatch.fnmatch(filename, p):
                    return True
            elif fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(normalized, f"*/{p}"):
                return True
        return False

    paths = [
        "Movie/Movie.mkv", "Movie/movie.NFO", "Movie/Sample/x.mkv", "sample/x.mkv", "Movie/sample.mkv",
        "Show/Season 01/poster.jpg", "Show/season01-poster.jpg", "x/extras/y.mkv", "Movie\\Proof\\p.jpg",
        "a/abc.txt", "a/ab.txt", "Show/Ep2.mkv", "Show/Ep4.mkv", "file.!qb", "dir.nfo/file.mkv", ".actors/a.jpg",
    ]
    compiled = CompiledExclusions(patterns=patterns)
    assert [compiled.is_excluded(p) for p in paths] == [reference(p) for p in paths]
