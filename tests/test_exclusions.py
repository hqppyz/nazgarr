from nazgarr.exclusions import compile_exclusions, parse_custom_patterns, parse_preset_keys


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


def test_presets_never_saved_enable_media_server_metadata_by_default():
    exclusions = compile_exclusions(None, None)
    assert exclusions.is_excluded("tv/Show/Season 01/Show - S01E01-thumb.jpg")
    assert exclusions.is_excluded("movies/Interstellar (2014)/poster.jpg")
    assert exclusions.is_excluded("movies/Interstellar (2014)/Interstellar.nfo")
    assert not exclusions.is_excluded("movies/Interstellar (2014)/Interstellar.mkv")
    assert not exclusions.is_excluded("movies/Interstellar (2014)/Interstellar.en.srt")


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

    from nazgarr.exclusions import PRESETS, CompiledExclusions

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
