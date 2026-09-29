import json

import pytest

from app import adapter_factory
from app.adapters.media_resolver.base import ResolvedMedia
from app.models import UploadJob
from app.upload_worker import UploadWorker
from tests.upload_helpers import InlineExecutor, make_disk, make_tracker, write_video


class _FakeResolver:
    SOURCE = "filename_parser"

    def __init__(self, resolved=None):
        self.resolved = resolved
        self.calls = []

    def resolve(self, file_path):
        self.calls.append(file_path)
        return self.resolved


@pytest.fixture
def setup(client, tmp_path, monkeypatch):
    """Disco, un tracker con profilo e un worker che gira nel thread del test."""
    session = client.app.state.session_factory()
    disk = make_disk(session, tmp_path)
    tracker = make_tracker(session)
    ids = disk.id, tracker.id
    session.close()
    client.app.state.upload_worker = UploadWorker(
        client.app.state.session_factory, str(tmp_path / "data"),
        light_executor=InlineExecutor(), heavy_executor=InlineExecutor(),
    )
    resolver = _FakeResolver()
    monkeypatch.setattr(adapter_factory, "build_media_resolver", lambda session: resolver)
    return {"disk_id": ids[0], "tracker_id": ids[1], "resolver": resolver}


def test_create_movie_upload_identifies_and_stops_at_the_match_gate(client, tmp_path, setup):
    video = write_video(tmp_path / "media" / "Movie.Name.2024.1080p.WEB.mkv")
    setup["resolver"].resolved = ResolvedMedia(
        tmdb_id=603, content_type="movie", title="Movie Name", year=2024, poster_path="/p.jpg"
    )

    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "media/" + video.name})

    assert resp.status_code == 201, resp.text
    detail = client.get(f"/api/uploads/{resp.json()['id']}").json()
    assert detail["status"] == "awaiting_match"
    assert detail["kind"] == "movie"
    assert detail["candidates"] == [{
        "tmdb_id": 603, "content_type": "movie", "title": "Movie Name", "year": 2024, "poster_path": "/p.jpg",
        "imdb_id": None, "source": "filename_parser",
    }]
    assert setup["resolver"].calls == [str(video)]
    assert [t["tracker_id"] for t in detail["targets"]] == [setup["tracker_id"]]
    assert [e["code"] for e in detail["events"]] == ["job_created", "identify_started", "identify_done"]


def test_create_season_pack_folder(client, tmp_path, setup):
    for ep in (1, 2):
        write_video(tmp_path / "Show.S01.1080p-GRP" / f"Show.S01E0{ep}.1080p-GRP.mkv")

    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "Show.S01.1080p-GRP"})

    detail = client.get(f"/api/uploads/{resp.json()['id']}").json()
    assert detail["status"] == "awaiting_match"
    assert detail["is_dir"] is True
    assert detail["kind"] == "season_pack"
    assert detail["seasons"] == [1]
    assert detail["layout"]["episodes_by_season"] == {"1": [1, 2]}
    assert detail["candidates"] == []


def test_folder_without_videos_fails_with_a_coded_error(client, tmp_path, setup):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("x")

    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "docs"})

    detail = client.get(f"/api/uploads/{resp.json()['id']}").json()
    assert detail["status"] == "failed"
    assert detail["error_message"] == "no_video_files"


def test_create_rejects_path_outside_disk(client, setup):
    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "../../etc/passwd"})

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "path_outside_scope"


def test_create_rejects_missing_source_and_unknown_disk(client, setup):
    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "nope.mkv"})
    assert resp.json()["detail"]["code"] == "upload_source_not_found"

    resp = client.post("/api/uploads", json={"disk_id": 999, "relative_path": "x"})
    assert resp.status_code == 404


def test_cancel_list_and_delete(client, tmp_path, setup):
    write_video(tmp_path / "Movie.2024.mkv")
    job_id = client.post(
        "/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "Movie.2024.mkv"}
    ).json()["id"]

    listed = client.get("/api/uploads").json()
    assert [j["id"] for j in listed] == [job_id]
    assert listed[0]["targets"][0]["tracker_label"] == "t"

    assert client.post(f"/api/uploads/{job_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/uploads/{job_id}/cancel").status_code == 400
    assert client.delete(f"/api/uploads/{job_id}").status_code == 204
    assert client.get(f"/api/uploads/{job_id}").status_code == 404


def test_resolver_error_fails_the_job_but_not_the_request(client, tmp_path, setup):
    write_video(tmp_path / "Movie.2024.mkv")

    def boom(file_path):
        raise RuntimeError("tmdb down")

    setup["resolver"].resolve = boom
    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "Movie.2024.mkv"})

    assert resp.status_code == 201
    session = client.app.state.session_factory()
    try:
        job = session.get(UploadJob, resp.json()["id"])
        assert job.status == "failed"
        assert json.loads(job.events[-1].params_json)["error"] == "tmdb down"
    finally:
        session.close()
