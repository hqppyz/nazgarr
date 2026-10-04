
from nazgarr import media_resolution, pipeline
from nazgarr.adapters.media_resolver.base import MediaResolverAdapter, ResolvedMedia
from nazgarr.models import Disk, MediaFile, MediaItem
from tests.fakes import make_media_file


class FakeResolver(MediaResolverAdapter):
    SOURCE = "filename_parser"

    def __init__(self, results: dict[str, ResolvedMedia | None]):
        # results keyed by relative_path piece contained in the abs_path, per test comodità
        self._results = results

    def resolve(self, file_path: str) -> ResolvedMedia | None:
        for key, value in self._results.items():
            if key in file_path:
                if isinstance(value, Exception):
                    raise value
                return value
        return None


def _setup(db_session):
    disk = Disk(label="disk1", root_path="/mnt/disk1", media_rel_path="movies")
    db_session.add(disk)
    db_session.commit()
    run = pipeline.start_run(db_session, run_type="manual")
    return disk, run


def test_resolves_and_creates_media_item(db_session, tmp_path):
    disk, run = _setup(db_session)
    make_media_file(db_session, disk, "movies/Interstellar.2014.mkv", run)

    resolver = FakeResolver({
        "Interstellar": ResolvedMedia(tmdb_id=157336, content_type="movie", poster_path=None),
    })

    counts = media_resolution.resolve_unmatched_media_files(db_session, resolver, str(tmp_path / "posters"))

    assert counts == {"resolved": 1, "unresolved": 0, "excluded": 0, "corrected": 0}
    mf = db_session.query(MediaFile).one()
    assert mf.media_item_id is not None
    assert mf.resolver_source == "filename_parser"
    media_item = db_session.query(MediaItem).one()
    assert media_item.tmdb_id == 157336
    assert media_item.content_type == "movie"


def test_two_files_same_movie_share_one_media_item(db_session, tmp_path):
    disk, run = _setup(db_session)
    make_media_file(db_session, disk, "movies/Interstellar.2014.mkv", run)
    make_media_file(db_session, disk, "movies/Interstellar.2014.Extended.mkv", run)

    resolver = FakeResolver({
        "Interstellar": ResolvedMedia(tmdb_id=157336, content_type="movie"),
    })

    counts = media_resolution.resolve_unmatched_media_files(db_session, resolver, str(tmp_path / "posters"))

    assert counts == {"resolved": 2, "unresolved": 0, "excluded": 0, "corrected": 0}
    assert db_session.query(MediaItem).count() == 1


def test_two_episodes_same_show_get_distinct_media_items(db_session, tmp_path):
    disk, run = _setup(db_session)
    make_media_file(db_session, disk, "movies/GoT.S03E01.mkv", run)
    make_media_file(db_session, disk, "movies/GoT.S03E09.mkv", run)

    resolver = FakeResolver({
        "S03E01": ResolvedMedia(tmdb_id=1399, content_type="tv", season_number=3, episode_number=1),
        "S03E09": ResolvedMedia(tmdb_id=1399, content_type="tv", season_number=3, episode_number=9),
    })

    media_resolution.resolve_unmatched_media_files(db_session, resolver, str(tmp_path / "posters"))

    assert db_session.query(MediaItem).count() == 2


def test_unresolvable_file_counted_as_unresolved(db_session, tmp_path):
    disk, run = _setup(db_session)
    make_media_file(db_session, disk, "movies/Unknown.Thing.mkv", run)

    resolver = FakeResolver({})  # nessun match per nessun file

    counts = media_resolution.resolve_unmatched_media_files(db_session, resolver, str(tmp_path / "posters"))

    assert counts == {"resolved": 0, "unresolved": 1, "excluded": 0, "corrected": 0}
    mf = db_session.query(MediaFile).one()
    assert mf.media_item_id is None


def test_resolver_exception_on_one_file_does_not_abort_the_rest(db_session, tmp_path):
    disk, run = _setup(db_session)
    make_media_file(db_session, disk, "movies/Broken.mkv", run)
    make_media_file(db_session, disk, "movies/Interstellar.2014.mkv", run)

    resolver = FakeResolver({
        "Broken": RuntimeError("network error"),
        "Interstellar": ResolvedMedia(tmdb_id=157336, content_type="movie"),
    })

    counts = media_resolution.resolve_unmatched_media_files(db_session, resolver, str(tmp_path / "posters"))

    assert counts == {"resolved": 1, "unresolved": 1, "excluded": 0, "corrected": 0}


def test_already_resolved_files_are_skipped(db_session, tmp_path):
    disk, run = _setup(db_session)
    mf = make_media_file(db_session, disk, "movies/Interstellar.2014.mkv", run)
    existing_item = MediaItem(content_type="movie", tmdb_id=1)
    db_session.add(existing_item)
    db_session.commit()
    mf.media_item_id = existing_item.id
    db_session.commit()

    def _unreachable(*args, **kwargs):
        raise AssertionError("non deve richiamare il resolver per un file già risolto")

    resolver = FakeResolver({})
    resolver.resolve = _unreachable

    counts = media_resolution.resolve_unmatched_media_files(db_session, resolver, str(tmp_path / "posters"))

    assert counts == {"resolved": 0, "unresolved": 0, "excluded": 0, "corrected": 0}


def test_excluded_files_are_never_resolved(db_session, tmp_path):
    from nazgarr import settings_repo

    settings_repo.set_setting(db_session, "exclusion_presets", "scene_junk")
    disk, run = _setup(db_session)
    make_media_file(db_session, disk, "movies/Interstellar.2014-sample.mkv", run)

    class NeverCalled(FakeResolver):
        def resolve(self, file_path):
            raise AssertionError("un file escluso non deve mai arrivare al resolver")

    counts = media_resolution.resolve_unmatched_media_files(db_session, NeverCalled({}), str(tmp_path / "posters"))

    assert counts == {"resolved": 0, "unresolved": 0, "excluded": 1, "corrected": 0}


def _resolved_by_name(db_session, disk, run, relative_path, tmdb_id):
    mf = make_media_file(db_session, disk, relative_path, run)
    item = MediaItem(content_type="movie", tmdb_id=tmdb_id)
    db_session.add(item)
    db_session.commit()
    mf.media_item_id, mf.resolver_source = item.id, "filename_parser"
    db_session.commit()
    return mf


def test_files_identified_by_name_are_reread_once_when_the_rules_change(db_session, tmp_path):
    disk, run = _setup(db_session)
    mf = _resolved_by_name(db_session, disk, run, "movies/Mission Impossible - Fallout (2018).mkv", 954)
    calls = []

    class Resolver(FakeResolver):
        def resolve(self, file_path):
            calls.append(file_path)
            return ResolvedMedia(tmdb_id=353081, content_type="movie")

    resolver = Resolver({})
    posters = str(tmp_path / "posters")

    counts = media_resolution.resolve_unmatched_media_files(db_session, resolver, posters)

    assert counts["corrected"] == 1
    assert mf.media_item.tmdb_id == 353081
    media_resolution.resolve_unmatched_media_files(db_session, resolver, posters)
    assert len(calls) == 1  # una tantum: la run dopo non rilegge più


def test_a_file_that_cannot_be_reread_keeps_its_identity(db_session, tmp_path):
    disk, run = _setup(db_session)
    mf = _resolved_by_name(db_session, disk, run, "movies/Some Movie (2001).mkv", 42)

    counts = media_resolution.resolve_unmatched_media_files(db_session, FakeResolver({}), str(tmp_path / "p"))

    assert counts == {"resolved": 0, "unresolved": 0, "excluded": 0, "corrected": 0}
    assert mf.media_item.tmdb_id == 42


def test_radarr_identity_wins_over_the_one_guessed_from_the_name(db_session, tmp_path):
    from nazgarr import settings_repo
    from nazgarr.arr import ArrIdentity, ArrIndex

    disk, run = _setup(db_session)
    settings_repo.set_setting(db_session, media_resolution.IDENTITY_RULES_KEY, media_resolution.IDENTITY_RULES_VERSION)
    mf = _resolved_by_name(db_session, disk, run, "movies/Mission Impossible (2023)/MI.2023.mkv", 954)
    untouched = _resolved_by_name(db_session, disk, run, "movies/Other (2001)/Other.mkv", 7)
    index = ArrIndex()
    index.add_identity("/radarr/Mission Impossible (2023)/MI.2023.mkv", 1,
                       ArrIdentity(source="radarr", content_type="movie", tmdb_id=575264))

    class Resolver(FakeResolver):  # l'ArrResolver reale legge la dimensione dal disco
        def resolve(self, file_path):
            assert "Other" not in file_path, "un file che Radarr non conosce non si rilegge"
            return ResolvedMedia(tmdb_id=575264, content_type="movie", source="radarr")

    counts = media_resolution.resolve_unmatched_media_files(
        db_session, Resolver({}), str(tmp_path / "p"), arr_index=index
    )

    assert counts["corrected"] == 1
    assert (mf.media_item.tmdb_id, mf.resolver_source) == (575264, "radarr")
    assert untouched.media_item.tmdb_id == 7
