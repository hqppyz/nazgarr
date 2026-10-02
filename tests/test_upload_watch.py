import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from app import settings_repo, upload_identify, upload_jobs, upload_watch
from app.models import UploadJob, WatchEntry
from tests.upload_helpers import FakeTMDB, make_disk, make_tracker, tmdb_result, write_video

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(seconds=upload_watch.STABLE_SECONDS + 1)


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


def test_a_new_release_starts_once_it_stops_changing(db_session, tmp_path, watched):
    write_video(tmp_path / "releases" / "My.Movie.2024.1080p.WEB-DL.mkv")
    kicked = []

    assert upload_watch.scan(db_session, kick=lambda *a: kicked.append(a), now=T0) == []  # appena visto
    assert upload_watch.scan(db_session, now=T0 + timedelta(seconds=30)) == []  # non ancora stabile
    [job_id] = upload_watch.scan(db_session, kick=lambda *a: kicked.append(a), now=LATER)

    job = db_session.get(UploadJob, job_id)
    assert (job.origin, job.relative_path, job.status) == ("watch", "releases/My.Movie.2024.1080p.WEB-DL.mkv",
                                                          "identifying")
    assert kicked == [(job_id, "identifying")]
    # Una volta sola, anche dopo aver cancellato il job.
    upload_jobs.cancel_job(db_session, job)
    upload_jobs.delete_job(db_session, job)
    assert upload_watch.scan(db_session, now=LATER + timedelta(hours=1)) == []


def test_a_release_still_copying_waits(db_session, tmp_path, watched):
    folder = tmp_path / "releases" / "Show.S01.1080p"
    write_video(folder / "Show.S01E01.mkv")
    write_video(folder / "Show.S01E02.mkv.part")
    upload_watch.scan(db_session, now=T0)

    assert upload_watch.scan(db_session, now=LATER) == []  # un file parziale dentro

    os.rename(folder / "Show.S01E02.mkv.part", folder / "Show.S01E02.mkv")
    upload_watch.scan(db_session, now=LATER)
    assert upload_watch.scan(db_session, now=LATER + timedelta(seconds=upload_watch.STABLE_SECONDS + 1))


def test_the_releaser_name_is_the_group(db_session, tmp_path, watched):
    settings_repo.set_setting(db_session, upload_watch.RELEASER_SETTING, "  NZG ")
    write_video(tmp_path / "releases" / "My.Movie.2024.mkv")
    upload_watch.scan(db_session, now=T0)
    [job_id] = upload_watch.scan(db_session, now=LATER)

    assert json.loads(db_session.get(UploadJob, job_id).overrides_json) == {"group": "NZG"}


def test_what_was_there_when_the_folder_was_chosen_does_not_start(db_session, tmp_path, watched):
    write_video(tmp_path / "releases" / "Old.Release.2020.mkv")
    upload_watch.baseline(db_session, watched, now=T0)
    write_video(tmp_path / "releases" / "New.Release.2024.mkv")

    upload_watch.scan(db_session, now=T0)
    created = upload_watch.scan(db_session, now=LATER)

    assert [db_session.get(UploadJob, i).relative_path for i in created] == ["releases/New.Release.2024.mkv"]


def test_only_videos_and_folders_count_and_links_are_never_followed(db_session, tmp_path, watched):
    (tmp_path / "releases" / "notes.txt").write_text("x")
    (tmp_path / "releases" / ".hidden.mkv").write_bytes(b"x" * 10)
    elsewhere = write_video(tmp_path / "elsewhere" / "Secret.mkv")
    os.symlink(elsewhere, tmp_path / "releases" / "Link.mkv")

    upload_watch.scan(db_session, now=T0)
    assert upload_watch.scan(db_session, now=LATER) == []
    assert db_session.query(WatchEntry).count() == 0


def test_without_a_tracker_to_upload_to_it_waits_and_retries(db_session, tmp_path):
    (tmp_path / "releases").mkdir()
    disk = make_disk(db_session, tmp_path)
    disk.watch_rel_path = "releases"
    db_session.commit()
    write_video(tmp_path / "releases" / "My.Movie.2024.mkv")
    upload_watch.scan(db_session, now=T0)
    assert upload_watch.scan(db_session, now=LATER) == []

    make_tracker(db_session)
    assert len(upload_watch.scan(db_session, now=LATER + timedelta(minutes=1))) == 1


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


def test_an_unsure_or_manual_match_waits_for_the_user(db_session, tmp_path, monkeypatch):
    make_tracker(db_session)
    unsure = _identified(db_session, monkeypatch, tmp_path, "The.Matrix.1999.1080p.mkv",
                         {("movie", "The Matrix", 1999): [tmdb_result(9999, "The Matrix Revisited", 2001)]})
    assert unsure.status == "awaiting_match"
    assert any(e.code == "auto_match_skipped" for e in unsure.events)

    manual = _identified(db_session, monkeypatch, tmp_path, "Dune.2021.mkv",
                         {("movie", "Dune", 2021): [tmdb_result(438631, "Dune", 2021)]}, origin=None)
    assert manual.status == "awaiting_match"  # creato a mano: si sceglie sempre


def test_the_threshold_can_be_raised_or_turned_off(db_session, tmp_path, monkeypatch):
    make_tracker(db_session)
    settings_repo.set_setting(db_session, upload_identify.AUTO_MATCH_SETTING, "0")
    job = _identified(db_session, monkeypatch, tmp_path, "The.Matrix.1999.1080p.mkv",
                      {("movie", "The Matrix", 1999): [tmdb_result(603, "The Matrix", 1999)]})
    assert job.status == "awaiting_match"
