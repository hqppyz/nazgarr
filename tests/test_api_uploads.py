import os

import pytest

from app import adapter_factory, settings_repo, upload_analysis, upload_identify
from app.adapters.media_resolver.base import ResolvedMedia
from app.api import metadata as metadata_api
from app.models import UploadJob
from app.poster_cache import poster_file
from app.upload_worker import UploadWorker
from tests.upload_helpers import (
    FakeTMDB,
    InlineExecutor,
    make_client,
    make_disk,
    make_tracker,
    tmdb_result,
    write_video,
)


class _FakeResolver:
    SOURCE = "filename_parser"

    def __init__(self, resolved=None):
        self.resolved = resolved
        self.calls = []

    def resolve(self, file_path):
        self.calls.append(file_path)
        return self.resolved


class _NoDupes:
    def search_by_tmdb(self, tmdb_id):
        return []


@pytest.fixture
def setup(client, tmp_path, monkeypatch):
    """Disco, un tracker con profilo e un worker che gira nel thread del test."""
    session = client.app.state.session_factory()
    disk = make_disk(session, tmp_path)
    tracker = make_tracker(session)
    # Il match automatico spento: questi test provano il punto di match.
    settings_repo.set_setting(session, upload_identify.AUTO_MATCH_SETTING, "0")
    ids = disk.id, tracker.id
    session.close()
    client.app.state.upload_worker = UploadWorker(
        client.app.state.session_factory, str(tmp_path / "data"),
        light_executor=InlineExecutor(), heavy_executor=InlineExecutor(),
    )
    resolver = _FakeResolver()
    monkeypatch.setattr(adapter_factory, "build_media_resolver", lambda session, arr_index=None: resolver)
    # Mai una chiamata vera verso un tracker o mediainfo sui file finti.
    monkeypatch.setattr(upload_analysis.adapter_factory, "build_tracker_adapter", lambda t: _NoDupes())
    monkeypatch.setattr(upload_analysis.mediainfo_util, "extract_full_text", lambda path: "MI")
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
    assert [(c["tmdb_id"], c["title"], c["source"]) for c in detail["candidates"]] == [
        (603, "Movie Name", "filename_parser")
    ]
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


def test_resolver_error_does_not_block_identification(client, tmp_path, setup):
    write_video(tmp_path / "Movie.2024.mkv")

    def boom(file_path):
        raise RuntimeError("tmdb down")

    setup["resolver"].resolve = boom
    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "Movie.2024.mkv"})

    assert resp.status_code == 201
    detail = client.get(f"/api/uploads/{resp.json()['id']}").json()
    assert detail["status"] == "awaiting_match"
    assert detail["candidates"] == []


def _awaiting_match(client, tmp_path, setup, relative_path, files):
    for f in files:
        write_video(tmp_path / f)
    job_id = client.post(
        "/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": relative_path,
                              "forced_ids": {"imdb": "tt0944947", "mal": 5}},
    ).json()["id"]
    assert client.get(f"/api/uploads/{job_id}").json()["status"] == "awaiting_match"
    return job_id


def test_confirm_match_stores_ids_and_moves_on(client, tmp_path, setup, monkeypatch):
    files = ["Show.S02/Show.S02E01.mkv", "Show.S02/Show.S02E02.mkv"]
    job_id = _awaiting_match(client, tmp_path, setup, "Show.S02", files)
    fake = FakeTMDB(details={("tv", 1399): {
        **tmdb_result(1399, "Game of Thrones", 2011, "tv", "/got.jpg"), "imdb_id": "tt-from-tmdb", "tvdb_id": 121361,
    }})
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)

    resp = client.post(f"/api/uploads/{job_id}/match", json={
        "content_type": "tv", "tmdb_id": 1399, "kind": "season_pack", "seasons": [2],
    })

    assert resp.status_code == 200, resp.text
    session = client.app.state.session_factory()
    try:
        job = session.get(UploadJob, job_id)
        assert (job.tmdb_id, job.imdb_id, job.tvdb_id, job.mal_id) == (1399, "tt0944947", 121361, 5)
        assert (job.title, job.year, job.poster_path, job.seasons_json) == ("Game of Thrones", 2011, "/got.jpg", "[2]")
        assert "match_confirmed" in [e.code for e in job.events]
        assert job.status == "awaiting_decision"
        assert [(t.status, t.suggested_action) for t in job.targets] == [("awaiting_decision", "upload")]
        assert job.mediainfo_text == "MI"
    finally:
        session.close()


@pytest.mark.parametrize(("body", "code"), [
    ({"content_type": "movie", "tmdb_id": 1, "kind": "season_pack", "seasons": [1]}, "upload_kind_mismatch"),
    ({"content_type": "tv", "tmdb_id": 1, "kind": "season_pack", "seasons": []}, "upload_season_required"),
    ({"content_type": "tv", "tmdb_id": 1, "kind": "season_pack", "seasons": [1, 2]}, "upload_single_season_required"),
    ({"content_type": "tv", "tmdb_id": 1, "kind": "episode", "seasons": [1]}, "upload_episode_required"),
])
def test_confirm_match_validates_kind_and_seasons(client, tmp_path, setup, body, code):
    files = ["Show.S01/Show.S01E01.mkv", "Show.S01/Show.S01E02.mkv"]
    job_id = _awaiting_match(client, tmp_path, setup, "Show.S01", files)

    resp = client.post(f"/api/uploads/{job_id}/match", json=body)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == code


def test_packs_need_a_folder(client, tmp_path, setup):
    job_id = _awaiting_match(client, tmp_path, setup, "Show.S01E01.mkv", ["Show.S01E01.mkv"])

    resp = client.post(f"/api/uploads/{job_id}/match", json={
        "content_type": "tv", "tmdb_id": 1, "kind": "season_pack", "seasons": [1],
    })

    assert resp.json()["detail"]["code"] == "upload_pack_requires_folder"


def test_reidentify_with_forced_ids(client, tmp_path, setup, monkeypatch):
    job_id = _awaiting_match(client, tmp_path, setup, "Movie.2024.mkv", ["Movie.2024.mkv"])
    fake = FakeTMDB(details={("movie", 603): tmdb_result(603, "The Matrix", 1999)})
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)

    resp = client.post(f"/api/uploads/{job_id}/reidentify", json={"forced_ids": {"tmdb": "movie/603"}})

    assert resp.status_code == 200
    detail = client.get(f"/api/uploads/{job_id}").json()
    assert detail["status"] == "awaiting_match"
    assert detail["forced_ids"] == {"tmdb": "movie/603"}
    assert [c["tmdb_id"] for c in detail["candidates"]] == [603]


def test_metadata_search_details_and_poster(client, tmp_path, monkeypatch):
    fake = FakeTMDB(
        search={("movie", "Matrix", None): [tmdb_result(603, "The Matrix", 1999, poster_path="/m.jpg")]},
        details={("movie", 603): {**tmdb_result(603, "The Matrix", 1999, poster_path="/m.jpg"), "genres": ["SF"]}},
    )
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)
    downloads = []

    def fake_download(posters_dir, content_type, tmdb_id, poster_path):
        downloads.append(poster_path)
        path = poster_file(posters_dir, content_type, tmdb_id)
        os.makedirs(posters_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"jpg")
        return path

    monkeypatch.setattr(metadata_api, "download_poster", fake_download)

    assert [r["tmdb_id"] for r in client.get("/api/metadata/search?content_type=movie&query=Matrix").json()] == [603]
    assert client.get("/api/metadata/movie/603").json()["genres"] == ["SF"]
    assert client.get("/api/metadata/search?content_type=book&query=x").status_code == 400

    # Con il path dal candidato non serve chiedere i dettagli; un path che
    # non è un nome file TMDB viene ignorato.
    assert client.get("/api/metadata/posters/movie/603.jpg?path=/m.jpg").content == b"jpg"
    assert client.get("/api/metadata/posters/movie/603.jpg").status_code == 200  # dalla cache
    fake.details[("tv", 603)] = tmdb_result(603, "Other", 2000, "tv", poster_path=None)
    resp = client.get("/api/metadata/posters/tv/603.jpg?path=http://evil/x.jpg")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "poster_not_available"
    assert ("details", "tv", 603) in fake.calls
    assert downloads == ["/m.jpg"]


def test_metadata_without_tmdb_key(client):
    resp = client.get("/api/metadata/search?content_type=movie&query=x")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "tmdb_api_key_missing"


def test_upload_trackers_lists_only_trackers_with_a_profile_and_their_client(client):
    session = client.app.state.session_factory()
    try:
        qbit_id = make_client(session, "qbit").id
        tracker_id = make_tracker(session, "with").id
        make_tracker(session, "without", with_profile=False)
    finally:
        session.close()

    assert client.get("/api/uploads/trackers").json() == [
        {"id": tracker_id, "label": "with", "torrent_client_id": qbit_id, "torrent_client_label": "qbit",
         "freeleech_options": [], "default_freeleech": None}
    ]


def test_verify_endpoint_rejects_unknown_target_or_dupe(client, tmp_path, setup):
    job_id = _awaiting_match(client, tmp_path, setup, "Movie.2024.mkv", ["Movie.2024.mkv"])
    client.post(f"/api/uploads/{job_id}/match", json={"content_type": "movie", "tmdb_id": 1, "kind": "movie"})
    target_id = client.get(f"/api/uploads/{job_id}").json()["targets"][0]["id"]

    resp = client.post(f"/api/uploads/{job_id}/targets/999/verify", json={"torrent_id_remote": "1"})
    assert resp.status_code == 404
    resp = client.post(f"/api/uploads/{job_id}/targets/{target_id}/verify", json={"torrent_id_remote": "1"})
    assert resp.json()["detail"]["code"] == "upload_dupe_not_found"


def test_overrides_and_approve_through_the_api(client, tmp_path, setup):
    job_id = _awaiting_match(client, tmp_path, setup, "Movie.Name.2024.1080p.WEB-DL.H.264-GRP.mkv",
                             ["Movie.Name.2024.1080p.WEB-DL.H.264-GRP.mkv"])
    client.post(f"/api/uploads/{job_id}/match", json={"content_type": "movie", "tmdb_id": 1, "kind": "movie"})

    detail = client.put(f"/api/uploads/{job_id}/overrides", json={"overrides": {"group": "ME"}}).json()
    target = detail["targets"][0]
    assert target["proposed_name"].endswith("-ME")
    assert target["type_id_map"] == {}

    resp = client.post(f"/api/uploads/{job_id}/approve", json={"targets": [
        {"target_id": target["id"], "action": "upload", "name": "Movie Name (2024)", "category_id": 1, "type_id": 4,
         "resolution_id": 3, "flags": {"anonymous": False}},
    ]})
    assert resp.status_code == 200, resp.text
    session = client.app.state.session_factory()
    try:
        job = session.get(UploadJob, job_id)
        assert "target_approved" in [e.code for e in job.events]
        assert job.targets[0].approved_name == "Movie Name (2024)"
    finally:
        session.close()


def test_targets_expose_the_freeleech_options_of_their_profile(client, tmp_path, setup):
    client.patch(f"/api/trackers/{setup['tracker_id']}/upload-profile", json={"freeleech_options": [50, 25]})
    job_id = _awaiting_match(client, tmp_path, setup, "Movie.2024.mkv", ["Movie.2024.mkv"])
    client.post(f"/api/uploads/{job_id}/match", json={"content_type": "movie", "tmdb_id": 1, "kind": "movie"})

    target = client.get(f"/api/uploads/{job_id}").json()["targets"][0]

    assert target["freeleech_options"] == [25, 50]
    assert target["flags"]["freeleech"] == 0


def test_the_file_naming_pattern_is_editable_and_previewed(client):
    current = client.get("/api/uploads/file-naming").json()
    assert current["rules"]["separator"] == "." and current["rules"] == current["default"]

    preview = client.post("/api/uploads/file-naming/preview", json={"rules": current["rules"]}).json()
    names = {e["key"]: e["name"] for e in preview["examples"]}
    assert names["uhd_remux"].startswith("Dune.Part.Two.2024.2160p.BluRay.REMUX.")
    assert names["uhd_remux"].endswith("-FraMeSToR.mkv") and ":" not in names["uhd_remux"]

    mine = {**current["rules"], "templates": {"default": "{title} {year} {group}"}}
    assert client.put("/api/uploads/file-naming", json={"rules": mine}).json()["rules"] == mine



def test_a_sure_match_confirms_itself_in_the_classic_flow_too(client, tmp_path, setup):
    session = client.app.state.session_factory()
    settings_repo.set_setting(session, upload_identify.AUTO_MATCH_SETTING, "0.9")
    session.close()
    video = write_video(tmp_path / "media" / "Movie.Name.2024.1080p.WEB.mkv")
    setup["resolver"].resolved = ResolvedMedia(tmdb_id=603, content_type="movie", title="Movie Name", year=2024)

    resp = client.post("/api/uploads", json={"disk_id": setup["disk_id"], "relative_path": "media/" + video.name})

    detail = client.get(f"/api/uploads/{resp.json()['id']}").json()
    assert detail["tmdb_id"] == 603 and detail["status"] != "awaiting_match"
    assert "auto_matched" in [e["code"] for e in detail["events"]]
