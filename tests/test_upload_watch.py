import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from nazgarr import settings_repo, upload_identify, upload_jobs, upload_watch
from nazgarr.models import UploadJob, WatchEntry
from tests.upload_helpers import FakeTMDB, make_disk, make_tracker, tmdb_result, write_video

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
QUIET = timedelta(seconds=upload_watch.QUIET_SECONDS)


def _written_at(path, when):
    """La data di modifica di un file (o di tutto ciò che c'è in una cartella)."""
    for item in [path, *path.rglob("*")] if path.is_dir() else [path]:
        os.utime(item, (when.timestamp(), when.timestamp()))
    return path


@pytest.fixture
def watched(db_session, tmp_path):
    (tmp_path / "releases").mkdir()
    disk = make_disk(db_session, tmp_path)
    disk.watch_rel_path = "releases"
    db_session.commit()
    make_tracker(db_session)
    return disk


def _jobs(db_session):
    return db_session.query(UploadJob).order_by(UploadJob.id).all()


def test_a_release_moved_in_starts_right_away(db_session, tmp_path, watched):
    # Spostata dentro: la sua data di modifica è di prima, nessuno ci scrive.
    _written_at(write_video(tmp_path / "releases" / "My.Movie.2024.1080p.WEB-DL.mkv"), T0 - timedelta(hours=2))
    kicked = []

    [job_id] = upload_watch.scan(db_session, kick=lambda *a: kicked.append(a), now=T0)

    job = db_session.get(UploadJob, job_id)
    assert (job.origin, job.relative_path, job.status) == ("watch", "releases/My.Movie.2024.1080p.WEB-DL.mkv",
                                                          "identifying")
    assert kicked == [(job_id, "identifying")]
    # Una volta sola, anche dopo aver cancellato il job.
    upload_jobs.cancel_job(db_session, job)
    upload_jobs.delete_job(db_session, job)
    assert upload_watch.scan(db_session, now=T0 + timedelta(hours=1)) == []


def test_a_copy_starts_once_nobody_writes_to_it(db_session, tmp_path, watched):
    video = write_video(tmp_path / "releases" / "My.Movie.2024.mkv")
    _written_at(video, T0)  # appena scritto
    assert upload_watch.scan(db_session, now=T0 + timedelta(seconds=5)) == []

    # La copia continua: dimensione e data cambiano.
    video.write_bytes(b"x" * 40000)
    _written_at(video, T0 + timedelta(seconds=8))
    assert upload_watch.scan(db_session, now=T0 + timedelta(seconds=10)) == []

    # Finita: dopo QUIET_SECONDS senza scritture parte.
    assert upload_watch.scan(db_session, now=T0 + timedelta(seconds=8) + QUIET) != []


def test_a_release_still_copying_waits(db_session, tmp_path, watched):
    folder = tmp_path / "releases" / "Show.S01.1080p"
    write_video(folder / "Show.S01E01.mkv")
    write_video(folder / "Show.S01E02.mkv.part")
    _written_at(folder, T0 - timedelta(hours=1))

    assert upload_watch.scan(db_session, now=T0) == []  # un file parziale dentro

    os.rename(folder / "Show.S01E02.mkv.part", folder / "Show.S01E02.mkv")
    _written_at(folder, T0 - timedelta(hours=1))
    assert upload_watch.scan(db_session, now=T0 + timedelta(seconds=10)) != []


def test_the_releaser_name_is_the_group_and_what_is_already_there_starts_too(db_session, tmp_path, watched):
    # La cartella è solo di passaggio: anche quello che c'era già parte.
    settings_repo.set_setting(db_session, upload_watch.RELEASER_SETTING, "  NZG ")
    _written_at(write_video(tmp_path / "releases" / "My.Movie.2024.mkv"), T0 - timedelta(days=3))

    [job_id] = upload_watch.scan(db_session, now=T0)

    assert json.loads(db_session.get(UploadJob, job_id).overrides_json) == {"group": "NZG"}


def test_only_videos_and_folders_count_and_links_are_never_followed(db_session, tmp_path, watched):
    (tmp_path / "releases" / "notes.txt").write_text("x")
    (tmp_path / "releases" / ".hidden.mkv").write_bytes(b"x" * 10)
    elsewhere = write_video(tmp_path / "elsewhere" / "Secret.mkv")
    os.symlink(elsewhere, tmp_path / "releases" / "Link.mkv")

    assert upload_watch.scan(db_session, now=T0 + timedelta(days=1)) == []
    assert db_session.query(WatchEntry).count() == 0


def test_without_a_tracker_to_upload_to_it_waits_and_retries(db_session, tmp_path):
    (tmp_path / "releases").mkdir()
    disk = make_disk(db_session, tmp_path)
    disk.watch_rel_path = "releases"
    db_session.commit()
    _written_at(write_video(tmp_path / "releases" / "My.Movie.2024.mkv"), T0 - timedelta(hours=1))
    assert upload_watch.scan(db_session, now=T0) == []

    make_tracker(db_session)
    assert len(upload_watch.scan(db_session, now=T0 + timedelta(seconds=10))) == 1


def _identified(db_session, monkeypatch, tmp_path, name, results, origin="watch"):
    monkeypatch.setattr(upload_identify.adapter_factory, "build_media_resolver",
                        lambda session, arr_index=None: type("R", (), {"SOURCE": "x", "resolve": lambda s, p: None})())
    details = {(r["content_type"], r["tmdb_id"]): r for rs in results.values() for r in rs}
    fake = FakeTMDB(search=results, details=details)
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)
    write_video(tmp_path / "releases" / name)
    disk = make_disk(db_session, tmp_path) if not db_session.query(UploadJob).count() else None
    job = upload_jobs.create_job(db_session, disk or db_session.get(UploadJob, 1).disk, f"releases/{name}",
                                 origin=origin)
    upload_identify.handle(db_session, job, None)
    return job


def test_a_sure_match_from_the_watched_folder_confirms_itself(db_session, tmp_path, monkeypatch):
    make_tracker(db_session)
    job = _identified(db_session, monkeypatch, tmp_path, "The.Matrix.1999.1080p.mkv",
                      {("movie", "The Matrix", 1999): [tmdb_result(603, "The Matrix", 1999)]})

    assert (job.status, job.tmdb_id) == ("analyzing", 603)
    assert any(e.code == "auto_matched" for e in job.events)


def test_an_unsure_match_waits_and_a_manual_upload_matches_too(db_session, tmp_path, monkeypatch):
    make_tracker(db_session)
    unsure = _identified(db_session, monkeypatch, tmp_path, "The.Matrix.1999.1080p.mkv",
                         {("movie", "The Matrix", 1999): [tmdb_result(9999, "The Matrix Revisited", 2001)]})
    assert unsure.status == "awaiting_match"
    assert any(e.code == "auto_match_skipped" for e in unsure.events)

    # Anche un upload creato a mano si conferma da solo, se è sicuro.
    manual = _identified(db_session, monkeypatch, tmp_path, "Dune.2021.mkv",
                         {("movie", "Dune", 2021): [tmdb_result(438631, "Dune", 2021)]}, origin=None)
    assert manual.status == "analyzing"


def test_the_threshold_can_be_raised_or_turned_off(db_session, tmp_path, monkeypatch):
    make_tracker(db_session)
    settings_repo.set_setting(db_session, upload_identify.AUTO_MATCH_SETTING, "0")
    job = _identified(db_session, monkeypatch, tmp_path, "The.Matrix.1999.1080p.mkv",
                      {("movie", "The Matrix", 1999): [tmdb_result(603, "The Matrix", 1999)]})
    assert job.status == "awaiting_match"
