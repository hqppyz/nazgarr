import pytest

from nazgarr.adapters.media_resolver.base import ResolvedMedia
from nazgarr.upload import identify as upload_identify
from nazgarr.upload.jobs import UploadJobError
from nazgarr.upload.source import scan_source
from tests.upload_helpers import FakeTMDB, tmdb_result, write_video


@pytest.mark.parametrize(("value", "expected"), [
    ("603", ("movie", 603)),
    ("tv/1399", ("tv", 1399)),
    ("movie:603", ("movie", 603)),
    ("https://www.themoviedb.org/tv/1399-game-of-thrones", ("tv", 1399)),
    ("https://themoviedb.org/movie/603-the-matrix?language=it", ("movie", 603)),
    ("abc", None),
])
def test_parse_tmdb_ref(value, expected):
    assert upload_identify.parse_tmdb_ref(value, "movie") == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("tt0133093", "tt0133093"), ("0133093", "tt0133093"),
    ("https://www.imdb.com/title/tt0133093/", "tt0133093"), ("x", None),
])
def test_normalize_imdb(value, expected):
    assert upload_identify.normalize_imdb(value) == expected


@pytest.fixture
def no_resolver(monkeypatch):
    class _Resolver:
        SOURCE = "filename_parser"
        resolved = None

        def resolve(self, file_path):
            return self.resolved

    resolver = _Resolver()
    monkeypatch.setattr(
        upload_identify.adapter_factory, "build_media_resolver", lambda session, arr_index=None: resolver
    )
    return resolver


def _with_tmdb(monkeypatch, fake):
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)


def test_resolver_first_then_search_prefers_the_year_and_dedupes(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "The.Matrix.1999.1080p.mkv")))
    no_resolver.resolved = ResolvedMedia(tmdb_id=603, content_type="movie", title="The Matrix", year=1999)
    fake = FakeTMDB(search={("movie", "The Matrix", 1999): [
        tmdb_result(9999, "The Matrix Revisited", 2001), tmdb_result(603, "The Matrix", 1999),
        tmdb_result(604, "The Matrix Reloaded", 1999), tmdb_result(605, "Other", 1999),
    ]})
    _with_tmdb(monkeypatch, fake)

    candidates = upload_identify.find_candidates(db_session, {}, layout)

    assert [c["tmdb_id"] for c in candidates] == [603, 604, 605, 9999]
    assert [c["source"] for c in candidates] == ["filename_parser", "search", "search", "search"]
    assert ("search", "tv", "The Matrix", 1999) not in fake.calls  # abbastanza risultati nel tipo rilevato


def test_few_results_also_search_the_other_type_and_retry_without_year(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Chernobyl.2019.1080p.mkv")))
    fake = FakeTMDB(search={
        ("movie", "Chernobyl", None): [tmdb_result(1, "Chernobyl Diaries", 2012)],
        ("tv", "Chernobyl", 2019): [tmdb_result(87108, "Chernobyl", 2019, "tv")],
    })
    _with_tmdb(monkeypatch, fake)

    candidates = upload_identify.find_candidates(db_session, {}, layout)

    # Dal più sicuro: stesso titolo e stesso anno (anche se serie) prima di un
    # titolo diverso di un altro anno.
    assert [(c["content_type"], c["tmdb_id"]) for c in candidates] == [("tv", 87108), ("movie", 1)]
    assert candidates[0]["confidence"] > candidates[1]["confidence"]


def test_forced_ids_are_the_only_candidates(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Show.S01E01.mkv")))
    no_resolver.resolved = ResolvedMedia(tmdb_id=1, content_type="tv")
    fake = FakeTMDB(
        details={("tv", 1399): {**tmdb_result(1399, "GoT", 2011, "tv"), "seasons": []}},
        find={("imdb", "tt0944947"): [tmdb_result(1399, "GoT", 2011, "tv")],
              ("tvdb", "121361"): [tmdb_result(1399, "GoT", 2011, "tv")]},
    )
    _with_tmdb(monkeypatch, fake)

    candidates = upload_identify.find_candidates(
        db_session, {"tmdb": "1399", "imdb": "0944947", "tvdb": 121361}, layout
    )

    assert [(c["tmdb_id"], c["source"]) for c in candidates] == [(1399, "forced_tmdb")]
    assert ("find", "imdb", "tt0944947") in fake.calls


def test_invalid_forced_tmdb_id_is_a_coded_error(db_session, tmp_path, monkeypatch, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Movie.2024.mkv")))
    _with_tmdb(monkeypatch, FakeTMDB())

    with pytest.raises(UploadJobError) as exc:
        upload_identify.find_candidates(db_session, {"tmdb": "nope"}, layout)
    assert exc.value.code == "upload_invalid_tmdb_id"


def test_without_tmdb_key_only_the_resolver_is_used(db_session, tmp_path, no_resolver):
    layout = scan_source(str(write_video(tmp_path / "Movie.2024.mkv")))
    no_resolver.resolved = ResolvedMedia(tmdb_id=7, content_type="movie", source="radarr")

    candidates = upload_identify.find_candidates(db_session, {"tmdb": "603"}, layout)

    assert [(c["tmdb_id"], c["source"]) for c in candidates] == [(7, "radarr")]


def test_a_title_in_the_tracker_language_is_matched_too(db_session, tmp_path, monkeypatch, no_resolver):
    # Il file ha il titolo italiano: in inglese TMDB lo trova, ma con un altro titolo.
    layout = scan_source(str(write_video(tmp_path / "Il.Signore.degli.Anelli.2001.1080p.mkv")))
    fake = FakeTMDB(search={
        ("movie", "Il Signore degli Anelli", 2001): [tmdb_result(120, "The Lord of the Rings", 2001)],
        ("movie", "Il Signore degli Anelli", 2001, "it"): [
            tmdb_result(120, "Il Signore degli Anelli - La compagnia dell'anello", 2001),
            tmdb_result(121, "Il Signore degli Anelli", 2001),  # solo in italiano
        ],
    })
    _with_tmdb(monkeypatch, fake)

    english_only = upload_identify.find_candidates(db_session, {}, layout)
    with_italian = upload_identify.find_candidates(db_session, {}, layout, ("it",))

    assert [c["tmdb_id"] for c in english_only] == [120]
    assert {c["tmdb_id"] for c in with_italian} == {120, 121}
    best_120 = next(c for c in with_italian if c["tmdb_id"] == 120)
    assert best_120["confidence"] > english_only[0]["confidence"]  # il titolo italiano conta


def test_the_italian_title_reaches_a_candidate_found_first_by_the_resolver(
    db_session, tmp_path, monkeypatch, no_resolver
):
    # Il resolver trova il film per primo; la ricerca in italiano trova lo
    # stesso film: il suo titolo italiano deve arrivare a quel candidato.
    layout = scan_source(str(write_video(tmp_path / "La.Grande.Bellezza.2013.1080p.mkv")))
    no_resolver.resolved = ResolvedMedia(tmdb_id=179144, content_type="movie", title="The Great Beauty", year=2013)
    fake = FakeTMDB(search={
        ("movie", "La Grande Bellezza", 2013): [tmdb_result(179144, "The Great Beauty", 2013)],
        ("movie", "La Grande Bellezza", 2013, "it"): [tmdb_result(179144, "La grande bellezza", 2013)],
    })
    _with_tmdb(monkeypatch, fake)

    [best] = upload_identify.find_candidates(db_session, {}, layout, ("it",))

    assert best["titles"] == ["La grande bellezza"]
    assert best["confidence"] == 1.0
    assert best["confidence_parts"]["title_matched"] == "La grande bellezza"


def test_auto_match_confirms_the_numbers_of_the_chosen_ordering(db_session, monkeypatch):
    """Come al match a mano: se l'ordinamento scelto non è quello dei file,
    stagione ed episodio confermati sono già tradotti (nome, file e campi
    del tracker usano la stessa numerazione)."""
    from types import SimpleNamespace

    from nazgarr.library import episode_orders
    from nazgarr.upload import jobs as upload_jobs

    job = SimpleNamespace(id=1, kind="episode", seasons_json="[2]", episode=1, forced_ids_json="{}",
                          title=None, year=None)
    orders = {
        "recommended": "tmdb:group:1", "warning": None,
        "orders": [{"key": "tmdb:group:1"}], "files_order": "tvdb:aired",
        # I file dicono S02E01, che nell'ordinamento scelto è S01E06.
        "found": {"tmdb:group:1": {1: [6]}, "tvdb:aired": {2: [1]}},
    }
    confirmed = {}
    monkeypatch.setattr(upload_identify, "auto_match_threshold", lambda session: 0.5)
    monkeypatch.setattr(upload_identify, "tmdb_client",
                        lambda session: SimpleNamespace(full_details=lambda *a: {"tvdb_id": 5}))
    monkeypatch.setattr(episode_orders, "for_job", lambda *a, **k: orders)
    monkeypatch.setattr(episode_orders, "snapshot", lambda result, key: {"chosen": {"key": key}})
    monkeypatch.setattr(upload_jobs, "confirm_match", lambda session, job, **kw: confirmed.update(kw))
    monkeypatch.setattr(upload_jobs, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(db_session, "commit", lambda: None)

    upload_identify._auto_match(db_session, job, [{"content_type": "tv", "tmdb_id": 96677, "confidence": 0.99}])

    assert (confirmed["seasons"], confirmed["episode"]) == ([1], 6)
    assert job.episode_order == "tmdb:group:1"


def test_numbers_in_keeps_the_files_numbers_without_found_episodes():
    from nazgarr.library import episode_orders

    assert episode_orders.numbers_in({"found": {}}, "x", "season_pack", [3], None) == ([3], None)
    assert episode_orders.numbers_in({"found": {"x": {"1": [1, 2], "2": [1]}}}, "x", "complete_pack", [5], None) \
        == ([1, 2], None)


def test_confirm_translates_only_when_asked_and_remembers_only_a_user_choice(db_session, monkeypatch):
    """Lo stesso servizio per il match a mano (numeri già tradotti, scelta
    ricordata) e per quello automatico (numeri dei file, niente preferenza)."""
    from types import SimpleNamespace

    from nazgarr.library import episode_orders
    from nazgarr.upload import jobs as upload_jobs

    orders = {"orders": [{"key": "tmdb:group:1"}, {"key": "tvdb:aired"}], "files_order": "tvdb:aired",
              "found": {"tmdb:group:1": {1: [6]}}}
    confirmed, remembered = [], []
    monkeypatch.setattr(upload_jobs, "confirm_match", lambda session, job, **kw: confirmed.append(kw))
    monkeypatch.setattr(episode_orders, "remember", lambda session, tmdb_id, key: remembered.append(key))

    def job():
        return SimpleNamespace(forced_ids_json="{}", episode_order=None, episode_order_json=None)

    manual, auto = job(), job()
    upload_identify.confirm(db_session, manual, content_type="tv", tmdb_id=1, kind="episode", seasons=[1],
                            episode=6, details=None, order_key="tmdb:group:1", orders=orders, remember=True)
    upload_identify.confirm(db_session, auto, content_type="tv", tmdb_id=1, kind="episode", seasons=[2],
                            episode=1, details=None, order_key="tmdb:group:1", orders=orders, translate=True)

    assert [(c["seasons"], c["episode"]) for c in confirmed] == [([1], 6), ([1], 6)]
    assert remembered == ["tmdb:group:1"]
    assert manual.episode_order == auto.episode_order == "tmdb:group:1"

    with pytest.raises(episode_orders.EpisodeOrderError):
        upload_identify.confirm(db_session, job(), content_type="tv", tmdb_id=1, kind="episode", seasons=[1],
                                episode=1, details=None, order_key="nope", orders=orders)
