import pytest

from nazgarr import episode_orders as eo
from nazgarr.episode_orders import EpisodeOrder, OrderEpisode


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
    assert eo.fit(tmdb, {1: [1, 2, 3, 4, 5]}, pack=True) == {"score": 0.85, "matched": 5, "files": 5,
                                                            "complete_seasons": 0}


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
    from nazgarr.models import EpisodeOrderPreference, SonarrInstance

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

    monkeypatch.setattr("nazgarr.net_guard.check_url", lambda url: None)
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

    from nazgarr.upload_file_names import _EpisodeJob
    from nazgarr.upload_naming import season_token

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
