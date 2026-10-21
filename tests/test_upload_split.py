"""Una stagione incompleta divisa in episodi (nazgarr/upload/split.py): i primi
2 episodi di 8 usciti insieme nella cartella osservata."""

import json
import os

import pytest

from nazgarr.core import settings_repo
from nazgarr.core.models import UploadJob
from nazgarr.library import episode_orders
from nazgarr.upload import execute as upload_execute
from nazgarr.upload import identify as upload_identify
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload import split as upload_split
from tests.upload_helpers import FakeTMDB, make_disk, make_tracker, tmdb_result, write_video

FOLDER = "Show.S01E01E02.1080p.WEB-DL-GRP"
EPISODES = ("Show.S01E01.1080p.WEB-DL-GRP.mkv", "Show.S01E02.1080p.WEB-DL-GRP.mkv")


def _release(tmp_path):
    """La release nella cartella osservata, con un nfo e un sample."""
    folder = tmp_path / "releases" / FOLDER
    for name in EPISODES:
        write_video(folder / name)
    (folder / "Show.S01E01E02.nfo").write_text("notes")
    write_video(folder / "Sample" / "show.sample.mkv", size=100)
    return folder


def _tmdb(monkeypatch, episodes_in_season):
    monkeypatch.setattr(upload_identify.adapter_factory, "build_media_resolver",
                        lambda session, arr_index=None: type("R", (), {"SOURCE": "x", "resolve": lambda s, p: None})())
    show = tmdb_result(1399, "Show", 2024, "tv")
    details = {**show, "seasons": [{"season_number": 1, "episode_count": episodes_in_season}]}
    fake = FakeTMDB(search={("tv", "Show", None): [show]}, details={("tv", 1399): details})
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)
    # Niente ordinamenti alternativi (TVDB, gruppi TMDB): basta il conteggio di TMDB.
    monkeypatch.setattr(episode_orders, "for_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))


def _identified(db_session, tmp_path, monkeypatch, *, episodes_in_season=8, origin="watch"):
    tracker = make_tracker(db_session)
    disk = make_disk(db_session, tmp_path)
    _release(tmp_path)
    _tmdb(monkeypatch, episodes_in_season)
    # Il nome della release non ha l'anno: il match vale 0.85.
    settings_repo.set_setting(db_session, upload_identify.AUTO_MATCH_SETTING, "0.8")
    finished = []
    monkeypatch.setattr(upload_jobs, "_emit_finished", lambda session, job: finished.append(job.id))
    job = upload_jobs.create_job(db_session, disk, f"releases/{FOLDER}",
                                 tracker_choices={tracker.id: {"freeleech": 25}}, origin=origin)
    kicked = []
    worker = type("W", (), {"kick": lambda self, job_id, status: kicked.append((job_id, status))})()
    upload_identify.handle(db_session, job, worker)
    return job, kicked, finished


def test_two_episodes_of_eight_become_two_episode_uploads(db_session, tmp_path, monkeypatch):
    job, kicked, finished = _identified(db_session, tmp_path, monkeypatch)

    assert job.status == "cancelled"
    split = next(e for e in job.events if e.code == "job_split")
    children = [db_session.get(UploadJob, i) for i in json.loads(split.params_json)["jobs"]]
    assert [(c.kind, json.loads(c.seasons_json), c.episode, c.tmdb_id, c.status) for c in children] == [
        ("episode", [1], 1, 1399, "analyzing"), ("episode", [1], 2, 1399, "analyzing")]
    assert [os.path.basename(c.relative_path) for c in children] == list(EPISODES)
    assert {(c.origin, c.split_from_id) for c in children} == {("watch", job.id)}
    # Stessi tracker, con il freeleech scelto, e gli episodi vanno avanti da soli.
    assert [json.loads(c.targets[0].flags_json) for c in children] == [{"freeleech": 25}] * 2
    assert kicked == [(c.id, "analyzing") for c in children]
    assert finished == []  # niente notifica "upload annullato"
    with pytest.raises(upload_jobs.UploadJobError, match="upload_job_split"):
        upload_jobs.resume_job(db_session, job)


def test_a_split_failing_halfway_leaves_only_the_pack(db_session, tmp_path, monkeypatch):
    """Audit 2026-10-18: un errore a metà divisione lasciava vivi gli episodi
    già creati, sugli stessi file del pack che andava avanti intero."""
    real_create = upload_jobs.create_job
    calls = []

    def create_job(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:  # il pack, il primo episodio, poi il secondo fallisce
            raise upload_jobs.UploadJobError("upload_source_not_found", path="gone")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(upload_jobs, "create_job", create_job)
    job, kicked, _finished = _identified(db_session, tmp_path, monkeypatch)

    assert (job.status, job.kind) == ("analyzing", "season_pack")
    assert db_session.query(UploadJob).count() == 1 and kicked == []
    assert job.events[-1].code == "split_failed"


def test_a_complete_season_stays_a_pack(db_session, tmp_path, monkeypatch):
    job, _kicked, _finished = _identified(db_session, tmp_path, monkeypatch, episodes_in_season=2)

    assert (job.status, job.kind) == ("analyzing", "season_pack")
    assert db_session.query(UploadJob).count() == 1


def test_the_option_off_or_a_manual_upload_keep_the_pack(db_session, tmp_path, monkeypatch):
    settings_repo.set_setting(db_session, upload_split.SPLIT_SETTING, "false")
    job, _kicked, _finished = _identified(db_session, tmp_path, monkeypatch)
    assert (job.status, job.kind) == ("analyzing", "season_pack")

    settings_repo.set_setting(db_session, upload_split.SPLIT_SETTING, "true")
    manual = upload_jobs.create_job(db_session, job.disk, f"releases/{FOLDER}")
    upload_identify.handle(db_session, manual, None)
    assert (manual.status, manual.kind) == ("analyzing", "season_pack")  # a mano: il tasto al match


def test_the_watched_folder_goes_once_no_episode_is_left(db_session, tmp_path, monkeypatch):
    job, _kicked, _finished = _identified(db_session, tmp_path, monkeypatch)
    first, second = db_session.query(UploadJob).filter(UploadJob.split_from_id == job.id).order_by(UploadJob.id)
    job.disk.watch_rel_path = "releases"
    db_session.commit()
    folder = tmp_path / "releases" / FOLDER
    watch = str(tmp_path / "releases")

    os.remove(folder / EPISODES[0])  # spostato nella cartella delle release dal primo upload
    upload_execute._remove_split_folder(db_session, first, watch)
    assert folder.is_dir()  # c'è ancora il secondo episodio

    os.remove(folder / EPISODES[1])
    upload_execute._remove_split_folder(db_session, second, watch)
    assert not folder.exists()
    removed = next(e for e in second.events if e.code == "watch_folder_removed")
    assert sorted(json.loads(removed.params_json)["files"]) == ["Sample/show.sample.mkv", "Show.S01E01E02.nfo"]


def test_split_from_the_match_by_hand(client, tmp_path, monkeypatch):
    from nazgarr.upload.worker import UploadWorker
    from tests.upload_helpers import InlineExecutor

    session = client.app.state.session_factory()
    disk = make_disk(session, tmp_path)
    make_tracker(session)
    settings_repo.set_setting(session, upload_identify.AUTO_MATCH_SETTING, "0")  # si ferma al match
    _release(tmp_path)
    _tmdb(monkeypatch, 8)
    job = upload_jobs.create_job(session, disk, f"releases/{FOLDER}")
    upload_identify.handle(session, job, None)
    assert job.status == "awaiting_match"
    job_id = job.id
    session.close()
    kicked = []
    client.app.state.upload_worker = UploadWorker(client.app.state.session_factory, str(tmp_path / "data"),
                                                  light_executor=InlineExecutor(), heavy_executor=InlineExecutor())
    monkeypatch.setattr(client.app.state.upload_worker, "kick", lambda job_id, status: kicked.append(job_id))
    body = {"content_type": "tv", "tmdb_id": 1399, "kind": "season_pack", "seasons": [1]}

    assert client.post(f"/api/uploads/{job_id}/split", json={**body, "kind": "episode"}).status_code == 400
    response = client.post(f"/api/uploads/{job_id}/split", json=body)

    assert response.status_code == 200, response.text
    children = response.json()["job_ids"]
    assert len(children) == 2 and kicked == children
    assert client.get(f"/api/uploads/{job_id}").json()["status"] == "cancelled"


@pytest.mark.parametrize("failure", ["io", "unexpected"])
def test_a_split_by_hand_that_fails_leaves_only_the_pack_going(client, tmp_path, monkeypatch, failure):
    """Audit 2026-10-18 (finding 154): fuori da UploadJobError e
    ScopeViolation (un OSError leggendo un episodio, un errore del DB) la
    divisione a mano rispondeva 500 senza codice, e il pack restava fermo
    fino al riavvio. Ora un codice, il pack va avanti, e nessun episodio
    resta, anche se la divisione non è riuscita a toglierli da sé."""
    from nazgarr.upload.worker import UploadWorker
    from tests.upload_helpers import InlineExecutor

    session = client.app.state.session_factory()
    disk = make_disk(session, tmp_path)
    make_tracker(session)
    settings_repo.set_setting(session, upload_identify.AUTO_MATCH_SETTING, "0")  # si ferma al match
    _release(tmp_path)
    _tmdb(monkeypatch, 8)
    job = upload_jobs.create_job(session, disk, f"releases/{FOLDER}")
    upload_identify.handle(session, job, None)
    job_id = job.id
    session.close()
    kicked = []
    client.app.state.upload_worker = UploadWorker(client.app.state.session_factory, str(tmp_path / "data"),
                                                  light_executor=InlineExecutor(), heavy_executor=InlineExecutor())
    monkeypatch.setattr(client.app.state.upload_worker, "kick", lambda job_id, status: kicked.append(job_id))
    real_scan, calls = upload_split.scan_source, []

    def scan_source(path, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk gone") if failure == "io" else RuntimeError("database is locked")
        return real_scan(path, *args, **kwargs)

    monkeypatch.setattr(upload_split, "scan_source", scan_source)
    if failure == "unexpected":
        monkeypatch.setattr(upload_split, "_discard", lambda session, children: None)  # non è riuscita

    response = client.post(f"/api/uploads/{job_id}/split",
                           json={"content_type": "tv", "tmdb_id": 1399, "kind": "season_pack", "seasons": [1]})

    assert response.status_code == (400 if failure == "io" else 500)
    assert response.json()["detail"]["code"] == ("upload_source_unreadable" if failure == "io"
                                                 else "upload_prepare_failed")
    assert kicked == [job_id]
    assert [j["id"] for j in client.get("/api/uploads").json()] == [job_id]
    detail = client.get(f"/api/uploads/{job_id}").json()
    # Il pack va avanti intero: l'analisi non rifà la divisione non riuscita.
    assert (detail["status"], detail["stage"]) == ("analyzing", None)


class _PartsTmdb:
    """Lupin come su TMDB: default 10 + 7, e il gruppo "Parts" 5 / 5 / 7."""

    def __init__(self, dates=None):
        self.dates = dates or {}

    def get(self, path, **params):
        if path == "/tv/96677" and not params:
            return {"seasons": [{"season_number": 1}, {"season_number": 2}]}
        if path == "/tv/96677":
            return {f"season/{n}": {"episodes": [
                {"episode_number": e, "name": f"Chapter {n}x{e}", "air_date": self.dates.get((n, e))}
                for e in range(1, c + 1)]} for n, c in ((1, 10), (2, 7))}
        if path == "/tv/96677/external_ids":
            return {"tvdb_id": 1}
        if path == "/tv/96677/episode_groups":
            return {"results": [{"id": "g1", "name": "Parts", "type": 4, "episode_count": 17}]}
        if path == "/tv/episode_group/g1":
            def part(order, refs):
                return {"order": order, "name": f"Part {order}", "episodes": [
                    {"season_number": s, "episode_number": e, "order": i} for i, (s, e) in enumerate(refs)]}
            return {"groups": [part(1, [(1, e) for e in range(1, 6)]), part(2, [(1, e) for e in range(6, 11)]),
                               part(3, [(2, e) for e in range(1, 8)])]}
        raise AssertionError(path)


def _sonarr(episodes):
    class Sonarr:
        def __init__(self, instance):
            pass

        def get(self, path, **params):
            return [{"id": 7, "tmdbId": 96677}] if path == "/api/v3/series" else episodes

    return Sonarr


def _lupin_watch(db_session, tmp_path, monkeypatch, files, tmdb_api, sonarr_episodes):
    from nazgarr.core.models import SonarrInstance
    from nazgarr.upload import file_names as upload_file_names

    episode_orders.clear_cache()
    db_session.add(SonarrInstance(label="sonarr", base_url="http://s", api_key="k"))
    db_session.commit()
    real_for_job = episode_orders.for_job
    monkeypatch.setattr(episode_orders, "for_job", lambda session, job, tmdb_id, tvdb_id=None, **k: real_for_job(
        session, job, tmdb_id, 1, tmdb_api=tmdb_api, sonarr_factory=_sonarr(sonarr_episodes)))
    monkeypatch.setattr(upload_identify.adapter_factory, "build_media_resolver",
                        lambda session, arr_index=None: type("R", (), {"SOURCE": "x", "resolve": lambda s, p: None})())
    show = tmdb_result(96677, "Lupin", 2021, "tv")
    details = {**show, "tvdb_id": 1, "seasons": [{"season_number": 1, "episode_count": 10},
                                                 {"season_number": 2, "episode_count": 7}]}
    fake = FakeTMDB(search={("tv", "Lupin", 2021): [show]}, details={("tv", 96677): details})
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)
    settings_repo.set_setting(db_session, upload_identify.AUTO_MATCH_SETTING, "0.5")
    folder = "Lupin.2021.S02.1080p.NF.WEB-DL-GRP"
    for name in files:
        write_video(tmp_path / "releases" / folder / name)
    make_tracker(db_session)
    job = upload_jobs.create_job(db_session, make_disk(db_session, tmp_path), f"releases/{folder}", origin="watch")
    upload_identify.handle(db_session, job, None)
    children = db_session.query(UploadJob).filter(UploadJob.split_from_id == job.id).order_by(UploadJob.id).all()
    names = [upload_file_names.plan(db_session, c, "generated").content_name for c in children]
    return job, children, names


def test_episodes_split_from_a_pack_keep_the_numbering_of_the_pack(db_session, tmp_path, monkeypatch):
    """Audit 2026-10-18: ogni episodio ricalcolava gli ordinamenti dal suo
    file solo, dove combaciano tutti: la numerazione dei file diventava
    quella che vince a parità (TVDB aired) e la Parte 2 S02E01-03 finiva
    in S03E01-03."""
    sonarr = [{"seasonNumber": s, "episodeNumber": e, "title": f"Chapitre {s}x{e}"}
              for s, c in ((1, 10), (2, 7)) for e in range(1, c + 1)]
    files = [f"Lupin.2021.S02E0{e}.1080p.NF.WEB-DL-GRP.mkv" for e in (1, 2, 3)]

    job, children, names = _lupin_watch(db_session, tmp_path, monkeypatch, files, _PartsTmdb(), sonarr)

    assert (job.status, job.episode_order) == ("cancelled", "tmdb:group:g1")
    assert [(json.loads(c.seasons_json), c.episode, c.episode_order) for c in children] == [
        ([2], 1, "tmdb:group:g1"), ([2], 2, "tmdb:group:g1"), ([2], 3, "tmdb:group:g1")]
    assert [json.loads(c.episode_order_json)["files"]["key"] for c in children] == ["tmdb:group:g1"] * 3
    assert all(f".S02E0{e}." in name for e, name in zip((1, 2, 3), names, strict=True)), names


class _CoursTmdb:
    """Una serie in due cour su TMDB (S1 13 + S2 13), senza gruppi."""

    def __init__(self, dates):
        self.dates = dates

    def get(self, path, **params):
        if path == "/tv/96677" and not params:
            return {"seasons": [{"season_number": 1}, {"season_number": 2}]}
        if path == "/tv/96677":
            return {f"season/{n}": {"episodes": [
                {"episode_number": e, "name": f"Chapter {n}x{e}", "air_date": self.dates[(n, e)]}
                for e in range(1, 14)]} for n in (1, 2)}
        if path == "/tv/96677/episode_groups":
            return {"results": []}
        raise AssertionError(path)


def test_an_episode_that_does_not_translate_leaves_the_season_count_unknown(db_session, tmp_path, monkeypatch):
    """Audit 2026-10-18: un episodio che la traduzione perde contava come
    mancante, e una stagione completa si divideva in episodi. Qui la seconda
    cour, numerata di seguito come Sonarr (S01E14-26), con un episodio che
    per TVDB è uscito un giorno dopo."""
    from datetime import date, timedelta

    def week(n):
        return (date(2021, 1, 1) + timedelta(weeks=n)).isoformat()

    dates = {(s, e): week((s - 1) * 13 + e) for s in (1, 2) for e in range(1, 14)}
    sonarr = [{"seasonNumber": 1, "episodeNumber": n, "title": f"Titre {n}",
               "airDate": week(n) if n != 20 else (date.fromisoformat(week(n)) + timedelta(days=1)).isoformat()}
              for n in range(1, 28)]  # 27: uno in più, alla fine
    files = [f"Lupin.2021.S01E{e:02d}.1080p.NF.WEB-DL-GRP.mkv" for e in range(14, 27)]

    def no_split(session, job, *args, **kwargs):
        raise AssertionError("una stagione completa non si divide")

    monkeypatch.setattr(upload_split, "split", no_split)
    job, children, _names = _lupin_watch(db_session, tmp_path, monkeypatch, files, _CoursTmdb(dates), sonarr)

    assert children == [] and job.status == "analyzing"
    assert (job.kind, json.loads(job.seasons_json), job.episode_order) == ("season_pack", [2], "tmdb:default")
    assert upload_split.season_count(job, None) is None and upload_split.untranslated(job, None)
    codes = [e.code for e in job.events]
    assert "split_skipped_untranslated" in codes and "episode_order_untranslated" in codes
    # Il video che non si traduce resta nel pack con i suoi vicini, non finisce fuori come "stagione 1".
    assert "pack_from_seasons" not in codes and len(json.loads(job.layout_json)["videos"]) == 13


def _counted(episodes, expected, snapshot=None):
    from types import SimpleNamespace

    layout = {"episodes_by_season": {"1": episodes}}
    return SimpleNamespace(kind="season_pack", seasons_json="[1]", layout_json=json.dumps(layout),
                           episode_order="tmdb:default" if snapshot else None,
                           episode_order_json=json.dumps(snapshot) if snapshot else None), \
        {"seasons": [{"season_number": 1, "episode_count": expected}]}


def test_only_episodes_the_season_has_count_towards_completeness():
    """Audit 2026-10-18: un E00 o un E13 di una stagione da 12 coprivano il
    dodicesimo mancante, e la stagione incompleta restava un pack."""
    from tests.test_episode_orders import _order

    tmdb = _order("tmdb:default", {1: 12})
    snapshot = {"chosen": tmdb.to_dict(), "files": tmdb.to_dict()}
    for extra in (0, 13):
        for snap in (None, snapshot):
            job, details = _counted([extra, *range(1, 12)], 12, snap)
            assert upload_split.season_count(job, details) == (11, 12)
            assert upload_split.is_incomplete(job, details)
    job, details = _counted(list(range(1, 13)), 12, snapshot)
    assert upload_split.season_count(job, details) == (12, 12) and not upload_split.is_incomplete(job, details)


def test_a_source_error_halfway_leaves_only_the_pack(db_session, tmp_path, monkeypatch):
    """Un errore di I/O (non un UploadJobError) sul secondo episodio: via
    anche il primo, il pack va avanti da solo (audit 2026-10-18)."""
    real_scan = upload_split.scan_source
    calls = []

    def scan_source(path, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk gone")
        return real_scan(path, *args, **kwargs)

    monkeypatch.setattr(upload_split, "scan_source", scan_source)
    job, kicked, _finished = _identified(db_session, tmp_path, monkeypatch)

    assert (job.status, job.kind) == ("analyzing", "season_pack")
    assert db_session.query(UploadJob).count() == 1 and kicked == []
    assert job.events[-1].code == "split_failed"


def test_a_cancel_during_the_split_is_honoured(db_session, tmp_path, monkeypatch):
    """L'utente annulla il pack mentre si divide: niente episodi rimasti, e
    niente "divisione non riuscita" nel registro (audit 2026-10-18)."""
    real_close = upload_split._close

    def close(session, job, code, children):
        other = session.__class__(bind=session.get_bind())
        upload_jobs.cancel_job(other, other.get(UploadJob, job.id))
        other.close()
        session.expire(job)
        real_close(session, job, code, children)

    monkeypatch.setattr(upload_split, "_close", close)
    job, kicked, _finished = _identified(db_session, tmp_path, monkeypatch)

    assert job.status == "cancelled" and kicked == []
    assert db_session.query(UploadJob).count() == 1
    assert "split_failed" not in [e.code for e in job.events]


class _Killed(BaseException):
    """Un kill del processo: nessun except Exception lo ferma."""


def _crash_on(monkeypatch, call):
    real = upload_identify.record_identification
    calls = []

    def record_identification(*args, **kwargs):
        calls.append(1)
        if len(calls) == call:
            raise _Killed()
        return real(*args, **kwargs)

    monkeypatch.setattr(upload_identify, "record_identification", record_identification)
    return lambda: monkeypatch.setattr(upload_identify, "record_identification", real)


def _restart(db_session, ids_first, last):
    """Come all'avvio (upload_jobs.reset_interrupted e un kick per job), con i
    job svegliati nell'ordine dato: (ripresi, svegliati dalla ripresa)."""
    from nazgarr.upload import analysis as upload_analysis

    db_session.rollback()
    resumed = upload_jobs.reset_interrupted(db_session)
    kicked = []
    worker = type("W", (), {"kick": lambda self, job_id, status: kicked.append(job_id)})()
    for job_id in [*ids_first, last]:
        job = db_session.get(UploadJob, job_id)
        if job is None:
            continue  # tolto da un altro passo nel frattempo
        handler = {"identifying": upload_identify.handle, "analyzing": upload_analysis.handle}[job.status]
        handler(db_session, job, worker)
    return resumed, kicked


def test_a_split_stopped_by_a_restart_is_done_again_without_leftovers(db_session, tmp_path, monkeypatch):
    """Audit 2026-10-18: un riavvio a metà divisione faceva ripartire il pack
    intero (l'analisi non sapeva della divisione) e, accanto, gli episodi
    già creati."""
    restore = _crash_on(monkeypatch, 3)  # il pack, il primo episodio, poi il kill sul secondo
    with pytest.raises(_Killed):
        _identified(db_session, tmp_path, monkeypatch)
    restore()
    parent, first, second = db_session.query(UploadJob).order_by(UploadJob.id).all()
    assert (parent.status, parent.stage, first.status, second.status) == (
        "analyzing", upload_identify.SPLIT_PENDING, "analyzing", "identifying")

    resumed, kicked = _restart(db_session, [second.id, first.id], parent.id)

    assert sorted(resumed) == sorted([parent.id, first.id, second.id])
    jobs = db_session.query(UploadJob).order_by(UploadJob.id).all()
    assert jobs[0].id == parent.id and parent.status == "cancelled"
    children = jobs[1:]
    assert [(c.kind, c.episode, c.status, c.split_from_id) for c in children] == [
        ("episode", 1, "analyzing", parent.id), ("episode", 2, "analyzing", parent.id)]
    # Righe nuove (SQLite può ridare gli stessi id): ognuna creata una volta.
    assert [[e.code for e in c.events].count("job_created") for c in children] == [1, 1]
    assert kicked == [c.id for c in children]
    assert "job_split" in [e.code for e in parent.events]


def test_a_split_by_hand_stopped_by_a_restart_is_done_again(db_session, tmp_path, monkeypatch):
    """Audit 2026-10-18 (finding 155): "Dividi in episodi" al match non
    scriveva la divisione chiesta. Un riavvio a metà toglieva gli episodi
    rimasti, ma il pack andava poi alla decisione intero: la divisione
    chiesta dall'utente spariva senza dirlo."""
    disk = make_disk(db_session, tmp_path)
    make_tracker(db_session)
    settings_repo.set_setting(db_session, upload_identify.AUTO_MATCH_SETTING, "0")  # si ferma al match
    _release(tmp_path)
    _tmdb(monkeypatch, 8)
    job = upload_jobs.create_job(db_session, disk, f"releases/{FOLDER}")
    upload_identify.handle(db_session, job, None)
    assert job.status == "awaiting_match"
    # Spenta l'opzione della cartella osservata: la divisione chiesta a mano vale lo stesso.
    settings_repo.set_setting(db_session, upload_split.SPLIT_SETTING, "false")
    details = upload_identify.tmdb_client(db_session).full_details("tv", 1399)
    upload_identify.confirm(db_session, job, content_type="tv", tmdb_id=1399, kind="season_pack", seasons=[1],
                            episode=None, details=details, split_requested=True)  # come split_upload
    db_session.commit()
    assert (job.status, job.stage) == ("analyzing", upload_identify.SPLIT_REQUESTED)
    restore = _crash_on(monkeypatch, 2)  # il primo episodio, poi il kill sul secondo
    with pytest.raises(_Killed):
        upload_split.split(db_session, job, details)
    restore()
    parent_id = job.id
    db_session.rollback()
    leftovers = [c.id for c in db_session.query(UploadJob).filter(UploadJob.split_from_id == parent_id)]

    _resumed, kicked = _restart(db_session, leftovers, parent_id)

    parent = db_session.get(UploadJob, parent_id)
    children = db_session.query(UploadJob).filter(UploadJob.split_from_id == parent_id).order_by(UploadJob.id).all()
    assert parent.status == "cancelled" and "job_split" in [e.code for e in parent.events]
    assert [(c.kind, c.episode, c.status) for c in children] == [("episode", 1, "analyzing"),
                                                                 ("episode", 2, "analyzing")]
    assert kicked == [c.id for c in children]


def test_split_by_hand_writes_the_split_with_the_match(client, tmp_path, monkeypatch):
    session = client.app.state.session_factory()
    disk = make_disk(session, tmp_path)
    make_tracker(session)
    settings_repo.set_setting(session, upload_identify.AUTO_MATCH_SETTING, "0")
    _release(tmp_path)
    _tmdb(monkeypatch, 8)
    job = upload_jobs.create_job(session, disk, f"releases/{FOLDER}")
    upload_identify.handle(session, job, None)
    job_id = job.id
    session.close()
    monkeypatch.setattr(client.app.state.upload_worker, "kick", lambda job_id, status: None)
    real_split, stages = upload_split.split, []

    def split(session, job, details):
        stages.append(job.stage)  # quello che un riavvio adesso troverebbe nel DB
        return real_split(session, job, details)

    monkeypatch.setattr(upload_split, "split", split)
    response = client.post(f"/api/uploads/{job_id}/split",
                           json={"content_type": "tv", "tmdb_id": 1399, "kind": "season_pack", "seasons": [1]})

    assert response.status_code == 200, response.text
    assert stages == [upload_identify.SPLIT_REQUESTED]
    assert client.get(f"/api/uploads/{job_id}").json()["stage"] is None  # chiusa dalla divisione


def test_a_kill_right_after_the_split_closes_keeps_the_episodes(db_session, tmp_path, monkeypatch):
    """Audit 2026-10-18: l'annullamento del pack e l'evento della divisione
    erano due commit; un riavvio fra i due lasciava il pack annullato senza
    "divisione", e ogni episodio, ripreso, si toglieva da solo. Ora vanno
    insieme: un kill subito dopo li trova entrambi, e gli episodi restano."""
    real_transition = upload_jobs.transition

    def transition(session, job, expected, new, *args, **kwargs):
        done = real_transition(session, job, expected, new, *args, **kwargs)
        if new == "cancelled":
            raise _Killed()
        return done

    monkeypatch.setattr(upload_split.upload_jobs, "transition", transition)
    with pytest.raises(_Killed):
        _identified(db_session, tmp_path, monkeypatch)
    monkeypatch.setattr(upload_split.upload_jobs, "transition", real_transition)
    db_session.rollback()
    parent, first, second = db_session.query(UploadJob).order_by(UploadJob.id).all()
    assert parent.status == "cancelled" and "job_split" in [e.code for e in parent.events]

    # Al riavvio ogni episodio riparte da sé (l'analisi, qui non serve farla).
    upload_jobs.reset_interrupted(db_session)
    assert [upload_identify.drop_split_orphan(db_session, c) for c in (second, first)] == [False, False]
    children = db_session.query(UploadJob).filter(UploadJob.split_from_id == parent.id).order_by(UploadJob.id).all()
    assert [(c.id, c.episode, c.status) for c in children] == [(first.id, 1, "analyzing"), (second.id, 2, "analyzing")]


def test_an_old_kick_during_the_new_split_leaves_the_new_episode_alone(db_session, tmp_path, monkeypatch):
    """Audit 2026-10-18: la nuova divisione dopo un riavvio crea upload che
    possono avere l'id di quelli appena tolti (SQLite riusa gli id). Un kick
    vecchio per quell'id, arrivato mentre il pack si divide, trovava il nuovo
    episodio col pack non ancora chiuso e lo toglieva: la divisione falliva e
    il pack andava avanti intero."""
    restore = _crash_on(monkeypatch, 3)
    with pytest.raises(_Killed):
        _identified(db_session, tmp_path, monkeypatch)
    restore()
    parent = db_session.query(UploadJob).order_by(UploadJob.id).first()
    parent_id = parent.id

    real_scan = upload_split.scan_source
    stale = []

    def scan_source(path, *args, **kwargs):
        # Il worker, in un altro thread, con un kick di prima del riavvio.
        other = db_session.__class__(bind=db_session.get_bind())
        newest = other.query(UploadJob).filter(UploadJob.split_from_id == parent_id).order_by(
            UploadJob.id.desc()).first()
        if newest is not None and not stale:
            stale.append(newest.id)
            upload_identify.handle(other, newest, None)
        other.close()
        return real_scan(path, *args, **kwargs)

    monkeypatch.setattr(upload_split, "scan_source", scan_source)
    from nazgarr.upload import analysis as upload_analysis

    # Se la divisione fallisse, il pack andrebbe al dupe check: mai verso la rete.
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter",
                        lambda t: (_ for _ in ()).throw(RuntimeError("offline")))
    _resumed, kicked = _restart(db_session, [], parent_id)

    parent = db_session.get(UploadJob, parent_id)
    children = db_session.query(UploadJob).filter(UploadJob.split_from_id == parent_id).order_by(UploadJob.id).all()
    assert parent.status == "cancelled" and "job_split" in [e.code for e in parent.events]
    assert stale and stale[0] in [c.id for c in children]
    assert [(c.episode, c.status) for c in children] == [(1, "analyzing"), (2, "analyzing")]
    assert kicked == [c.id for c in children]


def test_a_complete_season_after_a_restart_is_analyzed_as_a_pack(db_session, tmp_path, monkeypatch):
    """Lo stage della divisione si toglie anche quando non si divide: dopo,
    l'analisi è quella di sempre."""
    job, _kicked, _finished = _identified(db_session, tmp_path, monkeypatch, episodes_in_season=2)

    assert (job.status, job.stage) == ("analyzing", None)
