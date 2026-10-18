"""Le stagioni scelte di una cartella con più stagioni (nazgarr/upload/pack.py
season_selection). Segnalato 2026-10-11: la serie intera arrivata nella
cartella osservata finiva tutta nel season pack della stagione scelta."""

import json
import os

import pytest

from nazgarr.core import settings_repo
from nazgarr.core.models import UploadJob
from nazgarr.library.episode_orders import EpisodeOrder, OrderEpisode
from nazgarr.upload import analysis as upload_analysis
from nazgarr.upload import execute as upload_execute
from nazgarr.upload import file_names as upload_file_names
from nazgarr.upload import identify as upload_identify
from nazgarr.upload import inventory as upload_inventory
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload import pack as upload_pack
from nazgarr.upload import split as upload_split
from tests.upload_helpers import FakeTMDB, make_disk, make_tracker, tmdb_result, write_video

FOLDER = "Show.S01-S03.1080p.WEB-DL-GRP"
SHOW = tmdb_result(1399, "Show", 2024, "tv")
DETAILS = {**SHOW, "seasons": [{"season_number": s, "episode_count": 2} for s in (1, 2, 3)]}


def _flat(folder):
    """Tutte le stagioni nella stessa cartella, con i nomi "S01E01"."""
    for season in (1, 2, 3):
        for episode in (1, 2):
            write_video(folder / f"Show.S{season:02d}E{episode:02d}.1080p.WEB-DL-GRP.mkv")
    (folder / "Show.S01E01.1080p.WEB-DL-GRP.it.srt").write_text("1")
    (folder / "Show.S02E01.1080p.WEB-DL-GRP.it.srt").write_text("1")
    (folder / "Show.nfo").write_text("notes")


def _nested(folder):
    """Una sottocartella per stagione; nella S03 la stagione la dice solo la cartella."""
    for season in (1, 2):
        for episode in (1, 2):
            write_video(folder / f"Season {season:02d}" / f"Show.S{season:02d}E{episode:02d}.mkv")
    for episode in (1, 2):
        write_video(folder / "Season 03" / f"{episode:02d}.mkv")
    (folder / "Season 03" / "Show.nfo").write_text("notes")


@pytest.fixture
def at_match(db_session, tmp_path, monkeypatch):
    """Una cartella della cartella osservata, identificata e ferma al match."""
    monkeypatch.setattr(upload_identify.adapter_factory, "build_media_resolver",
                        lambda session, arr_index=None: type("R", (), {"SOURCE": "x", "resolve": lambda s, p: None})())
    fake = FakeTMDB(search={("tv", "Show", None): [SHOW]}, details={("tv", 1399): DETAILS})
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)
    settings_repo.set_setting(db_session, upload_identify.AUTO_MATCH_SETTING, "0")
    make_tracker(db_session)
    disk = make_disk(db_session, tmp_path)
    disk.watch_rel_path = "watch"
    db_session.commit()

    def make(layout=_flat, folder=FOLDER):
        layout(tmp_path / "watch" / folder)
        job = upload_jobs.create_job(db_session, disk, f"watch/{folder}", origin="watch")
        upload_identify.handle(db_session, job, None)
        assert job.status == "awaiting_match"
        return job

    return make


def _confirm(session, job, kind, seasons, **kwargs):
    upload_identify.confirm(session, job, content_type="tv", tmdb_id=1399, kind=kind, seasons=seasons,
                            episode=None, details=DETAILS, **kwargs)
    session.commit()


def _names(job):
    return sorted(f.relative for f in upload_inventory.job_files(job))


def test_a_season_of_a_flat_folder_takes_only_its_episodes(db_session, tmp_path, at_match):
    job = at_match()
    assert (job.kind, json.loads(job.seasons_json)) == ("complete_pack", [1, 2, 3])

    _confirm(db_session, job, "season_pack", [2])

    assert job.status == "analyzing"
    assert upload_pack.is_pack(job)
    assert _names(job) == ["Show.S02E01.1080p.WEB-DL-GRP.it.srt", "Show.S02E01.1080p.WEB-DL-GRP.mkv",
                           "Show.S02E02.1080p.WEB-DL-GRP.mkv"]
    assert job.source_path == str(tmp_path / "watch" / FOLDER)
    assert upload_pack.name(job) == "Show.S02.1080p.WEB-DL-GRP"
    layout = json.loads(job.layout_json)
    assert (layout["kind"], layout["seasons"], layout["episodes_by_season"]) == ("season_pack", [2], {"2": [1, 2]})
    assert os.path.basename(layout["main_video"]).startswith("Show.S02E")
    event = next(e for e in job.events if e.code == "pack_from_seasons")
    assert json.loads(event.params_json) == {"seasons": "S02", "count": 2, "left": 4}


def test_a_season_subfolder_is_the_source(db_session, tmp_path, at_match):
    job = at_match(_nested)

    _confirm(db_session, job, "season_pack", [3])

    assert job.source_path == str(tmp_path / "watch" / FOLDER / "Season 03")
    assert job.relative_path == f"watch/{FOLDER}/Season 03"
    assert _names(job) == ["01.mkv", "02.mkv"]  # l'nfo resta fuori, come nei pack scelti a mano
    assert json.loads(job.layout_json)["episodes_by_season"] == {"3": [1, 2]}  # dalla sottocartella
    # Gli episodi non dicono la stagione: il nome viene dalla cartella.
    assert upload_pack.name(job) == "Show.S03.1080p.WEB-DL-GRP"
    files = [(f.path, f.size) for f in upload_inventory.job_files(job)]
    assert upload_analysis.name_source(job, files, [], None) == {
        "name": "Show.S03.1080p.WEB-DL-GRP", "origin": "source", "fallback": FOLDER}


def test_some_seasons_of_a_complete_pack_keep_their_season_folders(db_session, at_match):
    job = at_match()

    _confirm(db_session, job, "complete_pack", [1, 2])

    assert [r for r in _names(job) if r.endswith(".mkv")] == [
        f"Show.S{s:02d}E{e:02d}.1080p.WEB-DL-GRP.mkv" for s in (1, 2) for e in (1, 2)]
    plan = upload_file_names.plan(db_session, job, "original")
    assert plan.content_name == "Show.S01-S02.1080p.WEB-DL-GRP"
    assert sorted(target for _source, target in plan.files)[:2] == [
        "Show.S01-S02.1080p.WEB-DL-GRP/Season 01/Show.S01E01.1080p.WEB-DL-GRP.it.srt",
        "Show.S01-S02.1080p.WEB-DL-GRP/Season 01/Show.S01E01.1080p.WEB-DL-GRP.mkv",
    ]


@pytest.mark.parametrize(("kind", "seasons"), [
    ("complete_pack", [1, 2, 3]),  # tutte: la cartella com'è
    ("season_pack", [5]),  # nessuna di quelle dei file: l'utente rinumera
])
def test_the_folder_stays_whole(db_session, at_match, kind, seasons):
    job = at_match()

    _confirm(db_session, job, kind, seasons)

    assert not upload_pack.is_pack(job)
    assert len([r for r in _names(job) if r.endswith(".mkv")]) == 6
    assert not any(e.code == "pack_from_seasons" for e in job.events)


def test_back_to_the_match_gives_the_whole_folder_back(db_session, tmp_path, at_match):
    job = at_match()
    _confirm(db_session, job, "season_pack", [1])
    upload_jobs.transition(db_session, job, "analyzing", "awaiting_decision")

    upload_jobs.back_to_match(db_session, job)

    assert job.status == "awaiting_match"
    assert not upload_pack.is_pack(job)
    assert (job.relative_path, job.source_path) == (f"watch/{FOLDER}", str(tmp_path / "watch" / FOLDER))
    assert json.loads(job.layout_json)["seasons"] == [1, 2, 3]

    _confirm(db_session, job, "season_pack", [3])
    assert [r for r in _names(job) if r.endswith(".mkv")] == [
        "Show.S03E01.1080p.WEB-DL-GRP.mkv", "Show.S03E02.1080p.WEB-DL-GRP.mkv"]


def _order(key, seasons):
    return EpisodeOrder(key, key, "tmdb", {
        season: [OrderEpisode(number, refs=[ref]) for number, ref in episodes] for season, episodes in seasons.items()
    }).to_dict()


def test_the_seasons_are_those_of_the_chosen_ordering(db_session, tmp_path, at_match):
    """I file numerano una stagione sola da 4 episodi, l'ordinamento scelto la
    divide in due: la sua seconda stagione sono gli episodi 3 e 4 dei file."""
    def single_season(folder):
        for episode in (1, 2, 3, 4):
            write_video(folder / f"Show.S01E{episode:02d}.1080p.WEB-DL-GRP.mkv")

    job = at_match(single_season, "Show.S01.1080p.WEB-DL-GRP")
    files = _order("files", {1: [(e, (1, e)) for e in (1, 2, 3, 4)]})
    chosen = _order("split", {1: [(1, (1, 1)), (2, (1, 2))], 2: [(1, (1, 3)), (2, (1, 4))]})
    orders = {"orders": [files, chosen], "files_order": "files", "found": {}, "recommended": "split"}

    _confirm(db_session, job, "season_pack", [2], order_key="split", orders=orders)

    assert _names(job) == ["Show.S01E03.1080p.WEB-DL-GRP.mkv", "Show.S01E04.1080p.WEB-DL-GRP.mkv"]


def test_a_chosen_season_splits_into_its_own_episodes(db_session, tmp_path, at_match):
    job = at_match(_nested)
    _confirm(db_session, job, "season_pack", [1])

    children = upload_split.split(db_session, job, DETAILS)

    assert [c.relative_path for c in children] == [
        f"watch/{FOLDER}/Season 01/Show.S01E{e:02d}.mkv" for e in (1, 2)]
    assert [(c.kind, json.loads(c.seasons_json), c.episode) for c in children] == [
        ("episode", [1], 1), ("episode", [1], 2)]


def test_the_watched_folder_keeps_the_other_seasons(db_session, tmp_path, at_match):
    """A upload fatto dalla cartella osservata se ne vanno solo i file della
    stagione caricata (quelli che questo upload ha messo in seed)."""
    job = at_match()
    _confirm(db_session, job, "season_pack", [2])
    seed = tmp_path / "seed"
    seed.mkdir()
    seeded = {}
    for f in upload_inventory.job_files(job):
        copy = seed / os.path.basename(f.path)
        os.link(f.path, copy)
        st = os.stat(copy)
        seeded[(st.st_dev, st.st_ino)] = os.path.realpath(copy)
    for target in job.targets:
        target.status, target.action = "done", "upload"
    db_session.commit()

    upload_execute._clear_watch_source(db_session, job, {}, {"seeded": {job.targets[0].id: seeded}})

    left = sorted(os.listdir(tmp_path / "watch" / FOLDER))
    assert [n for n in left if n.endswith(".mkv")] == [
        f"Show.S{s:02d}E{e:02d}.1080p.WEB-DL-GRP.mkv" for s in (1, 3) for e in (1, 2)]
    assert "Show.S01E01.1080p.WEB-DL-GRP.it.srt" in left and "Show.nfo" in left
    assert db_session.query(UploadJob).count() == 1


# --- dalla cartella osservata: un upload per stagione (nazgarr/upload/split.py) ---


@pytest.fixture
def from_watch(db_session, tmp_path, monkeypatch):
    """Una cartella con tre stagioni nella cartella osservata, con il match
    automatico: (job, job svegliati)."""
    from nazgarr.library import episode_orders

    def run(episode_counts=(2, 2, 2), origin="watch"):
        monkeypatch.setattr(upload_identify.adapter_factory, "build_media_resolver",
                            lambda session, arr_index=None: type("R", (), {"SOURCE": "x",
                                                                           "resolve": lambda s, p: None})())
        details = {**SHOW, "seasons": [{"season_number": s, "episode_count": n}
                                       for s, n in zip((1, 2, 3), episode_counts, strict=True)]}
        fake = FakeTMDB(search={("tv", "Show", None): [SHOW]}, details={("tv", 1399): details})
        monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)
        monkeypatch.setattr(episode_orders, "for_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        # Il nome della release non ha l'anno: il match vale 0.85.
        settings_repo.set_setting(db_session, upload_identify.AUTO_MATCH_SETTING, "0.8")
        make_tracker(db_session)
        disk = make_disk(db_session, tmp_path)
        disk.watch_rel_path = "watch"
        db_session.commit()
        _flat(tmp_path / "watch" / FOLDER)
        job = upload_jobs.create_job(db_session, disk, f"watch/{FOLDER}", origin=origin)
        kicked = []
        worker = type("W", (), {"kick": lambda self, job_id, status: kicked.append(job_id)})()
        upload_identify.handle(db_session, job, worker)
        return job, kicked

    return run


def _children(session, job):
    return session.query(UploadJob).filter(UploadJob.split_from_id == job.id).order_by(UploadJob.id).all()


def test_several_seasons_become_one_upload_per_season(db_session, from_watch):
    job, kicked = from_watch()

    assert job.status == "cancelled"
    seasons = _children(db_session, job)
    assert [(c.kind, json.loads(c.seasons_json), c.status, c.origin) for c in seasons] == [
        ("season_pack", [s], "analyzing", "watch") for s in (1, 2, 3)]
    assert [[r for r in _names(c) if r.endswith(".mkv")] for c in seasons] == [
        [f"Show.S{s:02d}E{e:02d}.1080p.WEB-DL-GRP.mkv" for e in (1, 2)] for s in (1, 2, 3)]
    assert kicked == [c.id for c in seasons]
    event = next(e for e in job.events if e.code == "job_split_seasons")
    assert json.loads(event.params_json) == {"count": 3, "jobs": [c.id for c in seasons]}
    with pytest.raises(upload_jobs.UploadJobError, match="upload_job_split_seasons"):
        upload_jobs.resume_job(db_session, job)


def test_an_incomplete_season_then_becomes_episodes(db_session, from_watch):
    job, kicked = from_watch(episode_counts=(2, 8, 2))

    first, second, third = _children(db_session, job)
    assert second.status == "cancelled"  # 2 episodi su 8
    episodes = _children(db_session, second)
    assert [(c.kind, json.loads(c.seasons_json), c.episode) for c in episodes] == [
        ("episode", [2], 1), ("episode", [2], 2)]
    assert sorted(kicked) == sorted([first.id, third.id, *(c.id for c in episodes)])


@pytest.mark.parametrize("origin", ["watch", None])
def test_the_option_off_or_a_manual_upload_keep_the_complete_pack(db_session, from_watch, origin):
    if origin == "watch":
        settings_repo.set_setting(db_session, upload_split.SEASONS_SETTING, "false")
    job, kicked = from_watch(origin=origin)

    assert (job.status, job.kind, json.loads(job.seasons_json)) == ("analyzing", "complete_pack", [1, 2, 3])
    assert not upload_pack.is_pack(job)
    assert kicked == []


def test_the_folder_goes_once_every_season_is_out(db_session, tmp_path, from_watch):
    job, _kicked = from_watch()
    seasons = _children(db_session, job)
    folder = tmp_path / "watch" / FOLDER
    watch = str(tmp_path / "watch")

    for season in seasons[:2]:  # spostate nella cartella delle release dai loro upload
        for f in upload_inventory.job_files(season):
            os.remove(f.path)
        upload_execute._remove_split_folder(db_session, season, watch)
        assert folder.is_dir()  # c'è ancora la S03

    for f in upload_inventory.job_files(seasons[2]):
        os.remove(f.path)
    upload_execute._remove_split_folder(db_session, seasons[2], watch)
    assert not folder.exists()
    removed = next(e for e in seasons[2].events if e.code == "watch_folder_removed")
    assert json.loads(removed.params_json)["files"] == ["Show.nfo"]
