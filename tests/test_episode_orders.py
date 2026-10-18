import pytest

from nazgarr.library import episode_orders as eo
from nazgarr.library.episode_orders import EpisodeOrder, OrderEpisode


def _order(key, seasons, source="tmdb", refs=True, dates=None):
    """seasons: {stagione: numero di episodi}; refs: riferimenti uguali ai numeri.
    Titoli generici ("Episode 3"): non dicono quale episodio è, contano posizione e date."""
    order = EpisodeOrder(key, key, source)
    for season, count in seasons.items():
        order.seasons[season] = [
            OrderEpisode(number=n, titles=[f"Episode {n}"], air_date=(dates or {}).get((season, n)),
                         refs=[(season, n)] if refs else [])
            for n in range(1, count + 1)
        ]
    return order


@pytest.fixture(autouse=True)
def _no_cache():
    eo.clear_cache()


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


def _weekly(start: str, count: int, shift_days: int = 0) -> list[str]:
    from datetime import date, timedelta

    first = date.fromisoformat(start)
    return [(first + timedelta(days=7 * i + shift_days)).isoformat() for i in range(count)]


def _pilot_and_split_finale(shift_days: int = 0):
    """TMDB: il pilot fra gli speciali, 10 + 10 episodi, il finale diviso in
    due (E09 ed E10 lo stesso giorno). Sonarr: il pilot in S01 (11), il
    finale intero (9). I totali tornano (20 e 20), le posizioni no: dal
    pilot in poi tutto sfasato di uno. Titoli generici: non aiutano."""
    s1, s2 = _weekly("2020-01-08", 10), _weekly("2020-09-02", 9)
    tmdb_dates = {**{(1, n): d for n, d in enumerate(s1, 1)}, **{(2, n): d for n, d in enumerate(s2, 1)},
                  (2, 10): s2[-1]}
    tmdb = _order("tmdb:default", {1: 10, 2: 10}, dates=tmdb_dates)
    shifted = _weekly("2020-01-01", 11, shift_days)  # il pilot una settimana prima
    sonarr_dates = {**{(1, n): d for n, d in enumerate(shifted, 1)},
                    **{(2, n): d for n, d in enumerate(_weekly("2020-09-02", 9, shift_days), 1)}}
    sonarr = _order("sonarr:aired", {1: 11, 2: 9}, "sonarr", refs=False, dates=sonarr_dates)
    return tmdb, sonarr


def test_counts_that_match_by_coincidence_fall_back_to_the_air_dates():
    """Decisione dell'utente, 2026-10-18 (audit 2026-10-18): per posizione 19
    coppie su 20 avevano le date a una settimana l'una dall'altra, e ogni
    traduzione della serie era sbagliata di uno."""
    tmdb, sonarr = _pilot_and_split_finale()
    eo.align_to(sonarr, tmdb)
    s1, s2 = sonarr.seasons[1], sonarr.seasons[2]
    assert s1[0].refs == []  # il pilot: per TMDB è uno speciale
    assert [e.refs for e in s1[1:4]] == [[(1, 1)], [(1, 2)], [(1, 3)]]
    assert s2[0].refs == [(2, 1)] and s2[8].refs == [(2, 9), (2, 10)]  # il finale intero vale le due parti
    assert eo.translate(sonarr, tmdb, 1, 11) == [(1, 10)]
    # Le date di Sonarr un giorno dopo (il fuso orario di una fonte): uguale.
    tmdb, sonarr = _pilot_and_split_finale(shift_days=1)
    eo.align_to(sonarr, tmdb)
    assert sonarr.seasons[1][0].refs == [] and sonarr.seasons[1][1].refs == [(1, 1)]
    assert sonarr.seasons[2][8].refs == [(2, 9), (2, 10)]


def test_positions_stay_when_the_dates_agree_within_a_few_days():
    """Stessi episodi, date a uno-tre giorni (fusi orari, la prima in un
    altro paese): resta l'allineamento per posizione."""
    tmdb = _order("tmdb:default", {1: 10}, dates={(1, n): d for n, d in enumerate(_weekly("2021-03-01", 10), 1)})
    for shift in (1, 3, -2):
        tvdb = _order("tvdb:official", {1: 10}, "tvdb", refs=False,
                      dates={(1, n): d for n, d in enumerate(_weekly("2021-03-01", 10, shift), 1)})
        eo.clear_cache()
        eo.align_to(tvdb, tmdb)
        assert [e.refs for e in tvdb.seasons[1]] == [[(1, n)] for n in range(1, 11)], shift
    # Una sola coppia lontana su dieci, o date quasi tutte assenti: posizione.
    one_off = _order("tvdb:official", {1: 10}, "tvdb", refs=False,
                     dates={(1, n): d for n, d in enumerate(_weekly("2021-03-01", 10), 1)} | {(1, 4): "2022-01-01"})
    sparse = _order("tvdb:dvd", {1: 10}, "tvdb", refs=False, dates={(1, 2): "2030-01-01"})
    for order in (one_off, sparse):
        eo.align_to(order, tmdb)
        assert [e.refs for e in order.seasons[1]] == [[(1, n)] for n in range(1, 11)]
    # Uscita tutta in un giorno: le date non distinguono, la posizione resta.
    drop = {(1, n): "2021-03-01" for n in range(1, 11)}
    netflix = _order("tvdb:official", {1: 10}, "tvdb", refs=False, dates=drop)
    eo.align_to(netflix, _order("tmdb:default", {1: 10}, dates=drop))
    assert netflix.seasons[1][6].refs == [(1, 7)]


def test_a_one_day_release_on_one_side_only_keeps_the_positions():
    """Audit 2026-10-18 (verifica del fix): TVDB con tutti gli episodi nel
    giorno dello streaming, TMDB con le settimane della trasmissione. Per
    data andrebbero tutti su (1, 1); le date di una parte non distinguono
    le posizioni, e restano quelle. Anche al contrario."""
    weekly = {(1, n): d for n, d in enumerate(_weekly("2021-03-01", 8), 1)}
    drop = {(1, n): "2021-03-01" for n in range(1, 9)}
    tvdb = _order("tvdb:official", {1: 8}, "tvdb", refs=False, dates=drop)
    eo.align_to(tvdb, _order("tmdb:default", {1: 8}, dates=weekly))
    assert [e.refs for e in tvdb.seasons[1]] == [[(1, n)] for n in range(1, 9)]
    eo.clear_cache()
    tvdb = _order("tvdb:official", {1: 8}, "tvdb", refs=False, dates=weekly)
    eo.align_to(tvdb, _order("tmdb:default", {1: 8}, dates=drop))
    assert [e.refs for e in tvdb.seasons[1]] == [[(1, n)] for n in range(1, 9)]


def test_a_few_dated_pairs_do_not_decide_for_the_whole_show():
    """Audit 2026-10-18 (verifica del fix): 20 episodi, solo 3 con la data da
    tutte e due le parti, 2 lontani. Per data 19 su 20 restavano senza
    riferimenti: meno di metà delle coppie con le date non decide."""
    days = _weekly("2021-03-01", 20)
    tmdb = _order("tmdb:default", {1: 20}, dates={(1, n): d for n, d in enumerate(days, 1)})
    tvdb = _order("tvdb:official", {1: 20}, "tvdb", refs=False,
                  dates={(1, 1): days[0], (1, 5): "2022-06-01", (1, 9): "2023-01-01"})
    eo.align_to(tvdb, tmdb)
    assert [e.refs for e in tvdb.seasons[1]] == [[(1, n)] for n in range(1, 21)]


def test_halves_aired_together_still_fall_back_to_dates():
    """Le due metà di un episodio con la stessa data contano una volta: la
    metà sfasata torna per data anche col controllo delle date ripetute."""
    days = _weekly("2022-01-05", 6)
    tmdb = _order("tmdb:default", {1: 5}, dates={(1, n): days[n] for n in range(1, 6)})  # dalla seconda settimana
    halves = _order("tvdb:dvd", {1: 10}, "tvdb", refs=False,
                    dates={(1, n): days[(n - 1) // 2] for n in range(1, 11)})
    eo.align_to(halves, tmdb)
    refs = [e.refs for e in halves.seasons[1]]
    assert refs[:2] == [[], []]  # la prima settimana: TMDB non ce l'ha
    assert refs[2:4] == [[(1, 1)], [(1, 1)]] and refs[8:] == [[(1, 4)], [(1, 4)]]


def test_titles_still_win_after_the_fall_back_to_dates():
    tmdb, sonarr = _pilot_and_split_finale()
    tmdb.seasons[1][4].titles = ["The Long Night"]
    sonarr.seasons[1][2].titles = ["The Long Night"]  # il titolo dice E05, la data E02
    eo.align_to(sonarr, tmdb)
    assert sonarr.seasons[1][2].refs == [(1, 5)] and sonarr.seasons[1][3].refs == [(1, 3)]


def test_pairs_of_episodes_fall_back_to_dates_too():
    """Il doppio e la metà passano dallo stesso controllo."""
    days = _weekly("2022-01-05", 10)
    tmdb = _order("tmdb:default", {1: 10}, dates={(1, n): d for n, d in enumerate(days, 1)})
    # Cinque episodi doppi, trasmessi con le date delle parti dispari: per coppie, giusti.
    doubled = _order("tvdb:regional", {1: 5}, "tvdb", refs=False,
                     dates={(1, n): days[2 * (n - 1)] for n in range(1, 6)})
    eo.align_to(doubled, tmdb)
    assert doubled.seasons[1][1].refs == [(1, 3), (1, 4)]
    # Cinque episodi con le date delle ultime cinque parti: per coppie sarebbero sbagliati.
    late = _order("tvdb:regional", {1: 5}, "tvdb", refs=False, dates={(1, n): days[4 + n] for n in range(1, 6)})
    eo.align_to(late, tmdb)
    assert [e.refs for e in late.seasons[1]] == [[(1, 6)], [(1, 7)], [(1, 8)], [(1, 9)], [(1, 10)]]


def test_a_dvd_order_of_two_segment_episodes_is_aligned_by_title():
    # Iron Man and His Awesome Friends: su TMDB a segmenti, nell'ordine DVD di
    # TVDB due per episodio ("A / B") e quasi tutti con la stessa data. Per
    # data il file S01E03 finiva su DVD E02-E06 e dal S01E05 su niente
    # (segnalato il 2026-10-15). Con i refusi delle due fonti.
    segments = [("Enter the Iron Friends", "2025-08-11"), ("Amadeus Cho's Eggcellent Eggventure!", "2025-08-11"),
                ("Great Expo-tations", "2025-08-12"), ("Bouncy Boots", "2025-08-12"),
                ("Totally Awesome Beach Day", "2025-08-13"), ("Swarm Stinks It Up", "2025-08-13"),
                ("The Ultron Song", "2025-08-14"), ("Black Panther and the Boot", "2025-08-14"),
                ("Iron Friends Trick or Treats!", "2025-09-29"), ("Leaping into Fall", "2025-09-29"),
                ("Baby Vision", "2025-11-03"), ("Ironheart's Racing Adventure", "2025-11-03"),
                ("Episode 13", "2026-06-11")]
    tmdb = EpisodeOrder("tmdb:default", "TMDB", "tmdb", {1: [
        OrderEpisode(n, [title], date, [(1, n)]) for n, (title, date) in enumerate(segments, 1)]})
    dvd_titles = ["Enter the Iron Friends / Amadeus Cho's Eggcellent Eggventure!", "Great Expo-tations / Bouncy Boots",
                  "Totally Awesome Beach Day / Swarm Stinks it Up", "The Ultron Song / Black Panther and the Bot",
                  "Iron Friends Trick or Treat! / Leaping Into Fall"]
    dvd = EpisodeOrder("tvdb:dvd", "TVDB · DVD Order", "tvdb", {1: [
        OrderEpisode(n, [title], "2025-08-11" if n == 1 else "2025-08-12") for n, title in enumerate(dvd_titles, 1)]})
    eo.align_to(dvd, tmdb)
    assert [e.refs for e in dvd.seasons[1]] == [[(1, 1), (1, 2)], [(1, 3), (1, 4)], [(1, 5), (1, 6)],
                                                [(1, 7), (1, 8)], [(1, 9), (1, 10)]]
    assert [eo.translate(tmdb, dvd, 1, e) for e in (2, 3, 4, 5, 11)] == [[(1, 1)], [(1, 2)], [(1, 2)], [(1, 3)], []]


def test_titles_win_over_positions_and_dates_say_nothing_when_they_cannot():
    titles = ["The Train Job", "Bushwhacked", "Serenity", "Episode 4"]
    tmdb = EpisodeOrder("tmdb:default", "TMDB", "tmdb", {1: [
        OrderEpisode(n, [t], None, [(1, n)]) for n, t in enumerate(titles, 1)]})
    # Un ordine DVD che riordina: lo stesso numero di episodi, ma non uno a
    # uno per posizione. Un titolo generico resta alla posizione.
    dvd = EpisodeOrder("tvdb:dvd", "DVD", "tvdb", {1: [
        OrderEpisode(n, [t]) for n, t in enumerate(["Serenity", "The Train Job", "Bushwhacked", "Episode 4"], 1)]})
    eo.align_to(dvd, tmdb)
    assert [e.refs for e in dvd.seasons[1]] == [[(1, 3)], [(1, 1)], [(1, 2)], [(1, 4)]]
    # Cinque episodi in un giorno contro due, senza titoli che aiutino: nessun riferimento.
    ref = _order("tmdb:default", {1: 4}, dates={(1, 1): "2025-08-11", (1, 2): "2025-08-12", (1, 3): "2025-08-12",
                                                (1, 4): "2025-09-01"})
    same_day = _order("tvdb:dvd", {1: 6}, "tvdb", refs=False,
                      dates={(1, 1): "2025-08-11", **{(1, n): "2025-08-12" for n in range(2, 7)}})
    eo.align_to(same_day, ref)
    assert [e.refs for e in same_day.seasons[1]] == [[(1, 1)], [], [], [], [], []]


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
    one = _EpisodeJob(job(tmdb, parts), 2, [3])
    assert season_token(one.kind, json.loads(one.seasons_json), one.episode) == "S01E08"
    # File numerati uno a uno, scelto l'ordine con gli episodi accorpati: il file S01E04 è metà del 2.
    half = _EpisodeJob(job(doubled, tmdb), 1, [4])
    assert season_token(half.kind, json.loads(half.seasons_json), half.episode) == "S01E02"
    # Al contrario: un file dell'ordine accorpato copre due episodi.
    both = _EpisodeJob(job(tmdb, doubled), 1, [2])
    assert season_token(both.kind, json.loads(both.seasons_json), both.episode) == "S01E03E04"
    # Un file con due episodi (S01E03E04) nell'ordine accorpato è uno solo.
    pair = _EpisodeJob(job(doubled, tmdb), 1, [3, 4])
    assert season_token(pair.kind, json.loads(pair.seasons_json), pair.episode) == "S01E02"
    # Senza ordinamento scelto resta com'è, e un file con due episodi li tiene tutti e due.
    plain_job = SimpleNamespace(kind="season_pack", seasons_json="[2]", episode=None, episode_order_json=None)
    plain = _EpisodeJob(plain_job, 2, [3])
    assert season_token(plain.kind, json.loads(plain.seasons_json), plain.episode) == "S02E03"
    double = _EpisodeJob(plain_job, 2, [3, 4])
    assert season_token(double.kind, json.loads(double.seasons_json), double.episode) == "S02E03E04"


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
    def seasons(*names):
        return eo._group_seasons([{"order": i, "name": name} for i, name in enumerate(names)])

    assert seasons("Season 1", "Season 2") == [1, 2]
    assert seasons("Specials", "Stagione 1", "Part 3") == [0, 1, 3]
    # Senza numeri nel nome: dalla posizione, da 1.
    assert seasons("First", "Second") == [1, 2]
    assert seasons("Specials", "Main") == [0, 1]
    # Audit 2026-10-18: due gruppi con lo stesso numero nel nome (il secondo
    # spariva), e gli speciali in fondo (il primo gruppo diventava la 0).
    assert seasons("Season 1 Part 1", "Season 1 Part 2", "Season 2") == [1, 2, 3]
    assert seasons("Season 4 Volume 1", "Season 4 Volume 2") == [1, 2]
    assert seasons("Volume One", "Volume Two", "Specials") == [1, 2, 0]
    # "Season 0" sono gli speciali, e le altre stagioni restano le loro.
    assert seasons("Season 0", "Season 1") == [0, 1]
    assert seasons("Season 0", "Season 1", "Season 2") == [0, 1, 2]
    assert seasons("Season 0", "Specials", "Season 1") == [0, 0, 1]
    assert seasons("Season 0", "Season 1", "Season 1") == [0, 1, 2]
    # Un gruppo senza numero fra quelli numerati: il primo numero libero.
    assert seasons("Pilot Movie", "Season 1", "Season 2") == [3, 1, 2]


def test_parts_of_an_episode_group_with_the_same_number_keep_all_their_episodes():
    class Tmdb(FakeTmdb):
        def get(self, path, **params):
            if path == "/tv/episode_group/g1":
                def part(order, name, numbers):
                    return {"order": order, "name": name, "episodes": [
                        {"season_number": 1, "episode_number": e, "order": i} for i, e in enumerate(numbers)]}
                return {"groups": [part(0, "Season 1 Part 1", range(1, 6)), part(1, "Season 1 Part 2", range(6, 11)),
                                   part(2, "Extras", [1]), part(3, "Specials", [2])]}
            return super().get(path, **params)

    group = eo.tmdb_orders(Tmdb(), 96677)[1]
    assert {s: len(eps) for s, eps in group.seasons.items()} == {1: 5, 2: 5, 0: 2}
    assert group.seasons[2][0].refs == [(1, 6)] and [e.number for e in group.seasons[0]] == [1, 2]


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


def test_malformed_numbers_and_titles_from_the_sources_are_skipped(db_session):
    """Audit 2026-10-18: un episode_number null o un titolo non testo da
    TMDB o Sonarr facevano fallire build() (e le API sopra) con un TypeError."""
    from nazgarr.core.models import SonarrInstance

    class Tmdb:
        def get(self, path, **params):
            if path == "/tv/5" and not params:
                return {"seasons": [{"season_number": 1}, {"season_number": None}]}
            if path == "/tv/5":
                return {"season/1": {"episodes": [
                    {"episode_number": 1, "name": "Pilot", "air_date": "2020-01-01"},
                    {"episode_number": None, "name": "Broken"},
                    {"episode_number": "3", "name": "Text"},
                    {"episode_number": 2, "name": 42, "air_date": 7},
                ]}}
            if path == "/tv/5/episode_groups":
                return {"results": [{"id": "g", "name": "G", "type": 4, "episode_count": 2}]}
            if path == "/tv/episode_group/g":
                return {"groups": [{"order": 0, "name": "Season 1", "episodes": [
                    {"season_number": 1, "episode_number": 1, "order": 0},
                    {"season_number": None, "episode_number": 2, "order": 1}]}]}
            raise AssertionError(path)

    class Sonarr:
        def __init__(self, instance):
            pass

        def get(self, path, **params):
            if path == "/api/v3/series":
                return [{"id": 1, "tmdbId": 5}]
            return [{"seasonNumber": 1, "episodeNumber": 1, "title": ["not", "text"]},
                    {"seasonNumber": 1, "episodeNumber": "2", "title": "Two"},
                    {"seasonNumber": 1, "episodeNumber": 2, "title": 99}]

    alone = eo.build(db_session, 5, None, {1: [1, 2]}, pack=True, tmdb_api=Tmdb())
    tmdb = next(o for o in alone["orders"] if o["key"] == "tmdb:default")
    assert [(e["number"], e["titles"], e["air_date"]) for e in tmdb["seasons"][0]["episodes"]] == [
        (1, ["Pilot"], "2020-01-01"), (2, [""], None)]
    group = next(o for o in alone["orders"] if o["key"] == "tmdb:group:g")
    assert [e["refs"] for e in group["seasons"][0]["episodes"]] == [[[1, 1]]]

    db_session.add(SonarrInstance(label="s", base_url="http://s", api_key="k"))
    db_session.commit()
    eo.clear_cache()
    result = eo.build(db_session, 5, None, {1: [1, 2]}, pack=True, tmdb_api=Tmdb(), sonarr_factory=Sonarr)
    sonarr = next(o for o in result["orders"] if o["key"] == "sonarr:aired")
    assert [(e["number"], e["titles"], e["refs"]) for e in sonarr["seasons"][0]["episodes"]] == [
        (1, [""], [[1, 1]]), (2, [""], [[1, 2]])]


def test_an_order_that_fails_to_align_is_left_without_references(db_session, monkeypatch):
    from nazgarr.core.models import SonarrInstance

    db_session.add(SonarrInstance(label="sonarr", base_url="http://s", api_key="k"))
    db_session.commit()
    monkeypatch.setattr(eo, "align", lambda episodes, reference: 1 / 0)

    result = eo.build(db_session, 96677, 375921, {1: [1]}, pack=False, tmdb_api=FakeTmdb(), sonarr_factory=FakeSonarr)

    sonarr = next(o for o in result["orders"] if o["key"] == "sonarr:aired")
    assert all(e["refs"] == [] for s in sonarr["seasons"] for e in s["episodes"])


def test_translations_index_each_pair_of_orders_once(monkeypatch):
    """Audit 2026-10-18: translate() rifaceva e riordinava i due ordinamenti
    a ogni episodio; una serie da 1100 episodi costava secondi alla scheda,
    al match e ai nomi dei file di un pack."""
    import json
    from types import SimpleNamespace

    tmdb = _order("tmdb:default", {1: 300, 2: 300})
    parts = _order("tvdb:alternate", {1: 200, 2: 200, 3: 200}, "tvdb", refs=False)
    eo.align_to(parts, tmdb)
    calls = []
    real = EpisodeOrder.episodes
    monkeypatch.setattr(EpisodeOrder, "episodes", lambda self: calls.append(self.key) or real(self))

    found = eo.translate_found(parts, tmdb, {3: list(range(1, 201))})

    assert found == {2: list(range(101, 301))}
    assert sorted(calls) == ["tmdb:default", "tvdb:alternate"]  # una volta per ordinamento, non per episodio

    calls.clear()
    job = SimpleNamespace(episode_order_json=json.dumps({"chosen": tmdb.to_dict(), "files": parts.to_dict()}))
    parsed = []
    real_from = EpisodeOrder.from_dict
    monkeypatch.setattr(EpisodeOrder, "from_dict", staticmethod(lambda data: parsed.append(1) or real_from(data)))
    assert [eo.translate_files(job, 3, e) for e in (1, 2, 200)] == [[(2, 101)], [(2, 102)], [(2, 300)]]
    assert len(parsed) == 2  # il JSON del job letto una volta, non a ogni file
    assert eo.translate_files(job, 9, 9) == [(9, 9)]


def _titled(key, titles, source="tvdb", refs=False):
    return EpisodeOrder(key, key, source, {1: [
        OrderEpisode(n, [t], None, [(1, n)] if refs else []) for n, t in enumerate(titles, 1)]})


def test_a_title_override_needs_the_same_numbers_and_a_title_unique_on_both_sides():
    """Audit 2026-10-18: "Part I" passava per "Part II" (il controllo dei
    numeri guardava solo le cifre), e due episodi con lo stesso titolo
    nell'ordinamento finivano sullo stesso riferimento."""
    tmdb = _titled("tmdb:default", ["Pilot", "The Best of Both Worlds", "The Best of Both Worlds Part II", "Restless"],
                   "tmdb", refs=True)
    sonarr = _titled("sonarr:aired", ["Pilot", "The Best of Both Worlds Part I", "The Best of Both Worlds Part II",
                                      "Restless"])
    eo.align_to(sonarr, tmdb)
    assert [e.refs for e in sonarr.seasons[1]] == [[(1, 1)], [(1, 2)], [(1, 3)], [(1, 4)]]
    assert eo.translate_found(sonarr, tmdb, {1: [1, 2, 3, 4]}) == {1: [1, 2, 3, 4]}

    # Lo stesso titolo due volte nell'ordinamento (una volta sola nel riferimento): resta la posizione.
    tmdb = EpisodeOrder("tmdb:default", "TMDB", "tmdb", {
        1: [OrderEpisode(1, ["Pilot"], None, [(1, 1)]), OrderEpisode(2, ["Second"], None, [(1, 2)])],
        2: [OrderEpisode(1, ["The Pilot"], None, [(2, 1)]), OrderEpisode(2, ["Fourth"], None, [(2, 2)])]})
    sonarr = EpisodeOrder("sonarr:aired", "S", "sonarr", {
        1: [OrderEpisode(1, ["Pilot"]), OrderEpisode(2, ["Second"])],
        2: [OrderEpisode(1, ["Pilot"]), OrderEpisode(2, ["Fourth"])]})
    eo.align_to(sonarr, tmdb)
    assert [e.refs for s in (1, 2) for e in sonarr.seasons[s]] == [[(1, 1)], [(1, 2)], [(2, 1)], [(2, 2)]]


def test_roman_numerals_and_number_words_count_only_after_the_first_word():
    assert eo._numbers(eo._title_key("The Best of Both Worlds, Part I")) == (1,)
    assert eo._numbers(eo._title_key("Chapter Four")) == (4,)
    # In testa sono un articolo o un pronome: "I Misteri" e "Misteri" si somigliano ancora.
    assert eo._numbers(eo._title_key("I misteri della notte")) == ()
    assert eo._numbers(eo._title_key("S01 2gether")) == (1, 2)


def test_a_near_title_never_takes_an_episode_an_identical_title_already_owns():
    tmdb = _titled("tmdb:default", ["Into the Woods", "Bushwhacked", "Restless"], "tmdb", refs=True)
    # "Into the Wood" somiglia a "Into the Woods", che però è già di un altro episodio.
    dvd = _titled("tvdb:dvd", ["Bushwhacked", "Into the Woods", "Into the Wood"])
    eo.align_to(dvd, tmdb)
    assert [e.refs for e in dvd.seasons[1]] == [[(1, 2)], [(1, 1)], [(1, 3)]]
    # Senza un titolo identico che lo prenda, un refuso vale ancora.
    typo = _titled("tvdb:dvd", ["Restless", "Into the Wood", "Bushwhacked"])
    eo.align_to(typo, tmdb)
    assert [e.refs for e in typo.seasons[1]] == [[(1, 3)], [(1, 1)], [(1, 2)]]


def test_an_alignment_is_computed_once_for_the_same_orders(monkeypatch):
    calls = []
    real = eo.align
    monkeypatch.setattr(eo, "align", lambda episodes, reference: calls.append(1) or real(episodes, reference))
    tmdb = _order("tmdb:default", {1: 10, 2: 7})
    for _ in range(3):
        parts = _order("tvdb:alternate", {1: 5, 2: 5, 3: 7}, "tvdb", refs=False)
        eo.align_to(parts, tmdb)
        assert parts.seasons[3][0].refs == [(2, 1)]
    assert len(calls) == 2  # stagioni e speciali, una volta sola
    other = _order("tvdb:alternate", {1: 5, 2: 12}, "tvdb", refs=False)
    eo.align_to(other, tmdb)
    assert len(calls) == 4 and other.seasons[2][0].refs == [(1, 6)]


def test_without_tmdb_the_files_ordering_is_proposed_since_nothing_translates(db_session):
    """Audit 2026-10-18: senza le stagioni di default di TMDB nessun
    ordinamento ha i riferimenti; proporne uno diverso da quello dei file
    (qui "Joined") lasciava i numeri di Sonarr sotto un'altra etichetta."""
    from nazgarr.core.models import SonarrInstance

    class Sonarr:
        def __init__(self, instance):
            pass

        def get(self, path, **params):
            if path == "/api/v3/series":
                return [{"id": 1, "tmdbId": 4229}]
            return [{"seasonNumber": 1, "episodeNumber": n, "title": f"Segment {n}"} for n in range(1, 40)]

    class Tvdb:
        def get(self, path, **params):
            if path.endswith("/extended"):
                return {"seasonTypes": [{"type": "official", "name": "Aired"}, {"type": "alternate", "name": "Joined"}]}
            count = 39 if path.endswith("/official") else 13
            return {"episodes": [{"seasonNumber": 1, "number": n, "name": f"x {n}"} for n in range(1, count + 1)]}

    db_session.add(SonarrInstance(label="sonarr", base_url="http://s", api_key="k"))
    db_session.commit()
    found = {1: list(range(1, 38, 3))}  # 13 file numerati col primo segmento di Sonarr

    result = eo.build(db_session, 4229, 76015, found, pack=True, tvdb_api=Tvdb(), sonarr_factory=Sonarr)

    assert result["sources"]["tmdb"] == "no_key"
    assert result["files_order"] == "sonarr:aired" and result["recommended"] == "sonarr:aired"
    # Scelto comunque l'altro a mano: nessun episodio si traduce, e si sa quali.
    snap = eo.snapshot(result, "tvdb:alternate")
    assert eo.untranslated(snap, found) == [(1, e) for e in found[1]]
    assert eo.untranslated(eo.snapshot(result, "sonarr:aired"), found) == []


def _named_job(db_session, tmp_path, relative, layout, chosen, files, *, kind, seasons, episode=None):
    import json

    from nazgarr.upload import jobs as upload_jobs
    from tests.upload_helpers import make_disk, make_tracker

    make_tracker(db_session)
    job = upload_jobs.create_job(db_session, make_disk(db_session, tmp_path), relative)
    job.status, job.content_type, job.title, job.year, job.tmdb_id = "analyzing", "tv", "Show", 2024, 1
    job.kind, job.seasons_json, job.episode = kind, json.dumps(seasons), episode
    job.layout_json = json.dumps(layout)
    job.episode_order = chosen.key
    job.episode_order_json = json.dumps({"chosen": chosen.to_dict(), "files": files.to_dict()})
    db_session.commit()
    return job


def test_a_single_file_of_a_merged_episode_is_named_with_both_episodes(db_session, tmp_path):
    """Audit 2026-10-18: lo stesso file in un pack si chiamava S01E03E04, da
    solo S01E03 (solo job.episode)."""
    from nazgarr.upload import file_names as upload_file_names
    from tests.upload_helpers import write_video

    tmdb = _order("tmdb:default", {1: 10})
    doubled = _order("tvdb:regional", {1: 5}, "tvdb", refs=False)
    eo.align_to(doubled, tmdb)
    write_video(tmp_path / "Show.S01E02.1080p.WEB-DL-GRP.mkv")
    layout = {"videos": [{"relative_path": "Show.S01E02.1080p.WEB-DL-GRP.mkv", "season": 1, "episodes": [2]}]}
    job = _named_job(db_session, tmp_path, "Show.S01E02.1080p.WEB-DL-GRP.mkv", layout, tmdb, doubled,
                     kind="episode", seasons=[1], episode=3)

    plan = upload_file_names.plan(db_session, job, "generated")

    assert "S01E03E04" in plan.content_name and plan.content_name.endswith(".mkv")
    assert job.episode == 3  # il campo episodio del tracker resta uno
    # Il titolo proposto per il tracker dice gli stessi episodi del file.
    from nazgarr.upload import decision as upload_decision

    upload_decision.propose(db_session, job)
    assert job.targets and all("S01E03E04" in t.proposed_name for t in job.targets)
    # Un episodio corretto a mano al match resta il suo.
    job.episode = 7
    assert "S01E07" in upload_file_names.plan(db_session, job, "generated").content_name
    upload_decision.propose(db_session, job)
    assert all("S01E07" in t.proposed_name and "E08" not in t.proposed_name for t in job.targets)


def test_a_pack_file_the_chosen_ordering_lacks_keeps_its_name_and_the_match_says_so(db_session, tmp_path):
    """Audit 2026-10-18: un episodio che non si traduce prendeva il numero
    dei file dentro il nome dell'altro ordinamento, senza dirlo."""
    import json

    from nazgarr.upload import file_names as upload_file_names
    from nazgarr.upload import identify as upload_identify
    from tests.upload_helpers import write_video

    tmdb = _order("tmdb:default", {1: 2})
    sonarr = _order("sonarr:aired", {1: 3}, "sonarr")  # un episodio in più, che TMDB non ha
    sonarr.seasons[1][2].refs = []
    names = [f"Show.S01E0{e}.1080p.WEB-DL-GRP.mkv" for e in (1, 2, 3)]
    for name in names:
        write_video(tmp_path / "Show.S01" / name)
    layout = {"kind": "season_pack", "videos": [{"relative_path": n, "season": 1, "episodes": [e]}
                                                for e, n in enumerate(names, 1)],
              "episodes_by_season": {"1": [1, 2, 3]}}
    job = _named_job(db_session, tmp_path, "Show.S01", layout, tmdb, sonarr, kind="season_pack", seasons=[1])

    plan = upload_file_names.plan(db_session, job, "generated")

    renamed = sorted(target.rsplit("/", 1)[1] for _s, target in plan.files)
    assert renamed[:2] == ["Show.S01E01.mkv", "Show.S01E02.mkv"]  # generati (nessun MediaInfo)
    assert renamed[2] == "Show.S01E03.1080p.WEB-DL-GRP.mkv"  # il suo nome di prima

    job.status, job.episode_order, job.episode_order_json = "awaiting_match", None, None
    db_session.commit()
    orders = {"orders": [tmdb.to_dict(), sonarr.to_dict()], "files_order": "sonarr:aired", "found": {}}
    upload_identify.confirm(db_session, job, content_type="tv", tmdb_id=1, kind="season_pack", seasons=[1],
                            episode=None, details=None, order_key="tmdb:default", orders=orders)
    db_session.commit()
    event = next(e for e in job.events if e.code == "episode_order_untranslated")
    assert (event.level, json.loads(event.params_json)) == ("warning", {"order": "tmdb:default", "count": 1,
                                                                        "episodes": "S01E03"})
    assert job.status == "analyzing"


def test_tmdb_and_tvdb_apis_share_one_http_client_each(monkeypatch):
    """Un TmdbApi o TvdbApi nasce per scheda, job e serie: ognuno apriva il
    suo httpx.Client senza chiuderlo (audit 2026-10-18). Ora quello di
    processo, con la chiave e il timeout in ogni richiesta."""
    import httpx

    from nazgarr.library import tmdb_client

    assert eo.TmdbApi("a")._client is eo.TmdbApi("b")._client is tmdb_client.shared_http_client()
    assert eo.TvdbApi("a")._client is eo.TvdbApi("b")._client

    seen = []

    def handler(request):
        seen.append((request.url.params.get("api_key"), request.extensions["timeout"]["read"]))
        return httpx.Response(200, json={})

    shared = httpx.Client(base_url=tmdb_client.TMDB_API_BASE, transport=httpx.MockTransport(handler), timeout=10.0)
    monkeypatch.setattr(tmdb_client, "_shared", shared)
    eo.TmdbApi("key-1").get("/tv/1")
    eo.TmdbApi("key-2").get("/tv/2")
    assert seen == [("key-1", eo.TMDB_TIMEOUT_SECONDS), ("key-2", eo.TMDB_TIMEOUT_SECONDS)]
