import json

import pytest
from sqlalchemy import inspect, text

from app import db as db_module
from app import upload, upload_jobs, upload_profiles
from app.fs_scope import ScopeViolation
from app.models import Disk, UploadJob, UploadTarget
from app.upload_jobs import UploadJobError
from app.upload_worker import UploadWorker
from tests.upload_helpers import InlineExecutor, make_client, make_disk, make_tracker, write_video


def _job(db_session, tmp_path, **kwargs):
    write_video(tmp_path / "media" / "Movie.2024.1080p.WEB.mkv")
    disk = db_session.query(Disk).first() or make_disk(db_session, tmp_path)
    return upload_jobs.create_job(db_session, disk, "media/Movie.2024.1080p.WEB.mkv", **kwargs)


def test_create_job_targets_every_upload_tracker_with_its_client(db_session, tmp_path):
    fallback = make_client(db_session, "first")
    chosen = make_client(db_session, "chosen")
    a = make_tracker(db_session, "a", torrent_client_id=chosen.id)
    b = make_tracker(db_session, "b")
    make_tracker(db_session, "no-profile", with_profile=False)
    make_tracker(db_session, "disabled", enabled=False)

    job = _job(db_session, tmp_path, forced_ids={"tmdb": " 603 ", "imdb": "", "tvdb": None})

    assert job.status == "identifying"
    assert job.is_dir is False
    assert {t.tracker_id: t.torrent_client_id for t in job.targets} == {a.id: chosen.id, b.id: fallback.id}
    assert json.loads(job.forced_ids_json) == {"tmdb": "603"}
    assert [e.code for e in job.events] == ["job_created"]


def test_create_job_with_explicit_trackers(db_session, tmp_path):
    make_tracker(db_session, "a")
    b = make_tracker(db_session, "b")

    job = _job(db_session, tmp_path, tracker_ids=[b.id, b.id])

    assert [t.tracker_id for t in job.targets] == [b.id]


def test_create_job_rejects_tracker_without_profile(db_session, tmp_path):
    t = make_tracker(db_session, "a", with_profile=False)

    with pytest.raises(UploadJobError) as exc:
        _job(db_session, tmp_path, tracker_ids=[t.id])
    assert exc.value.code == "upload_tracker_not_available"


def test_create_job_requires_a_tracker(db_session, tmp_path):
    with pytest.raises(UploadJobError) as exc:
        _job(db_session, tmp_path)
    assert exc.value.code == "upload_no_trackers"


def test_create_job_accepts_folders_but_not_the_disk_root(db_session, tmp_path):
    make_tracker(db_session)
    write_video(tmp_path / "Show.S01" / "Show.S01E01.mkv")
    disk = make_disk(db_session, tmp_path)

    job = upload_jobs.create_job(db_session, disk, "Show.S01")
    assert job.is_dir is True

    with pytest.raises(UploadJobError) as exc:
        upload_jobs.create_job(db_session, disk, "")
    assert exc.value.code == "upload_source_is_disk_root"
    with pytest.raises(ScopeViolation):
        upload_jobs.create_job(db_session, disk, "../outside")


def test_transition_is_conditional(db_session, tmp_path):
    make_tracker(db_session)
    job = _job(db_session, tmp_path)

    assert upload_jobs.transition(db_session, job, "identifying", "awaiting_match", title="X")
    assert job.status == "awaiting_match" and job.title == "X"
    assert not upload_jobs.transition(db_session, job, "identifying", "failed")
    assert job.status == "awaiting_match"
    assert upload_jobs.transition(db_session, job, "awaiting_match", "done")
    assert job.finished_at is not None


def test_cancel_and_delete(db_session, tmp_path):
    make_tracker(db_session)
    job = _job(db_session, tmp_path)

    with pytest.raises(UploadJobError):
        upload_jobs.delete_job(db_session, job)  # il worker ci sta lavorando
    upload_jobs.cancel_job(db_session, job)
    assert job.status == "cancelled"
    with pytest.raises(UploadJobError):
        upload_jobs.cancel_job(db_session, job)

    job_id = job.id
    upload_jobs.delete_job(db_session, job)
    assert db_session.get(UploadJob, job_id) is None
    assert db_session.query(UploadTarget).count() == 0


def test_reset_interrupted_never_repeats_an_upload(db_session, tmp_path):
    make_tracker(db_session, "a")
    make_tracker(db_session, "b")
    job = _job(db_session, tmp_path)
    job.status = "running"
    job.targets[0].status = "uploading"
    job.targets[1].status = "preparing"
    db_session.commit()

    assert upload_jobs.reset_interrupted(db_session) == [job.id]

    db_session.refresh(job)
    assert job.status == "queued"
    assert [t.status for t in job.targets] == ["failed", "approved"]
    assert job.targets[0].error_message == "interrupted"


def test_worker_runs_light_states_until_a_gate(db_session, tmp_path):
    make_tracker(db_session)
    job = _job(db_session, tmp_path)
    seen = []

    def identify(session, j, worker):
        seen.append("identify")
        upload_jobs.transition(session, j, "identifying", "analyzing")

    def analyze(session, j, worker):
        seen.append("analyze")
        upload_jobs.transition(session, j, "analyzing", "awaiting_decision")

    factory = lambda: db_session.__class__(bind=db_session.get_bind())  # noqa: E731
    worker = UploadWorker(
        factory, str(tmp_path), handlers={"identifying": identify, "analyzing": analyze},
        light_executor=InlineExecutor(), heavy_executor=InlineExecutor(),
    )
    worker.kick(job.id, job.status)

    db_session.refresh(job)
    assert seen == ["identify", "analyze"]
    assert job.status == "awaiting_decision"


def test_worker_marks_failed_on_error_and_on_missing_handler(db_session, tmp_path):
    make_tracker(db_session)
    job = _job(db_session, tmp_path)

    def boom(session, j, worker):
        raise UploadJobError("upload_source_unreadable", error="EIO")

    factory = lambda: db_session.__class__(bind=db_session.get_bind())  # noqa: E731
    worker = UploadWorker(
        factory, str(tmp_path), handlers={"identifying": boom},
        light_executor=InlineExecutor(), heavy_executor=InlineExecutor(),
    )
    worker.kick(job.id, job.status)
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_message == "upload_source_unreadable"
    assert job.events[-1].level == "error"
    assert json.loads(job.events[-1].params_json) == {"error": "EIO"}

    other = _job(db_session, tmp_path)
    upload_jobs.transition(db_session, other, "identifying", "queued")
    worker.kick(other.id, other.status)
    db_session.refresh(other)
    assert other.status == "failed"
    assert other.error_message == "upload_step_not_available"


def test_worker_does_not_fail_a_job_cancelled_while_running(db_session, tmp_path):
    make_tracker(db_session)
    job = _job(db_session, tmp_path)

    def cancel_then_crash(session, j, worker):
        other = db_session.__class__(bind=db_session.get_bind())
        upload_jobs.cancel_job(other, other.get(UploadJob, j.id))
        other.close()
        raise RuntimeError("late")

    factory = lambda: db_session.__class__(bind=db_session.get_bind())  # noqa: E731
    worker = UploadWorker(
        factory, str(tmp_path), handlers={"identifying": cancel_then_crash},
        light_executor=InlineExecutor(), heavy_executor=InlineExecutor(),
    )
    worker.kick(job.id, job.status)
    db_session.refresh(job)
    assert job.status == "cancelled"


def test_migration_drops_the_phase6_upload_job(tmp_path):
    engine = db_module.make_engine(str(tmp_path / "legacy.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE upload_job (id INTEGER PRIMARY KEY, tracker_id INTEGER, source_path TEXT)"))
        conn.execute(text("INSERT INTO upload_job (tracker_id, source_path) VALUES (1, '/x')"))

    db_module.migrate_legacy_upload_job(engine)
    db_module.apply_schema(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("upload_job")}
    assert "tracker_id" not in columns and "layout_json" in columns
    db_module.migrate_legacy_upload_job(engine)  # già nella forma nuova: no-op


def test_render_description_wraps_template_with_header_and_signature(db_session):
    from app import settings_repo

    tracker = make_tracker(db_session, with_profile=False)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    settings_repo.set_setting(db_session, "upload_description_header", "HEADER")
    settings_repo.set_setting(db_session, "upload_description_signature", "[i]Uploaded with Nazgarr[/i]")

    rendered = upload.render_description(db_session, profile, "MEDIAINFO", ["https://img.example/1.png"])

    assert rendered.startswith("HEADER\n\n")
    assert "https://img.example/1.png" in rendered
    assert rendered.endswith("\n\n[i]Uploaded with Nazgarr[/i]\n\n" + upload.credit_line())


def test_render_description_without_header_or_signature(db_session):
    tracker = make_tracker(db_session, with_profile=False)
    profile = upload_profiles.create_upload_profile(db_session, tracker, None)

    assert upload.render_description(db_session, profile, "MEDIAINFO", []) == "MEDIAINFO\n\n" + upload.credit_line()


def test_credit_line_has_version_and_project_link():
    from app.version import __version__

    line = upload.credit_line()
    assert f"v{__version__}" in line
    assert "[url=https://github.com/lktorrentz/nazgarr]" in line
    assert f"[img=16]{upload.CREDIT_LOGO_URL}[/img]" in line
    assert upload.CREDIT_LOGO_URL.endswith("/main/docs/assets/nazgarr-credit.png")


def test_reorder_queue(db_session, tmp_path):
    make_tracker(db_session)
    jobs = [_job(db_session, tmp_path) for _ in range(3)]
    for i, job in enumerate(jobs, start=1):
        upload_jobs.transition(db_session, job, "identifying", "queued", queue_position=i)
    upload_jobs.transition(db_session, jobs[0], "queued", "running")

    upload_jobs.reorder_queue(db_session, [jobs[2].id, 999, jobs[0].id])

    for job in jobs:
        db_session.refresh(job)
    assert [j.queue_position for j in jobs] == [1, 2, 1]  # quello partito non si tocca
    assert jobs[2].queue_position < jobs[1].queue_position
