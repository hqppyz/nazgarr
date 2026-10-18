"""La conferma prima di eliminare un tracker o un disco già usati
(decisione dell'utente, 2026-10-18): la storia va con loro (ON DELETE
CASCADE), e GET .../delete-preview dice quanto, in sola lettura."""

from nazgarr.core.models import SeedJob, UploadJob, UploadTarget
from tests.test_delete_used_tracker_and_disk import _count, _used_tracker_and_disk


def test_the_tracker_preview_counts_what_goes_with_it_and_changes_nothing(client):
    _disk_id, tracker_id = _used_tracker_and_disk(client)
    with client.app.state.session_factory() as session:
        upload = UploadJob(relative_path="media/m.mkv", source_path="/x/media/m.mkv", status="done", title="M")
        upload.targets = [UploadTarget(tracker_id=tracker_id, status="done", action="upload")]
        session.add(upload)
        session.commit()

    preview = client.get(f"/api/trackers/{tracker_id}/delete-preview")

    assert preview.status_code == 200
    assert preview.json() == {
        "candidates": 1, "reviews": 1, "executions": 1, "executions_seeding": 1, "match_attempts": 1,
        "upload_targets": 1, "upload_profile": False, "busy": False,
    }
    assert _count(client, SeedJob) == 1  # in sola lettura
    assert client.get("/api/trackers/999/delete-preview").status_code == 404


def test_the_tracker_preview_says_when_the_delete_would_be_refused(client):
    _disk_id, tracker_id = _used_tracker_and_disk(client)
    with client.app.state.session_factory() as session:
        session.query(SeedJob).one().final_status = "in_progress"
        session.commit()

    assert client.get(f"/api/trackers/{tracker_id}/delete-preview").json()["busy"] is True
    assert client.delete(f"/api/trackers/{tracker_id}").status_code == 409


def test_the_disk_preview_counts_what_goes_with_it(client):
    disk_id, _tracker_id = _used_tracker_and_disk(client)

    body = client.get(f"/api/disks/{disk_id}/delete-preview").json()

    assert body == {
        "folders": 0, "media_files": 1, "seed_files": 1, "reviews": 1, "executions": 1, "match_attempts": 1,
        "watch_entries": 0, "client_links": 0, "upload_jobs": 0, "busy": None,
    }
    assert client.get("/api/disks/999/delete-preview").status_code == 404
    with client.app.state.session_factory() as session:
        session.query(SeedJob).one().final_status = "in_progress"
        session.commit()
    assert client.get(f"/api/disks/{disk_id}/delete-preview").json()["busy"] == "reseed"
