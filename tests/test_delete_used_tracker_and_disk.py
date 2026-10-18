"""Cancellare un tracker o un disco già usati (audit 2026-10-18): prima un
tracker che aveva trovato anche un solo candidato, o un disco con un
reseed riuscito, non si cancellavano più (500, FOREIGN KEY constraint
failed). Ora quello che dipende da loro se ne va con loro, e lo storico
che resta perde solo il riferimento (docs/schema.sql)."""

from datetime import UTC, datetime

from nazgarr.core.models import (
    Candidate,
    CandidateFile,
    MatchAttempt,
    MatchReview,
    MediaFile,
    MediaItem,
    SeedFile,
    SeedJob,
)
from nazgarr.reseed import pipeline


def _used_tracker_and_disk(client):
    root = client.scan_root / "disk1"
    root.mkdir()
    disk_id = client.post("/api/disks", json={"label": "Disk 1", "root_path": str(root)}).json()["id"]
    tracker_id = client.post("/api/trackers", json={
        "label": "ITT", "adapter_type": "unit3d", "base_url": "https://itt.example", "api_token": "secret",
    }).json()["id"]
    session = client.app.state.session_factory()
    try:
        run = pipeline.start_run(session, "manual")
        now = datetime.now(UTC)
        item = MediaItem(content_type="movie", tmdb_id=603)
        session.add(item)
        session.flush()
        media = MediaFile(disk_id=disk_id, relative_path="media/m.mkv", size_bytes=1, st_dev=1, inode=1,
                          media_item_id=item.id, last_scan_id=run.id, last_seen_at=now)
        seed = SeedFile(disk_id=disk_id, relative_path="torrents/m.mkv", size_bytes=1, st_dev=1, inode=1,
                        last_scan_id=run.id, last_seen_at=now)
        session.add_all([media, seed])
        session.flush()
        candidate = Candidate(media_item_id=item.id, tracker_id=tracker_id, torrent_id_remote="1", name="m",
                              size_bytes=1, source="history", direction="media_to_torrent", confidence=1.0)
        session.add(candidate)
        session.flush()
        session.add_all([
            CandidateFile(candidate_id=candidate.id, torrent_path="m.mkv", is_video=True, media_file_id=media.id),
            MatchReview(candidate_id=candidate.id, media_file_id=media.id, status="approved"),
            MatchAttempt(tracker_id=tracker_id, media_file_id=media.id, size_bytes=1, tmdb_id=603, attempted_at=now),
            SeedJob(candidate_id=candidate.id, source_media_file_id=media.id, result_seed_file_id=seed.id,
                    info_hash="aa", final_status="seeding"),
        ])
        session.commit()
    finally:
        session.close()
    return disk_id, tracker_id


def _count(client, model) -> int:
    session = client.app.state.session_factory()
    try:
        return session.query(model).count()
    finally:
        session.close()


def test_a_tracker_that_found_candidates_can_be_deleted(client):
    _disk_id, tracker_id = _used_tracker_and_disk(client)

    assert client.delete(f"/api/trackers/{tracker_id}").status_code == 204

    assert client.get("/api/trackers").json() == []
    for model in (Candidate, CandidateFile, MatchReview, MatchAttempt, SeedJob):
        assert _count(client, model) == 0, model.__name__
    assert _count(client, MediaFile) == 1  # la libreria non c'entra


def test_a_disk_with_a_reseed_can_be_deleted(client):
    disk_id, _tracker_id = _used_tracker_and_disk(client)

    assert client.delete(f"/api/disks/{disk_id}").status_code == 204

    assert client.get("/api/disks").json() == []
    for model in (MediaFile, SeedFile, MatchReview, MatchAttempt, SeedJob):
        assert _count(client, model) == 0, model.__name__
    # Il candidato è del tracker: resta, senza più il file locale.
    session = client.app.state.session_factory()
    try:
        assert [f.media_file_id for f in session.query(CandidateFile)] == [None]
    finally:
        session.close()


def test_a_tracker_with_an_execution_or_an_upload_in_progress_is_not_deleted(client):
    """La cascata toglieva il seed_job su cui l'esecutore stava per
    scrivere: un hardlink o un torrent nel client senza traccia (audit 2026-10-18)."""
    from nazgarr.core.models import UploadJob, UploadTarget

    _disk_id, tracker_id = _used_tracker_and_disk(client)
    with client.app.state.session_factory() as session:
        job = session.query(SeedJob).one()
        job.final_status = "in_progress"
        session.commit()
    response = client.delete(f"/api/trackers/{tracker_id}")
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "tracker_busy", "params": {"label": "ITT"}}

    with client.app.state.session_factory() as session:
        session.query(SeedJob).one().final_status = "failed"
        upload = UploadJob(relative_path="media/m.mkv", source_path="/x/media/m.mkv", status="queued", title="M")
        upload.targets = [UploadTarget(tracker_id=tracker_id, status="approved", action="upload")]
        session.add(upload)
        session.commit()
        upload_id = upload.id
    assert client.delete(f"/api/trackers/{tracker_id}").json()["detail"]["code"] == "tracker_busy"

    with client.app.state.session_factory() as session:
        session.get(UploadJob, upload_id).status = "failed"
        session.commit()
    assert client.delete(f"/api/trackers/{tracker_id}").status_code == 204


def test_a_row_without_a_delete_action_gives_a_409(client):
    """Un DB con un riferimento senza ON DELETE (di prima della migrazione
    10): un 409 col suo codice, non un 500."""
    from sqlalchemy import text

    tracker_id = client.post("/api/trackers", json={
        "label": "Old", "adapter_type": "unit3d", "base_url": "https://old.example", "api_token": "secret",
    }).json()["id"]
    with client.app.state.session_factory() as session:
        session.execute(text("CREATE TABLE legacy_ref (tracker_id INTEGER REFERENCES tracker(id))"))
        session.execute(text("INSERT INTO legacy_ref VALUES (:id)"), {"id": tracker_id})
        session.commit()
    response = client.delete(f"/api/trackers/{tracker_id}")
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "tracker_in_use", "params": {"label": "Old"}}
    assert [t["label"] for t in client.get("/api/trackers").json()] == ["Old"]
