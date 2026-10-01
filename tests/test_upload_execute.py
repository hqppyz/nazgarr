import io
import json
import os
import types
from datetime import UTC, datetime

import pytest
import torf

from app import torrent_create, upload_decision, upload_execute, upload_jobs
from app.adapters.tracker.base import UploadedTorrent, UploadError
from app.models import Disk, TrackerUploadProfile
from app.upload_jobs import UploadJobError
from app.upload_worker import UploadWorker
from tests.upload_helpers import InlineExecutor, make_client, make_tracker, write_video

KB = 1024


class _Tracker:
    def __init__(self, torrent_id="100", error=None, torrent_bytes=None):
        self.torrent_id, self.error, self.torrent_bytes = torrent_id, error, torrent_bytes
        self.uploads = []
        self.changed_content = False

    def upload_torrent(self, fields, torrent_path):
        if self.error:
            raise self.error
        self.uploads.append((fields, torrent_path))
        return UploadedTorrent(self.torrent_id, f"https://tracker/torrent/download/{self.torrent_id}.key")

    def download_torrent(self, url):
        if url.startswith("https://tracker/torrent/download/"):
            # Come UNIT3D: riscrive il campo source, quindi un altro info hash.
            with open(self.uploads[-1][1], "rb") as f:
                torrent = torf.Torrent.read_stream(io.BytesIO(f.read()))
            torrent.source = f"Tracker{self.torrent_id}"
            if self.changed_content:
                torrent.metainfo["info"]["name"] = "Renamed by the tracker"
            return torrent.dump()
        return self.torrent_bytes


class _Client:
    def __init__(self):
        self.added = []
        self.skipped = []  # per ogni aggiunta: senza il recheck del client?
        self.rechecked = []
        self.save_paths = {}
        self.reported_path = None  # il percorso che il client dice di usare, se diverso
        self.labels = []  # (categoria, tag) di ogni aggiunta

    def add_torrent(self, torrent_file, save_path, force_recheck=True, skip_check_verified=False, **kwargs):
        assert force_recheck is True
        self.added.append((torrent_file, save_path))
        self.labels.append((kwargs.get("category"), kwargs.get("tags")))
        self.skipped.append(skip_check_verified)
        info_hash = torf.Torrent.read(torrent_file).infohash
        self.save_paths[info_hash] = save_path
        return info_hash

    def get_torrent_info(self, info_hash):
        return types.SimpleNamespace(save_path=self.reported_path or self.save_paths[info_hash])

    def recheck(self, info_hash):
        self.rechecked.append(info_hash)


class _Chain:
    def upload(self, path):
        return f"https://img.example/{os.path.basename(path)}"


@pytest.fixture
def env(db_session, tmp_path, monkeypatch):
    """Disco con libreria e cartella torrent, due tracker, un client, fake
    per tracker, client, screenshot e image host."""
    root = tmp_path / "disk"
    (root / "torrents").mkdir(parents=True)
    disk = Disk(label="d", root_path=str(root), media_rel_path="media", torrents_rel_path="torrents")
    db_session.add(disk)
    db_session.commit()
    client_row = make_client(db_session)
    trackers = {"a": _Tracker("100"), "b": _Tracker("200")}
    for label in trackers:
        tracker = make_tracker(db_session, label, torrent_client_id=client_row.id)
        profile = db_session.get(TrackerUploadProfile, tracker.id)
        profile.description_template = "{{ mediainfo }}{% for u in screenshot_urls %} [img]{{ u }}[/img]{% endfor %}"
    db_session.commit()
    client = _Client()
    monkeypatch.setattr(upload_execute.adapter_factory, "build_tracker_adapter", lambda t: trackers[t.label])
    monkeypatch.setattr(upload_execute.adapter_factory, "build_torrent_client_adapter", lambda row: client)
    monkeypatch.setattr(upload_execute.adapter_factory, "build_image_host_chain", lambda session: _Chain())

    def fake_screenshots(video, out_dir, count=4, tonemap=False):
        os.makedirs(out_dir, exist_ok=True)
        paths = [os.path.join(out_dir, f"{i}.png") for i in range(count)]
        for p in paths:
            open(p, "wb").close()
        return paths

    monkeypatch.setattr(upload_execute.screenshots, "generate_screenshots", fake_screenshots)
    return {"root": root, "disk": disk, "trackers": trackers, "client": client, "client_row": client_row}


def _approved(db_session, env, relative_path, decisions, file_naming="original", **job_values):
    job = upload_jobs.create_job(db_session, env["disk"], relative_path)
    # I test di prima dei nomi generati tengono i nomi della sorgente.
    if file_naming:
        job.overrides_json = json.dumps({"file_naming": file_naming})
    upload_jobs.transition(
        db_session, job, "identifying", "awaiting_decision", tmdb_id=603, imdb_id="tt0133093", title="The Matrix",
        year=1999, content_type=job_values.pop("content_type", "movie"), kind=job_values.pop("kind", "movie"),
        mediainfo_text="MI", **job_values,
    )
    for target in job.targets:
        target.status = "awaiting_decision"
    db_session.commit()
    upload_decision.approve(db_session, job, [
        {"target_id": t.id, **decisions[t.tracker.label]} for t in job.targets
    ])
    return job


def _upload(name, **extra):
    return {"action": "upload", "name": name, "category_id": 1, "type_id": 4, "resolution_id": 3,
            "flags": {"anonymous": True}, **extra}


def _run(db_session, tmp_path, job):
    factory = lambda: db_session.__class__(bind=db_session.get_bind())  # noqa: E731
    UploadWorker(
        factory, str(tmp_path / "data"), light_executor=InlineExecutor(), heavy_executor=InlineExecutor(),
        verify_executor=InlineExecutor(),
    ).kick(job.id, job.status)
    db_session.expire_all()
    return job


def test_uploads_to_every_tracker_and_seeds_from_hardlinks(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": _upload("Matrix B")})

    _run(db_session, tmp_path, job)

    assert job.status == "done"
    a, b = job.targets
    assert (a.status, a.torrent_id_remote, b.torrent_id_remote) == ("done", "100", "200")
    # Stessi piece, un .torrent per tracker: info hash diversi.
    ta, tb = torf.Torrent.read(a.torrent_path), torf.Torrent.read(b.torrent_path)
    assert ta.metainfo["info"]["pieces"] == tb.metainfo["info"]["pieces"]
    assert a.info_hash != b.info_hash
    fields, _ = env["trackers"]["a"].uploads[0]
    assert (fields.name, fields.imdb_id, fields.anonymous, fields.season_number) == ("Matrix A", "0133093", True, None)
    assert "https://img.example/0.png" in fields.description
    linked = env["root"] / "torrents" / video.name
    assert os.path.samefile(linked, video)
    assert env["client"].added == [(a.torrent_path, str(env["root"] / "torrents")),
                                   (b.torrent_path, str(env["root"] / "torrents"))]
    # Il torrent l'ha creato Nazgarr da quei file: niente recheck del client.
    assert env["client"].skipped == [True, True] and env["client"].rechecked == []
    # Nel client il .torrent del tracker (source riscritto), non quello inviato.
    seeded = torf.Torrent.read(a.torrent_path)
    assert seeded.source == "Tracker100" and a.info_hash == seeded.infohash
    assert seeded.infohash != torf.Torrent.read(env["trackers"]["a"].uploads[0][1]).infohash
    assert json.loads(job.screenshot_urls_json) == [f"https://img.example/{i}.png" for i in range(4)]


def test_a_source_inside_the_seeding_folder_seeds_in_place(db_session, tmp_path, env):
    folder = env["root"] / "torrents" / "Show.S01.1080p-GRP"
    for e in (1, 2):
        write_video(folder / f"Show.S01E0{e}.mkv", 200 * KB)
    write_video(folder / "Sample" / "sample.mkv", 10 * KB)
    job = _approved(db_session, env, "torrents/Show.S01.1080p-GRP", {"a": _upload("Show S01"), "b": {"action": "skip"}},
                    content_type="tv", kind="season_pack", seasons_json="[1]")

    _run(db_session, tmp_path, job)

    assert job.status == "done"
    torrent = torf.Torrent.read(job.targets[0].torrent_path)
    assert sorted(str(f) for f in torrent.files) == ["Show.S01.1080p-GRP/Show.S01E01.mkv",
                                                     "Show.S01.1080p-GRP/Show.S01E02.mkv"]
    assert env["client"].added == [(job.targets[0].torrent_path, str(env["root"] / "torrents"))]
    fields, _ = env["trackers"]["a"].uploads[0]
    assert (fields.season_number, fields.episode_number) == (1, 0)


def test_reseed_links_the_files_with_the_tracker_names(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "Matrix" / "matrix.mkv", 300 * KB)
    other = tmp_path / "tracker-layout" / "The.Matrix.1999.1080p-GRP"
    other.mkdir(parents=True)
    os.link(video, other / "The.Matrix.1999.1080p-GRP.mkv")
    torrent_path, _ = torrent_create.create_torrent(str(other), "https://a/announce", str(tmp_path / "t.torrent"))
    with open(torrent_path, "rb") as f:
        env["trackers"]["a"].torrent_bytes = f.read()
    job = upload_jobs.create_job(db_session, env["disk"], "media/Matrix")
    job.targets[0].dupes_json = json.dumps([{"torrent_id_remote": "7", "verdict": "identical",
                                             "download_link": "https://a/dl/7",
                                             "verification": {"status": "passed"}}])
    db_session.commit()
    upload_jobs.transition(db_session, job, "identifying", "awaiting_decision", tmdb_id=603, content_type="movie",
                           kind="movie")
    for target in job.targets:
        target.status = "awaiting_decision"
    db_session.commit()
    upload_decision.approve(db_session, job, [
        {"target_id": job.targets[0].id, "action": "reseed", "reseed_torrent_id": "7"},
        {"target_id": job.targets[1].id, "action": "skip"},
    ])

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    linked = env["root"] / "torrents" / "The.Matrix.1999.1080p-GRP" / "The.Matrix.1999.1080p-GRP.mkv"
    assert os.path.samefile(linked, video)
    assert env["client"].added == [(job.targets[0].torrent_path, str(env["root"] / "torrents"))]
    assert env["client"].skipped == [False]  # il .torrent è del tracker: recheck del client
    assert env["trackers"]["a"].uploads == []  # un reseed non pubblica niente


def test_an_upload_seen_elsewhere_by_the_client_is_rechecked(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})
    env["client"].reported_path = "/somewhere/else"

    _run(db_session, tmp_path, job)

    assert job.status == "done"
    assert env["client"].skipped == [True]
    assert env["client"].rechecked == [job.targets[0].info_hash]
    assert "recheck_after_path_mismatch" in [e.code for e in job.events]


def test_one_tracker_failing_leaves_the_others_going(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    env["trackers"]["a"].error = UploadError("rejected: dupe")
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": _upload("B")})

    _run(db_session, tmp_path, job)

    assert job.status == "partial"
    a, b = job.targets
    assert (a.status, a.error_message) == ("failed", "rejected: dupe")
    assert b.status == "done"
    assert "upload_failed" in [e.code for e in job.events]


def test_no_seed_and_existing_destination(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    write_video(env["root"] / "torrents" / "Movie.2024.mkv", 50 * KB)  # un altro file con lo stesso nome
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})

    _run(db_session, tmp_path, job)

    # Upload riuscito, seed no: mai ripetere l'upload per un problema del client.
    target = job.targets[0]
    assert (job.status, target.status, target.error_message) == ("done", "done", "seed_failed")
    assert env["client"].added == []

    job2 = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})
    job2.overrides_json = json.dumps({"no_seed": True})
    db_session.commit()
    _run(db_session, tmp_path, job2)
    assert "not_seeded" in [e.code for e in job2.events]


def test_screenshots_failing_blocks_uploads_but_not_reseeds(db_session, tmp_path, env, monkeypatch):
    def broken(*a, **k):
        raise upload_execute.screenshots.ScreenshotError("ffmpeg")

    monkeypatch.setattr(upload_execute.screenshots, "generate_screenshots", broken)
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": _upload("B")})

    _run(db_session, tmp_path, job)

    assert job.status == "failed"
    assert [t.error_message for t in job.targets] == ["upload_screenshots_failed"] * 2
    assert env["trackers"]["a"].uploads == []


def test_zero_screenshots_is_a_choice(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    job = upload_jobs.create_job(db_session, env["disk"], "media/" + video.name, overrides={"screenshot_count": 0})
    upload_jobs.transition(db_session, job, "identifying", "awaiting_decision", tmdb_id=1, content_type="movie",
                           kind="movie")
    for target in job.targets:
        target.status = "awaiting_decision"
    db_session.commit()
    upload_decision.approve(db_session, job, [{"target_id": t.id, **_upload(t.tracker.label)} for t in job.targets])

    _run(db_session, tmp_path, job)

    assert job.status == "done", [(e.code, e.params_json) for e in job.events]
    assert json.loads(job.screenshot_urls_json) == []


def test_files_in_place_needs_every_file_with_its_size(tmp_path):
    folder = tmp_path / "Show.S01"
    write_video(folder / "e1.mkv", 20 * KB)
    write_video(folder / "e2.mkv", 20 * KB)
    torrent = torf.Torrent(path=str(folder))

    assert upload_execute.files_in_place(torrent, str(tmp_path))
    (folder / "e2.mkv").write_bytes(b"short")
    assert not upload_execute.files_in_place(torrent, str(tmp_path))
    assert not upload_execute.files_in_place(torrent, str(tmp_path / "elsewhere"))


def test_a_torrent_changed_by_the_tracker_is_rechecked(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})
    env["trackers"]["a"].changed_content = True

    _run(db_session, tmp_path, job)

    assert job.status == "done"
    assert env["client"].skipped == [False]  # non più gli stessi file: recheck


def test_client_category_and_tags_follow_the_client_defaults_or_the_job(db_session, tmp_path, env):
    client = env["client_row"]
    client.category_movie, client.category_anime = "movie", "anime"
    client.tags_upload, client.tags_reseed = "release, nazgarr", "reseed"
    db_session.commit()
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    # "a" con i default del client; "b" con categoria e tag scelti nel job.
    job = _approved(db_session, env, "media/" + video.name, {
        "a": _upload("Matrix A"),
        "b": _upload("Matrix B", client_category="ebook", client_tags=""),
    })
    a, b = job.targets
    assert (a.client_category, a.client_tags) == ("movie", "release, nazgarr")
    assert (b.client_category, b.client_tags) == ("ebook", None)

    _run(db_session, tmp_path, job)

    assert env["client"].labels == [("movie", ["release", "nazgarr"]), ("ebook", None)]


def test_an_anime_takes_the_anime_category(db_session, env):
    from app import client_labels

    env["client_row"].category_tv, env["client_row"].category_anime = "tv", "anime"
    db_session.commit()
    write_video(env["root"] / "media" / "Show" / "e1.mkv", 20 * KB)
    job = upload_jobs.create_job(db_session, env["disk"], "media/Show")
    job.anime, job.content_type = True, "tv"
    db_session.commit()

    assert upload_decision.client_label_defaults(job, job.targets[0])["category"] == "anime"
    assert client_labels.is_anime({"genres": ["Animation", "Action"], "original_language": "ja"})
    assert not client_labels.is_anime({"genres": ["Animation"], "original_language": "en"})  # Pixar non è anime


def test_link_files_checks_everything_first_and_never_follows_symlinks(tmp_path):
    root = tmp_path / "torrents"
    root.mkdir()
    real = write_video(tmp_path / "media" / "a.mkv", 10 * KB)
    other = write_video(tmp_path / "media" / "b.mkv", 10 * KB)
    link = tmp_path / "media" / "link.mkv"
    link.symlink_to(real)

    with pytest.raises(UploadJobError) as exc:
        upload_execute.link_files([(str(real), str(root / "a.mkv")), (str(link), str(root / "l.mkv"))], str(root))
    assert exc.value.code == "upload_source_not_a_file"
    assert not (root / "a.mkv").exists()  # niente hardlink a metà

    with pytest.raises(Exception):
        upload_execute.link_files([(str(other), str(root / ".." / "escaped.mkv"))], str(root))
    assert not (tmp_path / "escaped.mkv").exists()


def test_a_library_file_is_uploaded_with_a_generated_release_name(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "The Matrix (1999) {imdb-tt0133093}.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    file_naming=None)  # il default: nessun hardlink, file della libreria -> generato

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    torrent = torf.Torrent.read(job.targets[0].torrent_path)
    assert torrent.name == "The.Matrix.1999.mkv"
    linked = env["root"] / "torrents" / "The.Matrix.1999.mkv"
    assert os.path.samefile(linked, video)  # in seed con quel nome, stessi byte
    assert env["client"].added == [(job.targets[0].torrent_path, str(env["root"] / "torrents"))]



def test_the_mediainfo_names_the_file_in_the_torrent_not_the_local_path(db_session, tmp_path, env, monkeypatch):
    # Rinominare cambia solo "Complete name"; il percorso locale non esce verso il tracker.
    monkeypatch.setattr("app.mediainfo_util.extract_full_text", lambda path: None)
    video = write_video(env["root"] / "media" / "The Matrix (1999) {imdb-tt0133093}.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    file_naming=None)
    job.mediainfo_text = f"General\nComplete name                            : {video}\nFormat : Matroska\n"
    db_session.commit()

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    assert "Complete name                            : The.Matrix.1999.mkv\n" in job.mediainfo_text
    assert str(env["root"]) not in job.mediainfo_text
    assert "Format : Matroska" in job.mediainfo_text


def test_the_names_of_the_hardlinked_torrent_win(db_session, tmp_path, env):
    from app.models import ClientTorrent, ClientTorrentFile, RunLog, SeedFile

    video = write_video(env["root"] / "media" / "Matrix (1999).mkv", 300 * KB)
    release = env["root"] / "torrents" / "The.Matrix.1999.1080p.BluRay.x264-GRP.mkv"
    os.link(video, release)
    run = RunLog(run_type="manual", started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    st = os.stat(release)
    seed = SeedFile(disk_id=env["disk"].id, relative_path=f"torrents/{release.name}", size_bytes=st.st_size,
                    st_dev=st.st_dev, inode=st.st_ino, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
    db_session.add(seed)
    db_session.commit()
    torrent_row = ClientTorrent(torrent_client_id=env["client_row"].id, info_hash="h", name=release.name,
                                save_path=str(release.parent), state="uploading", last_polled_at=datetime.now(UTC))
    db_session.add(torrent_row)
    db_session.commit()
    db_session.add(ClientTorrentFile(client_torrent_id=torrent_row.id, path_in_torrent=release.name,
                                     size_bytes=st.st_size, seed_file_id=seed.id, last_scan_id=run.id))
    db_session.commit()
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    file_naming=None)

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    assert torf.Torrent.read(job.targets[0].torrent_path).name == "The.Matrix.1999.1080p.BluRay.x264-GRP.mkv"


def test_renamed_links_are_removed_when_nothing_is_seeded(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "The Matrix (1999).mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    file_naming="generated")
    overrides = json.loads(job.overrides_json)
    job.overrides_json = json.dumps({**overrides, "no_seed": True})
    db_session.commit()

    _run(db_session, tmp_path, job)

    assert job.status == "done"
    assert not (env["root"] / "torrents" / "The.Matrix.1999.mkv").exists()
    assert video.exists()  # la libreria non si tocca
