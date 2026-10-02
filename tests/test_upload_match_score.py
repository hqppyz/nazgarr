from nazgarr.upload_match_score import scored


def _c(tmdb_id, title, year, content_type="movie", source="search", original=None):
    return {"tmdb_id": tmdb_id, "title": title, "original_title": original, "year": year,
            "content_type": content_type, "source": source}


def test_same_title_and_year_is_sure():
    [best] = scored([_c(1, "The Matrix", 1999)], "The Matrix", 1999, "movie")
    assert best["confidence"] == 1.0


def test_forced_ids_and_radarr_sonarr_win():
    assert scored([_c(1, "x", None, source="forced_tmdb")], "y", None, "movie")[0]["confidence"] == 1.0
    assert scored([_c(1, "x", None, source="radarr")], "y", None, "movie")[0]["confidence"] == 0.97


def test_a_wrong_year_or_type_lowers_it():
    [year_off] = scored([_c(1, "Dune", 1984)], "Dune", 2021, "movie")
    [one_off] = scored([_c(1, "Dune", 2020)], "Dune", 2021, "movie")
    [tv] = scored([_c(1, "Dune", 2021, "tv")], "Dune", 2021, "movie")
    assert year_off["confidence"] == 0.5 and one_off["confidence"] == 0.85 and tv["confidence"] == 0.6


def test_the_original_title_counts_too():
    [best] = scored([_c(1, "Spirited Away", 2001, original="Sen to Chihiro no Kamikakushi")],
                    "Sen to Chihiro no Kamikakushi", 2001, "movie")
    assert best["confidence"] == 1.0


def test_two_near_equal_candidates_are_ambiguous():
    first, second, other = scored(
        [_c(1, "Hamlet", 1996), _c(2, "Hamlet", 1996), _c(3, "Hamlet 2", 2008)], "Hamlet", 1996, "movie"
    )
    # Due film identici: nessuno dei due passa da solo la soglia di default (0.9).
    assert first["confidence"] == second["confidence"] == 0.9
    assert first["ambiguous"] and second["ambiguous"]
    assert other["confidence"] < 0.9 and other["tmdb_id"] == 3
