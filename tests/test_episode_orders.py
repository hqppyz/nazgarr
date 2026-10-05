import pytest

from nazgarr.library import episode_orders as eo
from nazgarr.library.episode_orders import EpisodeOrder, OrderEpisode


def _order(key, seasons, source="tmdb", refs=True, dates=None):
    """seasons: {stagione: numero di episodi}; refs: riferimenti uguali ai numeri."""
    order = EpisodeOrder(key, key, source)
    for season, count in seasons.items():
        order.seasons[season] = [
            OrderEpisode(number=n, titles=[f"S{season}E{n}"], air_date=(dates or {}).get((season, n)),
                         refs=[(season, n)] if refs else [])
            for n in range(1, count + 1)
        ]
    return order


@pytest.fixture(autouse=True)
def _no_cache():
    eo._cache.clear()


def test_align_one_to_one_in_pairs_and_by_date():
    tmdb = _order("tmdb:default", {1: 10, 2: 7})
    # Stessi episodi, stagioni divise diversamente (le "parti" di Netflix): uno a uno.
    parts = _order("tvdb:alternate", {1: 5, 2: 5, 3: 7}, "tvdb", refs=False)
    eo.align_to(parts, tmdb)
    assert parts.seasons[2][0].refs == [(1, 6)] and parts.seasons[3][0].refs == [(2, 1)]
    # Trasmessi due alla volta: metà degli episodi, ognuno vale due.
    doubled = _order("tvdb:regional", {1: 5}, "tvdb", refs=False)
    eo.align_to(doubled, _order("tmdb:default", {1: 10}))
    assert doubled.seasons[1][1].refs == [(1, 3), (1, 4)]
    # E al contrario.
    split = _order("tvdb:dvd", {1: 4}, "tvdb", refs=False)
    eo.align_to(split, _order("tmdb:default", {1: 2}))
    assert [e.refs for e in split.seasons[1]] == [[(1, 1)], [(1, 1)], [(1, 2)], [(1, 2)]]
    # Conteggi che non tornano: per data di uscita.
    dates = {(1, 1): "2021-01-08", (1, 2): "2021-01-08", (1, 3): "2021-06-11"}
    ref = _order("tmdb:default", {1: 3}, dates=dates)
    odd = _order("tvdb:official", {1: 2}, "tvdb", refs=False, dates={(1, 1): "2021-01-08", (1, 2): "2021-06-11"})
    odd.seasons[1].append(OrderEpisode(number=3, titles=["extra"], air_date="2030-01-01"))
    odd.seasons[1].append(OrderEpisode(number=4, titles=["extra"], air_date="2031-01-01"))
    eo.align_to(odd, ref)
    assert [e.refs for e in odd.seasons[1]] == [[(1, 1), (1, 2)], [(1, 3)], [], []]


def test_translate_goes_through_the_reference_episodes():
    tmdb = _order("tmdb:default", {1: 10, 2: 7})
    parts = _order("tvdb:alternate", {1: 5, 2: 5, 3: 7}, "tvdb", refs=False)
    eo.align_to(parts, tmdb)
    assert eo.translate(parts, tmdb, 3, 2) == [(2, 2)]
    assert eo.translate(tmdb, parts, 1, 7) == [(2, 2)]
    doubled = _order("tvdb:regional", {1: 5}, "tvdb", refs=False)
    eo.align_to(doubled, _order("tmdb:default", {1: 10}))
    assert eo.translate(doubled, _order("tmdb:default", {1: 10}), 1, 2) == [(1, 3), (1, 4)]
    assert eo.translate(parts, tmdb, 9, 9) == []


def test_fit_counts_existing_episodes_and_complete_seasons():
    tmdb = _order("tmdb:default", {1: 10, 2: 7})
    parts = _order("tvdb:alternate", {1: 5, 2: 5, 3: 7})
    found = {3: [1, 2, 3, 4, 5, 6, 7]}  # un "S03" di 7 episodi
    assert eo.fit(parts, found, pack=True)["score"] == 1.0
    assert eo.fit(tmdb, found, pack=True)["score"] == 0.0
    # 5 file contro una stagione da 10: i numeri esistono, ma il numero di episodi no.
    assert eo.fit(tmdb, {1: [1, 2, 3, 4, 5]}, pack=True) == {"score": 0.625, "coverage": 1.0, "matched": 5,
                                                            "files": 5, "complete_seasons": 0}


class FakeTmdb:
    def __init__(self):
        self.seasons = {0: 1, 1: 10, 2: 7}

    def get(self, path, **params):
        if path == "/tv/96677" and not params:
            return {"seasons": [{"season_number": n} for n in self.seasons]}
        if path == "/tv/96677":
            return {f"season/{n}": {"episodes": [{"episode_number": e, "name": f"Ep {n}x{e}", "air_date": None}
                                                 for e in range(1, c + 1)]}
                    for n, c in self.seasons.items()}
        if path == "/tv/96677/external_ids":
            return {"tvdb_id": 375921}
        if path == "/tv/96677/episode_groups":
            return {"results": [{"id": "g1", "name": "Parts", "type": 4, "episode_count": 10},
                                {"id": "g2", "name": "Empty", "type": 4, "episode_count": 0}]}
        if path == "/tv/episode_group/g1":
            def part(order, numbers):
                return {"order": order, "episodes": [
                    {"season_number": 1, "episode_number": e, "order": i} for i, e in enumerate(numbers)]}
            return {"groups": [part(1, range(1, 6)), part(2, range(6, 11))]}
        raise AssertionError(path)


def test_tmdb_default_seasons_and_episode_groups():
    orders = eo.tmdb_orders(FakeTmdb(), 96677)
    default, group = orders
    assert default.key == "tmdb:default" and len(default.seasons[1]) == 10 and default.seasons[0][0].refs == [(0, 1)]
    assert group.key == "tmdb:group:g1" and group.label == "TMDB · Parts"
    assert group.seasons[2][0].number == 1 and group.seasons[2][0].refs == [(1, 6)]


class FakeSonarr:
    def __init__(self, instance):
        self.label = instance.label

    def get(self, path, **params):
        if path == "/api/v3/series":
            return [{"id": 7, "tmdbId": 96677, "tvdbId": 375921}]
        if path == "/api/v3/episode":
            return [{"seasonNumber": 1, "episodeNumber": e, "title": f"Capitolo {e}"} for e in range(1, 11)] + [
                {"seasonNumber": 2, "episodeNumber": e, "title": f"Capitolo {e}"} for e in range(1, 8)]
        raise AssertionError(path)


def test_the_best_fit_is_chosen_and_only_a_miss_on_tvdb_aired_warns(db_session):
    from nazgarr.core.models import EpisodeOrderPreference, SonarrInstance

    found = {2: [1, 2, 3, 4, 5]}  # un "S02" da 5: le parti di Netflix, non l'ordine aired
    # Senza Sonarr né chiave TVDB non si sa cosa sia TVDB aired: nessun avviso.
    alone = eo.build(db_session, 96677, 375921, found, pack=True, tmdb_api=FakeTmdb())
    assert alone["recommended"] == "tmdb:group:g1" and alone["warning"] is None

    db_session.add(SonarrInstance(label="sonarr", base_url="http://s", api_key="k"))
    db_session.commit()
    result = eo.build(db_session, 96677, 375921, found, pack=True, tmdb_api=FakeTmdb(), sonarr_factory=FakeSonarr)

    keys = [o["key"] for o in result["orders"]]
    assert keys == ["tmdb:default", "tmdb:group:g1", "sonarr:aired"]
    # Scelto quello che combacia meglio, con l'avviso: non è l'ordine di Sonarr.
    assert result["recommended"] == "tmdb:group:g1" and result["files_order"] == "tmdb:group:g1"
    assert result["warning"] == {"code": "files_not_tvdb_aired", "order": "tmdb:group:g1", "tvdb": "sonarr:aired"}
    # Gli episodi dei file tradotti: la parte 2 è la seconda metà della stagione 1.
    assert result["found"]["sonarr:aired"] == {1: [6, 7, 8, 9, 10]}

    # File che seguono TVDB aired: scelto quello, nessun avviso.
    aired = eo.build(db_session, 96677, 375921, {1: list(range(1, 11))}, pack=True, tmdb_api=FakeTmdb(),
                     sonarr_factory=FakeSonarr)
    assert aired["warning"] is None and aired["fits"][aired["recommended"]]["score"] == 1.0
    # A parità vince TVDB aired (qui anche TMDB combacia del tutto).
    assert aired["recommended"] == "sonarr:aired"

    # Senza episodi nei file: la scelta dell'ultima volta per la serie, poi TVDB aired.
    assert eo.build(db_session, 96677, 375921, {}, pack=True, tmdb_api=FakeTmdb(),
                    sonarr_factory=FakeSonarr)["recommended"] == "sonarr:aired"
    db_session.add(EpisodeOrderPreference(tmdb_id=96677, order_key="tmdb:default"))
    db_session.commit()
    assert eo.build(db_session, 96677, 375921, {}, pack=True, tmdb_api=FakeTmdb(),
                    sonarr_factory=FakeSonarr)["recommended"] == "tmdb:default"


def test_round_trip_through_a_dict():
    order = _order("tmdb:group:x", {1: 2})
    assert eo.EpisodeOrder.from_dict(order.to_dict()).episodes() == order.episodes()


def test_tvdb_api_logs_in_and_reads_every_season_type(monkeypatch):
    import httpx

    monkeypatch.setattr("nazgarr.core.net_guard.check_url", lambda url: None)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"data": {"token": "tok"}})
        if request.url.path.endswith("/extended"):
            return httpx.Response(200, json={"data": {"seasonTypes": [
                {"type": "official", "name": "Aired Order"}, {"type": "alternate", "name": "Netflix Parts"}]}})
        kind = request.url.path.rsplit("/", 1)[1]
        seasons = {"official": [(1, 10), (2, 7)], "alternate": [(1, 5), (2, 5), (3, 7)]}[kind]
        episodes = [{"seasonNumber": s, "number": e, "name": f"{s}x{e}"} for s, c in seasons for e in range(1, c + 1)]
        return httpx.Response(200, json={"data": {"episodes": episodes}})

    api = eo.TvdbApi("key", client=httpx.Client(base_url=eo.TVDB_API, transport=httpx.MockTransport(handler)))
    orders = eo.tvdb_orders(api, 375921)

    assert [(o.key, o.label) for o in orders] == [("tvdb:official", "TVDB · Aired Order"),
                                                  ("tvdb:alternate", "TVDB · Netflix Parts")]
    assert sorted(orders[1].seasons) == [1, 2, 3] and len(orders[1].seasons[3]) == 7
    assert seen[0][:2] == ("POST", "/v4/login") and all(h == "Bearer tok" for _m, _p, h in seen[1:])


def test_generated_episode_names_follow_the_chosen_ordering():
    import json
    from types import SimpleNamespace

    from nazgarr.upload.file_names import _EpisodeJob
    from nazgarr.upload.naming import season_token

    tmdb = _order("tmdb:default", {1: 10})
    parts = _order("tmdb:group:g1", {1: 5, 2: 5}, refs=False)
    eo.align_to(parts, tmdb)
    doubled = _order("tvdb:regional", {1: 5}, "tvdb", refs=False)
    eo.align_to(doubled, tmdb)

    def job(chosen, files):
        return SimpleNamespace(kind="season_pack", seasons_json="[2]", episode=None,
                               episode_order_json=json.dumps({"chosen": chosen.to_dict(), "files": files.to_dict()}))

    # File "S02E03" (le parti), scelto l'ordine TMDB: S01E08.
    one = _EpisodeJob(job(tmdb, parts), 2, 3)
    assert season_token(one.kind, json.loads(one.seasons_json), one.episode) == "S01E08"
    # File numerati uno a uno, scelto l'ordine con gli episodi accorpati: il file S01E04 è metà del 2.
    half = _EpisodeJob(job(doubled, tmdb), 1, 4)
    assert season_token(half.kind, json.loads(half.seasons_json), half.episode) == "S01E02"
    # Al contrario: un file dell'ordine accorpato copre due episodi.
    both = _EpisodeJob(job(tmdb, doubled), 1, 2)
    assert season_token(both.kind, json.loads(both.seasons_json), both.episode) == "S01E03E04"
    # Senza ordinamento scelto resta com'è.
    plain = _EpisodeJob(SimpleNamespace(kind="season_pack", seasons_json="[2]", episode=None,
                                        episode_order_json=None), 2, 3)
    assert season_token(plain.kind, json.loads(plain.seasons_json), plain.episode) == "S02E03"


def test_a_pack_numbered_after_another_ordering_is_mapped_to_the_library(db_session, tmp_path):
    from datetime import UTC, datetime

    from nazgarr.core.models import Disk, MediaFile, MediaItem
    from nazgarr.reseed import pipeline
    from nazgarr.torrents.layout import Layout, LayoutFile, LocalFiles, map_media_side

    disk = Disk(label="d", root_path=str(tmp_path), media_rel_path="media", torrents_rel_path="torrents")
    db_session.add(disk)
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    # La libreria come Sonarr (TVDB aired): la stagione 1 ha 10 episodi.
    for ep in range(1, 11):
        item = MediaItem(content_type="tv", tmdb_id=96677, season_number=1, episode_number=ep)
        db_session.add(item)
        db_session.commit()
        db_session.add(MediaFile(disk_id=disk.id, relative_path=f"media/Lupin/Season 01/Lupin - S01E{ep:02d}.mkv",
                                 size_bytes=1000 + ep, st_dev=1, inode=ep, media_item_id=item.id,
                                 last_scan_id=run.id, last_seen_at=datetime.now(UTC)))
    db_session.commit()
    local = LocalFiles.load(db_session)
    anchor = db_session.query(MediaFile).filter(MediaFile.relative_path.like("%S01E06%")).one()
    # Il pack sul tracker: "Parte 2", numerato S02E01-05.
    layout = Layout("Lupin.S02", [LayoutFile(f"Lupin.S02E0{e}.mkv", 1005 + e, True) for e in range(1, 6)])

    plain = map_media_side(layout, anchor, local)
    assert [m.local for m in plain] == [None] * 5  # coi soli numeri del torrent non si trova niente

    translator = eo.Translator(db_session, tmdb_api=FakeTmdb())
    mapped = map_media_side(layout, anchor, local, translator=translator)
    assert [m.local.relative_path.rsplit(" - ", 1)[1] for m in mapped] == [
        f"S01E{e:02d}.mkv" for e in range(6, 11)]


def test_library_series_orderings_follow_the_library_numbering(client, monkeypatch):
    from nazgarr.core import settings_repo
    from nazgarr.core.models import MediaItem

    monkeypatch.setattr(eo, "TmdbApi", lambda key: FakeTmdb())
    session = client.app.state.session_factory()
    try:
        settings_repo.set_setting(session, "tmdb_api_key", "k")
        session.add_all([MediaItem(content_type="tv", tmdb_id=96677, season_number=1, episode_number=e)
                         for e in range(1, 11)])
        session.commit()
    finally:
        session.close()

    body = client.get("/api/library/items/tv/96677/episode-orders").json()

    assert body["recommended"] == "tmdb:default" and body["warning"] is None
    assert [o["key"] for o in body["orders"]] == ["tmdb:default", "tmdb:group:g1"]
    # Gli stessi file nelle "parti": la seconda metà della stagione 1 è la stagione 2.
    assert body["found"]["tmdb:group:g1"] == {"1": [1, 2, 3, 4, 5], "2": [1, 2, 3, 4, 5]}


def test_a_library_in_joined_order_is_not_taken_for_aired_segments(db_session, monkeypatch):
    """Come Dexter's Laboratory: TVDB aired divide ogni episodio in 3
    segmenti (S01 da 38), "Joined Order" no (S01 da 13), come la libreria."""
    import httpx

    from nazgarr.core.models import SonarrInstance

    monkeypatch.setattr("nazgarr.core.net_guard.check_url", lambda url: None)

    class Tmdb:
        def get(self, path, **params):
            if path == "/tv/4229/external_ids":
                return {"tvdb_id": 76015}
            if path == "/tv/4229" and not params:
                return {"seasons": [{"season_number": 1}]}
            if path == "/tv/4229":
                episodes = [{"episode_number": e, "name": f"Ep {e}", "air_date": f"1996-{e:02d}-01"}
                            for e in range(1, 14)]
                return {"season/1": {"episodes": episodes}}
            if path == "/tv/4229/episode_groups":
                return {"results": []}
            raise AssertionError(path)

    class Sonarr:
        def __init__(self, instance):
            pass

        def get(self, path, **params):
            if path == "/api/v3/series":
                return [{"id": 1, "tmdbId": 4229, "tvdbId": 76015}]
            # 38 segmenti, tre (o due) per data.
            return [{"seasonNumber": 1, "episodeNumber": n, "title": f"Segment {n}",
                     "airDate": f"1996-{min((n + 2) // 3, 13):02d}-01"} for n in range(1, 39)]

    def tvdb(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"data": {"token": "t"}})
        if request.url.path.endswith("/extended"):
            return httpx.Response(200, json={"data": {"seasonTypes": [
                {"type": "official", "name": "Aired Order"}, {"type": "alternate", "name": "Joined Order"}]}})
        kind = request.url.path.rsplit("/", 1)[1]
        count = 38 if kind == "official" else 13
        return httpx.Response(200, json={"data": {"episodes": [
            {"seasonNumber": 1, "number": n, "name": f"{kind} {n}"} for n in range(1, count + 1)]}})

    db_session.add(SonarrInstance(label="Main", base_url="http://s", api_key="k"))
    db_session.commit()
    api = eo.TvdbApi("k", client=httpx.Client(base_url=eo.TVDB_API, transport=httpx.MockTransport(tvdb)))
    library = {1: list(range(1, 14))}

    result = eo.build(db_session, 4229, 76015, library, pack=True, tmdb_api=Tmdb(), tvdb_api=api,
                      sonarr_factory=Sonarr)

    labels = {o["key"]: o["label"] for o in result["orders"]}
    assert labels["tvdb:alternate"] == "TVDB · Joined Order" and "tvdb:official" not in labels
    assert result["recommended"] == "tvdb:alternate"
    assert result["warning"] == {"code": "files_not_tvdb_aired", "order": "tvdb:alternate", "tvdb": "sonarr:aired"}
    assert result["fits"]["sonarr:aired"]["score"] < 1.0


def test_episode_group_seasons_come_from_their_names_or_start_at_one():
    parts = [{"order": 0, "name": "Season 1"}, {"order": 1, "name": "Season 2"}]
    assert [eo._group_season(p, i, parts) for i, p in enumerate(parts)] == [1, 2]
    named = [{"order": 0, "name": "Specials"}, {"order": 1, "name": "Stagione 1"}, {"order": 2, "name": "Part 3"}]
    assert [eo._group_season(p, i, named) for i, p in enumerate(named)] == [0, 1, 3]
    # Senza numeri nel nome: dalla posizione, da 1 se parte da 0 senza speciali.
    bare = [{"order": 0, "name": "First"}, {"order": 1, "name": "Second"}]
    assert [eo._group_season(p, i, bare) for i, p in enumerate(bare)] == [1, 2]
    with_specials = [{"order": 0, "name": "Specials"}, {"order": 1, "name": "Main"}]
    assert [eo._group_season(p, i, with_specials) for i, p in enumerate(with_specials)] == [0, 1]



def test_without_a_tvdb_key_the_tmdb_production_group_fits_a_joined_library(db_session):
    counts = {1: 13, 2: 39, 3: 13, 4: 13}
    segments = {1: 38, 2: 108, 3: 36, 4: 38}

    class Tmdb:
        def get(self, path, **params):
            if path == "/tv/4229" and not params:
                return {"seasons": [{"season_number": n} for n in segments]}
            if path == "/tv/4229":
                return {f"season/{n}": {"episodes": [{"episode_number": e} for e in range(1, c + 1)]}
                        for n, c in segments.items()}
            if path == "/tv/4229/episode_groups":
                return {"results": [{"id": "prod", "name": "TV", "type": 6, "episode_count": 78}]}
            if path == "/tv/episode_group/prod":
                return {"groups": [
                    {"order": n - 1, "name": f"Season {n}", "episodes": [
                        {"season_number": n, "episode_number": 3 * e - 2, "order": e - 1} for e in range(1, c + 1)]}
                    for n, c in counts.items()]}
            raise AssertionError(path)

    library = {n: list(range(1, c + 1)) for n, c in counts.items()}
    result = eo.build(db_session, 4229, None, library, pack=True, tmdb_api=Tmdb())

    assert result["recommended"] == "tmdb:group:prod"
    group = next(o for o in result["orders"] if o["key"] == "tmdb:group:prod")
    assert [(s["season_number"], len(s["episodes"])) for s in group["seasons"]] == [(1, 13), (2, 39), (3, 13), (4, 13)]


def test_a_library_numbered_by_sonarr_segments_is_shown_in_the_order_its_files_follow(db_session):
    """Dexter's Laboratory com'è davvero: Sonarr numera in TVDB aired, tre
    segmenti per file, e la libreria registra il primo (1, 4, 7...). I file
    però sono 13 per stagione, come il gruppo TV di TMDB."""
    from nazgarr.core.models import SonarrInstance

    segments = {1: 39, 3: 39}

    class Tmdb:
        def get(self, path, **params):
            if path == "/tv/4229" and not params:
                return {"seasons": [{"season_number": n} for n in segments]}
            if path == "/tv/4229":
                return {f"season/{n}": {"episodes": [{"episode_number": e} for e in range(1, c + 1)]}
                        for n, c in segments.items()}
            if path == "/tv/4229/episode_groups":
                return {"results": [{"id": "prod", "name": "TV", "type": 6, "episode_count": 26}]}
            if path == "/tv/episode_group/prod":
                return {"groups": [{"order": i, "name": f"Season {n}", "episodes": [
                    {"season_number": n, "episode_number": 3 * e - 2, "order": e - 1} for e in range(1, 14)]}
                    for i, n in enumerate(segments)]}
            raise AssertionError(path)

    class Sonarr:
        def __init__(self, instance):
            pass

        def get(self, path, **params):
            if path == "/api/v3/series":
                return [{"id": 1, "tmdbId": 4229}]
            return [{"seasonNumber": n, "episodeNumber": e} for n, c in segments.items() for e in range(1, c + 1)]

    db_session.add(SonarrInstance(label="Main", base_url="http://s", api_key="k"))
    db_session.commit()
    library = {n: list(range(1, 38, 3)) for n in segments}  # 13 file, numerati col primo segmento

    result = eo.build(db_session, 4229, None, library, pack=True, tmdb_api=Tmdb(), sonarr_factory=Sonarr)

    assert result["fits"]["tmdb:group:prod"]["score"] > result["fits"]["sonarr:aired"]["score"]
    assert result["recommended"] == "tmdb:group:prod"  # la forma delle stagioni: 13 file, 13 episodi
    assert result["files_order"] == "sonarr:aired"  # i numeri registrati, da cui si traduce
    assert result["found"]["tmdb:group:prod"] == {1: list(range(1, 14)), 3: list(range(1, 14))}


def test_cached_orders_are_copies_and_sonarr_is_asked_once(db_session):
    """align_to riallinea gli ordinamenti che riceve: quelli in cache non
    cambiano. La lista delle serie di Sonarr si chiede una volta, non a
    ogni scheda, match e serie del reseeding."""
    from nazgarr.core.models import SonarrInstance

    first = eo.tmdb_orders(FakeTmdb(), 96677)
    first[0].seasons[1][0].refs = [(9, 9)]  # come farebbe align_to
    again = eo.tmdb_orders(FakeTmdb(), 96677)
    assert again[0].seasons[1][0].refs == [(1, 1)]

    asked = []

    class CountingSonarr(FakeSonarr):
        def get(self, path, **params):
            asked.append(path)
            return super().get(path, **params)

    db_session.add(SonarrInstance(label="sonarr", base_url="http://s", api_key="k"))
    db_session.commit()
    for _ in range(3):
        assert eo.sonarr_order(db_session, 96677, 375921, CountingSonarr) is not None
    assert asked == ["/api/v3/series", "/api/v3/episode"]


def test_the_cache_keeps_a_bounded_number_of_entries(monkeypatch):
    monkeypatch.setattr(eo, "_CACHE_MAX", 3)
    for n in range(5):
        eo._cached(("k", n), lambda n=n: n)
    assert list(eo._cache) == [("k", 2), ("k", 3), ("k", 4)]
