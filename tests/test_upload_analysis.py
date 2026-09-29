import json
import os
from datetime import UTC, datetime

import pytest

from app import torrent_create, upload_analysis, upload_jobs, upload_verify
from app.adapters.tracker.base import TorrentCandidate
from app.arr import ArrGrab
from app.models import ClientTorrent, ClientTorrentFile, RunLog, SeedFile, UploadJob
from app.upload_worker import UploadWorker
from tests.upload_helpers import InlineExecutor, make_client, make_disk, make_tracker, write_video

MB = 1024 * 1024


class _FakeTracker:
    def __init__(self, candidates=None, error=None, torrent_bytes=None):
        self.candidates = candidates or []
        self.error = error
        self.torrent_bytes = torrent_bytes
        self.downloads = []

    def search_by_tmdb(self, tmdb_id):
        if self.error:
            raise self.error
        return self.candidates

    def download_torrent(self, url):
        self.downloads.append(url)
        return self.torrent_bytes


def _candidate(name, size, tid="1"):
    return TorrentCandidate(
        torrent_id_remote=tid, info_hash=None, name=name, size_bytes=size, file_list=None,
        mediainfo_unique_id=None, download_link=f"https://t/download/{tid}.key",
    )


@pytest.fixture
def analyzing_job(db_session, tmp_path, monkeypatch):
    """Un film da 60 MB a match confermato, verso due tracker."""
    video = write_video(tmp_path / "Movie.Name.2024.1080p.WEB-DL.DDP5.1.H.264-GRP.mkv", 60 * MB)
    disk = make_disk(db_session, tmp_path)
    make_tracker(db_session, "a")
    make_tracker(db_session, "b")
    job = upload_jobs.create_job(db_session, disk, video.name)
    upload_jobs.transition(db_session, job, "identifying", "awaiting_match", kind="movie", content_type="movie")
    upload_jobs.confirm_match(
        db_session, job, content_type="movie", tmdb_id=603, kind="movie", seasons=[], episode=None,
        details=None, forced={},
    )
    monkeypatch.setattr(upload_analysis.mediainfo_util, "extract_full_text", lambda path: f"MEDIAINFO {path}")
    return job


def _run(db_session, tmp_path, job):
    factory = lambda: db_session.__class__(bind=db_session.get_bind())  # noqa: E731
    worker = UploadWorker(
        factory, str(tmp_path), light_executor=InlineExecutor(), heavy_executor=InlineExecutor(),
        verify_executor=InlineExecutor(),
    )
    worker.kick(job.id, job.status)
    db_session.refresh(job)
    for target in job.targets:
        db_session.refresh(target)
    return worker


def test_analysis_checks_every_tracker_and_stops_at_the_decision(db_session, tmp_path, monkeypatch, analyzing_job):
    trackers = {
        "a": _FakeTracker([_candidate("Movie.Name.2024.1080p.WEB-DL.DDP5.1.H.264-OTHER", 59 * MB)]),
        "b": _FakeTracker(error=RuntimeError("503")),
    }
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter", lambda t: trackers[t.label])

    _run(db_session, tmp_path, analyzing_job)

    job = analyzing_job
    assert job.status == "awaiting_decision"
    assert job.mediainfo_text.startswith("MEDIAINFO ")
    a, b = job.targets
    assert (a.status, a.suggested_action) == ("awaiting_decision", "skip")
    assert json.loads(a.dupes_json)[0]["verdict"] == "same_slot"
    assert (b.status, b.suggested_action, b.error_message) == ("awaiting_decision", None, "dupe_check_failed")
    codes = [e.code for e in job.events]
    assert "dupe_check_failed" in codes and codes[-1] == "analysis_done"


def test_analysis_finds_the_source_already_seeding(db_session, tmp_path, monkeypatch, analyzing_job):
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter", lambda t: _FakeTracker())
    video = analyzing_job.source_path
    st = os.stat(video)
    run = RunLog(run_type="manual", started_at=datetime.now(UTC))
    client = make_client(db_session, "qbit")
    db_session.add(run)
    db_session.commit()
    sf = SeedFile(disk_id=analyzing_job.disk_id, relative_path="torrents/x.mkv", size_bytes=st.st_size,
                  st_dev=st.st_dev, inode=st.st_ino, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    seeding = ClientTorrent(torrent_client_id=client.id, info_hash="aa", name="Seeding", save_path="/t",
                            state="uploading", tracker_url="https://tracker.one/announce/k",
                            last_polled_at=datetime.now(UTC))
    lookalike = ClientTorrent(torrent_client_id=client.id, info_hash="bb", name="Lookalike", save_path="/t",
                              state="uploading", last_polled_at=datetime.now(UTC))
    db_session.add_all([sf, seeding, lookalike])
    db_session.commit()
    db_session.add_all([
        ClientTorrentFile(client_torrent_id=seeding.id, path_in_torrent="x.mkv", size_bytes=st.st_size,
                          seed_file_id=sf.id, last_scan_id=run.id),
        ClientTorrentFile(client_torrent_id=lookalike.id, path_in_torrent="y.mkv", size_bytes=st.st_size,
                          last_scan_id=run.id),
    ])
    db_session.commit()
    grab = ArrGrab(tracker_host="tracker.one", torrent_id_remote="77", download_url="u", info_hash="aa",
                   indexer="One")

    class _Index:
        def grab_for(self, path, size):
            return grab

    monkeypatch.setattr(upload_analysis, "arr_index_if_configured", lambda session: _Index())

    _run(db_session, tmp_path, analyzing_job)

    analysis = json.loads(analyzing_job.analysis_json)
    assert [(m["name"], m["match"], m["tracker_host"]) for m in analysis["client_matches"]] == [
        ("Seeding", "hardlink", "tracker.one"), ("Lookalike", "same_size", None),
    ]
    assert analysis["arr_grabs"] == [
        {"tracker_host": "tracker.one", "torrent_id_remote": "77", "info_hash": "aa", "indexer": "One"}
    ]
    levels = {e.code: e.level for e in analyzing_job.events}
    assert levels["already_on_client"] == "warning" and levels["grabbed_from_tracker"] == "warning"


def test_full_hash_check_turns_an_identical_release_into_a_reseed(db_session, tmp_path, monkeypatch, analyzing_job):
    source = analyzing_job.source_path
    torrent_path, _ = torrent_create.create_torrent(source, "https://a.example/announce", str(tmp_path / "t.torrent"))
    with open(torrent_path, "rb") as f:
        torrent_bytes = f.read()
    same = _FakeTracker([_candidate("Movie.Name.2024.1080p.WEB-DL-GRP", os.path.getsize(source), "42")],
                        torrent_bytes=torrent_bytes)
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter", lambda t: same)
    monkeypatch.setattr(upload_verify.adapter_factory, "build_tracker_adapter", lambda t: same)
    worker = _run(db_session, tmp_path, analyzing_job)
    target = analyzing_job.targets[0]
    assert target.suggested_action == "reseed"  # stessi byte: suggerito, ma non ancora verificato

    upload_verify.start(db_session, analyzing_job, target, "42", worker)

    db_session.refresh(target)
    verification = json.loads(target.dupes_json)[0]["verification"]
    assert verification["status"] == "passed"
    assert verification["ok"] == verification["pieces"] > 0
    assert (target.status, target.reseed_torrent_id) == ("awaiting_decision", "42")
    assert same.downloads == ["https://t/download/42.key"]


def test_full_hash_check_fails_on_different_bytes(db_session, tmp_path, monkeypatch, analyzing_job):
    other = write_video(tmp_path / "other" / "Movie.Name.2024.1080p.WEB-DL.DDP5.1.H.264-GRP.mkv", 60 * MB)
    with open(other, "r+b") as f:
        f.write(b"y" * 1000)
    torrent_path, _ = torrent_create.create_torrent(
        str(other), "https://a.example/announce", str(tmp_path / "t.torrent")
    )
    with open(torrent_path, "rb") as f:
        tracker = _FakeTracker([_candidate("x", 60 * MB, "9")], torrent_bytes=f.read())
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter", lambda t: tracker)
    monkeypatch.setattr(upload_verify.adapter_factory, "build_tracker_adapter", lambda t: tracker)
    worker = _run(db_session, tmp_path, analyzing_job)
    target = analyzing_job.targets[0]

    upload_verify.start(db_session, analyzing_job, target, "9", worker)

    db_session.refresh(target)
    verification = json.loads(target.dupes_json)[0]["verification"]
    assert verification["status"] == "failed" and verification["mismatched"] >= 1
    assert target.reseed_torrent_id is None
    assert analyzing_job.events[-1].code == "verify_failed"


def test_verify_requires_a_known_dupe(db_session, tmp_path, monkeypatch, analyzing_job):
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter", lambda t: _FakeTracker())
    worker = _run(db_session, tmp_path, analyzing_job)

    with pytest.raises(upload_jobs.UploadJobError) as exc:
        upload_verify.start(db_session, analyzing_job, analyzing_job.targets[0], "nope", worker)
    assert exc.value.code == "upload_dupe_not_found"


def test_interrupted_verification_goes_back_to_the_decision(db_session, tmp_path, monkeypatch, analyzing_job):
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter", lambda t: _FakeTracker())
    _run(db_session, tmp_path, analyzing_job)
    analyzing_job.targets[0].status = "verifying"
    db_session.commit()

    upload_jobs.reset_interrupted(db_session)

    db_session.refresh(analyzing_job.targets[0])
    assert analyzing_job.targets[0].status == "awaiting_decision"
    assert db_session.get(UploadJob, analyzing_job.id).events[-1].code == "verify_interrupted"
