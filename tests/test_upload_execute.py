import io
import json
import os
import types
from datetime import UTC, datetime

import httpx
import pytest
import torf

from nazgarr.adapters.tracker.base import UploadedTorrent, UploadError
from nazgarr.core.models import Disk, TrackerUploadProfile
from nazgarr.torrents import create as torrent_create
from nazgarr.torrents.metainfo import compute_info_hash
from nazgarr.upload import decision as upload_decision
from nazgarr.upload import execute as upload_execute
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload.jobs import UploadJobError
from nazgarr.upload.worker import UploadWorker
from tests.upload_helpers import InlineExecutor, make_client, make_tracker, write_video

KB = 1024


def _rejected(message="rejected: validation", status=422):
    """Come UNIT3D: il tracker risponde con un 4xx, l'errore di httpx come causa."""
    request = httpx.Request("POST", "https://tracker/api/torrents/upload")
    error = UploadError(message)
    error.__cause__ = httpx.HTTPStatusError(f"Client error '{status}'", request=request,
                                            response=httpx.Response(status, request=request))
    return error


def _unreachable(message="connection refused"):
    """Il tracker non risponde: la richiesta non è mai partita."""
    error = UploadError(message)
    error.__cause__ = httpx.ConnectError(message)
    return error


class _Tracker:
    def __init__(self, torrent_id="100", error=None, torrent_bytes=None):
        self.torrent_id, self.error, self.torrent_bytes = torrent_id, error, torrent_bytes
        self.uploads = []
        self.changed_content = False
        self.catalog = []  # quello che la ricerca trova (il dupe check prima di un upload programmato)

    def search_by_tmdb(self, tmdb_id):
        return self.catalog

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

    def start(self, info_hash):
        self.started = [*getattr(self, "started", []), info_hash]


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


def _approved(db_session, env, relative_path, decisions, file_naming="original", scheduled_at=None, **job_values):
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
    ], scheduled_at=scheduled_at)
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


def _reseed_job(db_session, tmp_path, env, verified_hash=None):
    """Un job col solo target "a" in reseed del torrent 7, già verificato
    (verified_hash: l'info hash letto dal controllo; di default quello del
    .torrent che il tracker restituisce)."""
    video = write_video(env["root"] / "media" / "Matrix" / "matrix.mkv", 300 * KB)
    other = tmp_path / "tracker-layout" / "The.Matrix.1999.1080p-GRP"
    other.mkdir(parents=True)
    os.link(video, other / "The.Matrix.1999.1080p-GRP.mkv")
    torrent_path, _ = torrent_create.create_torrent(str(other), "https://a/announce", str(tmp_path / "t.torrent"))
    with open(torrent_path, "rb") as f:
        env["trackers"]["a"].torrent_bytes = f.read()
    info_hash = verified_hash or compute_info_hash(env["trackers"]["a"].torrent_bytes)
    job = upload_jobs.create_job(db_session, env["disk"], "media/Matrix")
    job.targets[0].dupes_json = json.dumps([{"torrent_id_remote": "7", "verdict": "identical",
                                             "download_link": "https://a/dl/7",
                                             "verification": {"status": "passed", "info_hash": info_hash}}])
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
    return job, video


def test_reseed_links_the_files_with_the_tracker_names(db_session, tmp_path, env):
    job, video = _reseed_job(db_session, tmp_path, env)

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    linked = env["root"] / "torrents" / "The.Matrix.1999.1080p-GRP" / "The.Matrix.1999.1080p-GRP.mkv"
    assert os.path.samefile(linked, video)
    assert env["client"].added == [(job.targets[0].torrent_path, str(env["root"] / "torrents"))]
    assert env["client"].skipped == [False]  # il .torrent è del tracker: recheck del client
    assert env["trackers"]["a"].uploads == []  # un reseed non pubblica niente


def test_a_reseed_refuses_a_torrent_other_than_the_verified_one(db_session, tmp_path, env):
    # Il controllo completo ha letto un altro .torrent: quello riscaricato
    # non entra nel client, e niente hardlink.
    job, _video = _reseed_job(db_session, tmp_path, env, verified_hash="0" * 40)

    _run(db_session, tmp_path, job)

    target = job.targets[0]
    assert env["client"].added == []
    assert not (env["root"] / "torrents" / "The.Matrix.1999.1080p-GRP").exists()
    assert "upload_reseed_torrent_changed" in [e.code for e in job.events] + [target.error_message]


def test_a_client_that_cannot_skip_the_recheck_is_never_asked_to(db_session, tmp_path, env):
    # Transmission e rTorrent ricontrollano sempre: niente "verificato senza
    # recheck" nel registro, e nessun avviso di file fuori posto.
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})
    env["client"].can_skip_recheck = False

    _run(db_session, tmp_path, job)

    assert job.status == "done"
    assert env["client"].skipped == [False]
    codes = [e.code for e in job.events]
    assert "added_to_client" in codes
    assert "added_to_client_verified" not in codes and "recheck_files_not_in_place" not in codes


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
    env["trackers"]["a"].error = _rejected("rejected: dupe")
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
    from nazgarr.torrents import client_labels

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
    monkeypatch.setattr("nazgarr.library.mediainfo.extract_full_text", lambda path: None)
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
    from nazgarr.core.models import ClientTorrent, ClientTorrentFile, RunLog, SeedFile

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


def _watched_job(db_session, env, name, decisions, **overrides):
    env["disk"].watch_rel_path = "releases"
    db_session.commit()
    video = write_video(env["root"] / "releases" / name, 300 * KB)
    job = _approved(db_session, env, "releases/" + name, decisions)
    job.origin = "watch"
    if overrides:
        job.overrides_json = json.dumps({**json.loads(job.overrides_json or "{}"), **overrides})
    db_session.commit()
    return video


def test_a_release_leaves_the_watched_folder_once_it_seeds(db_session, tmp_path, env):
    # La cartella osservata è solo di passaggio: la release resta dove seeda.
    video = _watched_job(db_session, env, "My.Movie.2024.1080p.WEB-DL-NZG.mkv",
                         {"a": _upload("Movie A"), "b": {"action": "skip"}})
    job = db_session.query(upload_jobs.UploadJob).one()

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    assert not video.exists()
    seeding = env["root"] / "torrents" / "My.Movie.2024.1080p.WEB-DL-NZG.mkv"
    assert seeding.is_file() and seeding.stat().st_nlink == 1  # ora l'unica copia, in seed
    assert "watch_source_moved" in [e.code for e in job.events]


def test_a_watched_folder_inside_the_seeding_folder_still_moves_with_its_original_names(db_session, tmp_path, env):
    """Decisione dell'utente, 2026-10-05: con i nomi originali la release
    lascia comunque la cartella osservata (prima seedava sul posto, dentro
    torrents/watch, e restava lì); i nomi non si toccano."""
    env["disk"].watch_rel_path = "torrents/watch"
    db_session.commit()
    video = write_video(env["root"] / "torrents" / "watch" / "Original.Name.2024.mkv", 300 * KB)
    job = _approved(db_session, env, "torrents/watch/" + video.name, {"a": _upload("Movie A"), "b": {"action": "skip"}})
    job.origin = "watch"
    db_session.commit()

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    assert not video.exists()
    seeding = env["root"] / "torrents" / "Original.Name.2024.mkv"  # la cartella degli upload, stesso nome
    assert seeding.is_file() and seeding.stat().st_nlink == 1


def test_a_watched_file_linked_elsewhere_is_kept_unless_this_upload_seeds_its_copy(db_session, tmp_path, env):
    """Prima bastava un secondo link qualunque per cancellare il file della
    cartella osservata, anche se a seedare era proprio lui."""
    from nazgarr.upload import execute

    video = _watched_job(db_session, env, "Linked.2024.mkv", {"a": _upload("Movie A"), "b": {"action": "skip"}})
    (env["root"] / "downloads").mkdir()
    os.link(video, env["root"] / "downloads" / "Linked.2024.mkv")  # un altro link, non di questo job
    job = db_session.query(upload_jobs.UploadJob).one()
    job.targets[0].status = "done"
    db_session.commit()

    execute._clear_watch_source(db_session, job, {}, {"seeded": {}})
    assert video.is_file()
    copy = env["root"] / "torrents" / "Linked.2024.mkv"
    os.link(video, copy)
    st = video.stat()
    seeded = {job.targets[0].id: {(st.st_dev, st.st_ino): str(copy)}}
    execute._clear_watch_source(db_session, job, {}, {"seeded": seeded})
    assert not video.exists() and copy.is_file()


def _watch_upload_and_reseed(db_session, tmp_path, env, name="My.Movie.2024.1080p.WEB-DL-NZG.mkv", **overrides):
    """Dalla cartella osservata: upload su "a", reseed su "b" del torrent
    identico (stesso nome, quindi lo stesso hardlink nella cartella di seed
    di quello creato per l'upload), già verificato."""
    env["disk"].watch_rel_path = "releases"
    db_session.commit()
    video = write_video(env["root"] / "releases" / name, 300 * KB)
    torrent_path, _ = torrent_create.create_torrent(str(video), "https://b/announce", str(tmp_path / "b.torrent"))
    with open(torrent_path, "rb") as f:
        env["trackers"]["b"].torrent_bytes = f.read()
    info_hash = compute_info_hash(env["trackers"]["b"].torrent_bytes)
    job = upload_jobs.create_job(db_session, env["disk"], "releases/" + name)
    job.origin = "watch"
    job.overrides_json = json.dumps({"file_naming": "original", **overrides})
    b = next(t for t in job.targets if t.tracker.label == "b")
    b.dupes_json = json.dumps([{"torrent_id_remote": "9", "verdict": "identical", "download_link": "https://b/dl/9",
                                "verification": {"status": "passed", "info_hash": info_hash}}])
    db_session.commit()
    upload_jobs.transition(db_session, job, "identifying", "awaiting_decision", tmdb_id=603, title="My Movie",
                           year=2024, content_type="movie", kind="movie", mediainfo_text="MI")
    for target in job.targets:
        target.status = "awaiting_decision"
    db_session.commit()
    decisions = {"a": _upload("Movie A"), "b": {"action": "reseed", "reseed_torrent_id": "9"}}
    upload_decision.approve(db_session, job, [{"target_id": t.id, **decisions[t.tracker.label]} for t in job.targets])
    return job, video


@pytest.mark.parametrize("failure", ["tracker", "screenshots"])
def test_a_failed_upload_never_removes_the_links_a_reseed_of_the_same_job_seeds(
        db_session, tmp_path, env, monkeypatch, failure):
    """Audit 2026-10-18 (finding 1): l'upload su "a" fallisce, il reseed su
    "b" riusa l'hardlink creato per l'upload. Prima la pulizia toglieva quel
    link e poi la cartella osservata toglieva l'originale: nessuna copia
    della release restava, e il client di "b" seedava un torrent senza dati."""
    if failure == "tracker":
        env["trackers"]["a"].error = _rejected("rejected: validation")
    else:
        monkeypatch.setattr(upload_execute.screenshots, "generate_screenshots",
                            lambda *a, **k: (_ for _ in ()).throw(upload_execute.screenshots.ScreenshotError("ffmpeg")))
    job, video = _watch_upload_and_reseed(db_session, tmp_path, env)

    _run(db_session, tmp_path, job)

    assert job.status == "partial", [e.code for e in job.events]
    seeding = env["root"] / "torrents" / video.name
    assert env["client"].added == [(job.targets[1].torrent_path, str(env["root"] / "torrents"))]
    assert seeding.is_file()  # il reseed su "b" ha i suoi dati
    assert "file_links_removed" not in [e.code for e in job.events]
    if video.exists():
        assert os.path.samefile(video, seeding)


def test_with_no_seed_the_links_a_reseed_seeds_are_kept(db_session, tmp_path, env):
    job, video = _watch_upload_and_reseed(db_session, tmp_path, env, no_seed=True)

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    assert (env["root"] / "torrents" / video.name).is_file()  # quello che "b" seeda
    assert video.is_file()  # "non mettere in seed": la cartella osservata non si svuota


def test_the_watched_file_is_kept_when_its_recorded_copy_is_gone(db_session, tmp_path, env):
    """La copia in seed si ricontrolla subito prima di togliere l'originale:
    stesso inode, un file vero, in un altro percorso."""
    from nazgarr.upload import execute

    video = _watched_job(db_session, env, "Gone.2024.mkv", {"a": _upload("Movie A"), "b": {"action": "skip"}})
    job = db_session.query(upload_jobs.UploadJob).one()
    job.targets[0].status = "done"
    db_session.commit()
    copy = env["root"] / "torrents" / "Gone.2024.mkv"
    os.link(video, copy)
    st = video.stat()
    ctx = {"seeded": {job.targets[0].id: {(st.st_dev, st.st_ino): str(copy)}}}
    os.unlink(copy)  # tolto dopo che il job l'ha registrato

    execute._clear_watch_source(db_session, job, {}, ctx)

    assert video.is_file()


def test_a_release_stays_in_the_watched_folder_when_nothing_seeds(db_session, tmp_path, env):
    video = _watched_job(db_session, env, "My.Movie.2024.mkv", {"a": _upload("Movie A"), "b": {"action": "skip"}},
                         no_seed=True)
    job = db_session.query(upload_jobs.UploadJob).one()

    _run(db_session, tmp_path, job)

    assert video.is_file()


def test_an_upload_by_hand_never_removes_its_source(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "The.Matrix.1999.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})

    _run(db_session, tmp_path, job)

    assert job.status == "done" and video.is_file()


def test_a_release_folder_leaves_with_its_files_and_lists_what_the_torrent_did_not_take(db_session, tmp_path, env):
    # Una cartella con il film, un sample (fuori dal torrent) e un Thumbs.db.
    env["disk"].watch_rel_path = "releases"
    db_session.commit()
    folder = env["root"] / "releases" / "My Movie 2024"
    write_video(folder / "My.Movie.2024.1080p.WEB-DL-NZG.mkv", 300 * KB)
    write_video(folder / "Sample" / "sample.mkv", 10 * KB)
    (folder / "Thumbs.db").write_bytes(b"x")
    job = _approved(db_session, env, "releases/My Movie 2024", {"a": _upload("Movie A"), "b": {"action": "skip"}})
    job.origin = "watch"
    db_session.commit()

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    assert not (folder / "My.Movie.2024.1080p.WEB-DL-NZG.mkv").exists()
    assert not (folder / "Thumbs.db").exists()
    assert (folder / "Sample" / "sample.mkv").is_file()  # non era nel torrent: resta, e si dice
    leftovers = next(e for e in job.events if e.code == "watch_source_leftovers")
    assert json.loads(leftovers.params_json)["files"] == ["My Movie 2024/Sample/sample.mkv"]


def _single_file(db_session, choice):
    from nazgarr.core import settings_repo
    from nazgarr.upload import file_names as upload_file_names
    settings_repo.set_setting(db_session, upload_file_names.SINGLE_FILE_SETTING, "true")
    settings_repo.set_setting(db_session, upload_file_names.SINGLE_FILE_FOLDER_SETTING, choice)
    db_session.commit()


@pytest.mark.parametrize("choice", ["keep", "remove"])
def test_a_folder_with_one_file_becomes_a_single_file_torrent(db_session, tmp_path, env, choice):
    _single_file(db_session, choice)
    env["disk"].watch_rel_path = "releases"
    db_session.commit()
    folder = env["root"] / "releases" / "My Movie 2024"
    write_video(folder / "My.Movie.2024.1080p.WEB-DL-NZG.mkv", 300 * KB)
    write_video(folder / "Sample" / "sample.mkv", 10 * KB)  # mai nel torrent: non conta
    job = _approved(db_session, env, "releases/My Movie 2024", {"a": _upload("Movie A"), "b": {"action": "skip"}})
    job.origin = "watch"
    db_session.commit()

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    torrent = torf.Torrent.read(job.targets[0].torrent_path)
    assert torrent.mode == "singlefile" and torrent.name == "My.Movie.2024.1080p.WEB-DL-NZG.mkv"
    seeds_in = env["root"] / "torrents" / ("My Movie 2024" if choice == "keep" else "")
    assert (seeds_in / "My.Movie.2024.1080p.WEB-DL-NZG.mkv").is_file()
    assert env["client"].added == [(job.targets[0].torrent_path, str(seeds_in).rstrip(os.sep))]
    assert env["client"].skipped == [True]
    assert not (folder / "My.Movie.2024.1080p.WEB-DL-NZG.mkv").exists()  # spostato dalla cartella osservata


def test_a_single_file_already_in_the_seeding_folder_seeds_in_place(db_session, tmp_path, env):
    _single_file(db_session, "remove")
    video = write_video(env["root"] / "torrents" / "Movie.2024-GRP" / "Movie.2024-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "torrents/Movie.2024-GRP", {"a": _upload("Movie A"), "b": {"action": "skip"}})

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    assert torf.Torrent.read(job.targets[0].torrent_path).mode == "singlefile"
    assert env["client"].added == [(job.targets[0].torrent_path, str(video.parent))]
    assert video.stat().st_nlink == 1  # nessun hardlink nuovo


def test_a_folder_with_more_files_stays_a_folder(db_session, tmp_path, env):
    _single_file(db_session, "keep")
    folder = env["root"] / "media" / "Movie (2024)"
    write_video(folder / "Movie.mkv", 300 * KB)
    (folder / "Movie.nfo").write_text("nfo")
    job = _approved(db_session, env, "media/Movie (2024)", {"a": _upload("Movie A"), "b": {"action": "skip"}})

    _run(db_session, tmp_path, job)

    torrent = torf.Torrent.read(job.targets[0].torrent_path)
    assert torrent.mode == "multifile" and torrent.name == "Movie (2024)"


# --- pack di file scelti a mano (nazgarr/upload/pack.py) ----------------------


def _pack(db_session, env, files, kind, seasons, file_naming=None, **overrides):
    from dataclasses import asdict

    from nazgarr.upload import pack as upload_pack
    from nazgarr.upload.source import scan_source
    job = upload_pack.create_job(db_session, env["disk"], files)
    layout = scan_source(job.source_path, upload_pack.entries(job), upload_pack.name(job))
    assert (layout.kind, layout.seasons) == (kind, seasons)
    if file_naming or overrides:
        job.overrides_json = json.dumps({**({"file_naming": file_naming} if file_naming else {}), **overrides})
    upload_jobs.transition(
        db_session, job, "identifying", "awaiting_decision", tmdb_id=1399, title="Show", year=2020,
        content_type="tv", kind=kind, seasons_json=json.dumps(seasons), mediainfo_text="MI",
        layout_json=json.dumps(asdict(layout)),
    )
    for target in job.targets:
        target.status = "awaiting_decision"
    db_session.commit()
    return job


def _episodes(env, folder, season, count, size=200 * KB):
    """Gli episodi scaricati uno alla volta, ognuno nella cartella del suo torrent."""
    out = []
    for e in range(1, count + 1):
        name = f"Show.S{season:02d}E{e:02d}.1080p.WEB-DL-GRP"
        out.append(write_video(env["root"] / folder / name / f"{name}.mkv", size + e * KB))
    return out


def test_a_pack_of_episodes_already_seeding_becomes_one_season_torrent(db_session, tmp_path, env):
    episodes = _episodes(env, "torrents", 1, 3)
    (episodes[0].parent / "Show.S01E01.1080p.WEB-DL-GRP.it.srt").write_text("1")
    (episodes[0].parent / "other.nfo").write_text("x")  # non è un sottotitolo del video: resta fuori
    job = _pack(db_session, env, [str(p.relative_to(env["root"])) for p in episodes], "season_pack", [1],
                file_naming="original")
    from nazgarr.upload import pack as upload_pack
    assert upload_pack.name(job) == "Show.S01.1080p.WEB-DL-GRP"
    assert sorted(n for _p, n in upload_pack.entries(job))[0] == "Show.S01E01.1080p.WEB-DL-GRP.it.srt"
    upload_decision.approve(db_session, job, [
        {"target_id": t.id, **({"a": _upload("Show S01"), "b": {"action": "skip"}}[t.tracker.label])}
        for t in job.targets
    ])

    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    torrent = torf.Torrent.read(job.targets[0].torrent_path)
    assert sorted(str(f) for f in torrent.files) == [
        "Show.S01.1080p.WEB-DL-GRP/Show.S01E01.1080p.WEB-DL-GRP.it.srt",
        "Show.S01.1080p.WEB-DL-GRP/Show.S01E01.1080p.WEB-DL-GRP.mkv",
        "Show.S01.1080p.WEB-DL-GRP/Show.S01E02.1080p.WEB-DL-GRP.mkv",
        "Show.S01.1080p.WEB-DL-GRP/Show.S01E03.1080p.WEB-DL-GRP.mkv",
    ]
    pack = env["root"] / "torrents" / "Show.S01.1080p.WEB-DL-GRP"
    assert os.path.samefile(pack / "Show.S01E02.1080p.WEB-DL-GRP.mkv", episodes[1])
    assert episodes[1].is_file()  # i torrent degli episodi restano come sono
    assert env["client"].added == [(job.targets[0].torrent_path, str(env["root"] / "torrents"))]


def test_a_complete_pack_puts_each_season_in_its_folder(db_session, tmp_path, env):
    files = _episodes(env, "torrents", 1, 2) + _episodes(env, "torrents", 2, 2)
    job = _pack(db_session, env, [str(p.relative_to(env["root"])) for p in files], "complete_pack", [1, 2],
                file_naming="original")
    from nazgarr.upload import file_names as upload_file_names
    plan = upload_file_names.plan(db_session, job)
    assert plan.content_name == "Show.S01-S02.1080p.WEB-DL-GRP"
    assert sorted(target for _s, target in plan.files) == [
        "Show.S01-S02.1080p.WEB-DL-GRP/Season 01/Show.S01E01.1080p.WEB-DL-GRP.mkv",
        "Show.S01-S02.1080p.WEB-DL-GRP/Season 01/Show.S01E02.1080p.WEB-DL-GRP.mkv",
        "Show.S01-S02.1080p.WEB-DL-GRP/Season 02/Show.S02E01.1080p.WEB-DL-GRP.mkv",
        "Show.S01-S02.1080p.WEB-DL-GRP/Season 02/Show.S02E02.1080p.WEB-DL-GRP.mkv",
    ]
    # Rinominati: ogni episodio col suo nome, sempre nella sua stagione.
    generated = upload_file_names.plan(db_session, job, "generated")
    assert all("/Season 0" in target for _s, target in generated.files)


def test_a_mixed_pack_waits_for_a_confirmation(db_session, tmp_path, env):
    files = _episodes(env, "torrents", 1, 2)
    job = _pack(db_session, env, [str(p.relative_to(env["root"])) for p in files], "season_pack", [1])
    job.analysis_json = json.dumps({"pack_mixed": {"group": ["GRP", "OTHER"]}})
    db_session.commit()
    decisions = [{"target_id": t.id, **_upload("Show S01")} for t in job.targets]

    with pytest.raises(UploadJobError) as exc:
        upload_decision.approve(db_session, job, decisions)
    assert exc.value.code == "upload_pack_mixed_unconfirmed"

    upload_decision.update_overrides(db_session, job, {"pack_mixed_confirmed": True})
    db_session.refresh(job)
    job.analysis_json = json.dumps({**json.loads(job.analysis_json), "pack_mixed": {"group": ["GRP", "OTHER"]}})
    for target in job.targets:
        target.status = "awaiting_decision"
    db_session.commit()
    upload_decision.approve(db_session, job, decisions)
    assert job.status == "queued"


def test_a_pack_checks_every_file(db_session, tmp_path, env):
    from nazgarr.upload import pack as upload_pack
    a, b = _episodes(env, "torrents", 1, 2)
    rel = lambda p: str(p.relative_to(env["root"]))  # noqa: E731
    with pytest.raises(UploadJobError, match="upload_pack_too_few_files"):
        upload_pack.create_job(db_session, env["disk"], [rel(a)])
    nfo = env["root"] / "torrents" / "x.nfo"
    nfo.write_text("x")
    with pytest.raises(UploadJobError, match="upload_pack_not_a_video"):
        upload_pack.create_job(db_session, env["disk"], [rel(a), rel(nfo)])
    twin = write_video(env["root"] / "media" / a.name)
    with pytest.raises(UploadJobError, match="upload_pack_duplicate_name"):
        upload_pack.create_job(db_session, env["disk"], [rel(a), rel(b), rel(twin)])
    os.symlink(b, env["root"] / "torrents" / "link.mkv")
    with pytest.raises(UploadJobError, match="upload_source_has_symlinks"):
        upload_pack.create_job(db_session, env["disk"], [rel(a), "torrents/link.mkv"])
    from nazgarr.core.fs_scope import ScopeViolation
    with pytest.raises(ScopeViolation):
        upload_pack.create_job(db_session, env["disk"], [rel(a), "../outside.mkv"])


def test_an_episode_seeding_alone_does_not_mark_the_pack_as_seeding():
    from nazgarr.upload.analysis import seeding_here
    target = types.SimpleNamespace(
        tracker=types.SimpleNamespace(announce_url="https://t.example/announce", base_url=None), torrent_client_id=1,
    )
    one = {"match": "hardlink", "client_id": 1, "tracker_host": "t.example", "videos_matched": 1,
           "videos_hardlinked": 1, "videos_total": 3}
    assert seeding_here(target, [one]) is None
    assert seeding_here(target, [{**one, "videos_matched": 3, "videos_hardlinked": 3}]) is not None


def test_the_season_name_of_an_episode():
    from nazgarr.upload.pack import season_name
    assert season_name("Show.S01E01.1080p.WEB-DL-GRP.mkv", [1]) == "Show.S01.1080p.WEB-DL-GRP"
    assert season_name("Show.S01E01E02.1080p-GRP", [1]) == "Show.S01.1080p-GRP"
    assert (season_name("Show (2020) - S02E05 - Title [WEBDL-1080p]", [1, 3])
            == "Show (2020) - S01-S03 - Title [WEBDL-1080p]")
    assert season_name("Show.Season.Pack", [1]) == "Show.Season.Pack"


def test_seeding_can_be_retried_without_uploading_again(db_session, tmp_path, env, monkeypatch):
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})
    client = env["client"]
    real_add = client.add_torrent

    def broken(*args, **kwargs):
        raise RuntimeError("No such file or directory")

    monkeypatch.setattr(client, "add_torrent", broken)
    _run(db_session, tmp_path, job)
    target = job.targets[0]
    assert (target.status, target.error_message) == ("done", "seed_failed")
    uploads = len(env["trackers"]["a"].uploads)

    # Fallisce ancora: resta seed_failed, con il motivo.
    with pytest.raises(UploadJobError) as failed:
        upload_execute.retry_seed(db_session, job, target)
    assert failed.value.code == "upload_seed_retry_failed" and target.error_message == "seed_failed"

    monkeypatch.setattr(client, "add_torrent", real_add)
    upload_execute.retry_seed(db_session, job, target)

    assert target.error_message is None
    assert client.added == [(target.torrent_path, str(env["root"] / "torrents"))]
    assert client.skipped == [False]  # un nuovo tentativo ha sempre il recheck del client
    assert len(env["trackers"]["a"].uploads) == uploads  # nessun nuovo upload
    assert "seed_retried" in [e.code for e in job.events]
    with pytest.raises(UploadJobError) as again:
        upload_execute.retry_seed(db_session, job, target)
    assert again.value.code == "upload_seed_retry_unavailable"


def test_seeding_is_not_retried_when_the_files_are_gone(db_session, tmp_path, env, monkeypatch):
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})
    monkeypatch.setattr(env["client"], "add_torrent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    _run(db_session, tmp_path, job)
    target = job.targets[0]
    os.unlink(env["root"] / "torrents" / video.name)
    os.unlink(video)

    with pytest.raises(UploadJobError) as missing:
        upload_execute.retry_seed(db_session, job, target)
    assert missing.value.code == "upload_seed_files_missing"


def test_a_scheduled_upload_waits_for_its_time(db_session, tmp_path, env):
    from datetime import timedelta

    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    later = datetime.now(UTC) + timedelta(hours=3)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    scheduled_at=later)
    assert (job.status, upload_jobs.as_utc(job.scheduled_at)) == ("queued", later)
    assert any(e.code == "job_scheduled" for e in job.events)

    _run(db_session, tmp_path, job)
    assert job.status == "queued" and env["trackers"]["a"].uploads == []  # non è ancora ora

    job.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    _run(db_session, tmp_path, job)
    assert job.status == "done" and len(env["trackers"]["a"].uploads) == 1


def test_a_time_already_gone_means_now_and_the_time_can_change(db_session, tmp_path, env):
    from datetime import timedelta

    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    scheduled_at=datetime.now(UTC) - timedelta(minutes=5))
    assert job.scheduled_at is None

    upload_jobs.schedule(db_session, job, datetime.now(UTC) + timedelta(days=1))
    assert job.scheduled_at is not None
    upload_jobs.schedule(db_session, job, None)  # "Avvia ora"
    assert job.scheduled_at is None and job.events[-1].code == "job_start_now"


def test_a_dupe_that_appeared_after_the_decision_stops_that_tracker(db_session, tmp_path, env):
    from datetime import timedelta

    from nazgarr.adapters.tracker.base import TorrentCandidate

    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": _upload("Matrix B")},
                    scheduled_at=datetime.now(UTC) + timedelta(hours=1))
    # Su "a" nel frattempo qualcuno l'ha caricata; su "b" c'è solo quello che c'era alla decisione.
    same = TorrentCandidate(torrent_id_remote="77", info_hash=None, name="The.Matrix.1999.1080p.WEB-DL.H.264-OTHER",
                            size_bytes=300 * KB, file_list=None, mediainfo_unique_id=None)
    env["trackers"]["a"].catalog = [same]
    env["trackers"]["b"].catalog = [same]
    b = next(t for t in job.targets if t.tracker.label == "b")
    b.dupes_json = json.dumps([{"torrent_id_remote": "77", "verdict": "identical"}])
    job.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    _run(db_session, tmp_path, job)

    a = next(t for t in job.targets if t.tracker.label == "a")
    assert (a.status, a.error_message) == ("failed", "upload_dupe_appeared")
    assert env["trackers"]["a"].uploads == [] and len(env["trackers"]["b"].uploads) == 1
    assert job.status == "partial"


# --- errori a metà esecuzione (audit 2026-10-18) -------------------------------


def test_an_unexpected_error_while_preparing_fails_the_uploads_with_it(db_session, tmp_path, env, monkeypatch, caplog):
    """Un errore che non è nostro (qui torf che non legge il disco) faceva
    finire il job con "passo non disponibile", senza log, e lasciava gli
    hardlink dei nomi nuovi nella cartella di seed."""
    import logging

    video = write_video(env["root"] / "media" / "The Matrix (1999).mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    file_naming="generated")
    monkeypatch.setattr(torf.Torrent, "generate", lambda self, **k: (_ for _ in ()).throw(OSError(5, "I/O error")))

    with caplog.at_level(logging.ERROR, logger=upload_execute.logger.name):
        _run(db_session, tmp_path, job)

    a = job.targets[0]
    assert (job.status, a.status, a.error_message) == ("failed", "failed", "upload_prepare_failed")
    event = next(e for e in job.events if e.code == "upload_prepare_failed")
    assert "I/O error" in json.loads(event.params_json)["error"]
    assert "preparazione fallita" in caplog.text
    assert not (env["root"] / "torrents" / "The.Matrix.1999.mkv").exists()


def test_a_cancel_while_hashing_removes_the_links_made_for_the_names(db_session, tmp_path, env, monkeypatch):
    video = write_video(env["root"] / "media" / "The Matrix (1999).mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    file_naming="generated")

    def cancel_midway(self, callback=None, **kwargs):
        other = db_session.__class__(bind=db_session.get_bind())
        upload_jobs.cancel_job(other, other.get(upload_jobs.UploadJob, job.id))
        other.close()
        return callback(self, "", 1, 2)

    monkeypatch.setattr(torf.Torrent, "generate", cancel_midway)
    _run(db_session, tmp_path, job)

    assert job.status == "cancelled"
    assert not (env["root"] / "torrents" / "The.Matrix.1999.mkv").exists()
    assert video.is_file()
    assert "file_links_removed" in [e.code for e in job.events]


def test_a_cleanup_error_never_changes_the_outcome(db_session, tmp_path, env, monkeypatch):
    video = _watched_job(db_session, env, "My.Movie.2024.mkv", {"a": _upload("Movie A"), "b": {"action": "skip"}})
    job = db_session.query(upload_jobs.UploadJob).one()
    monkeypatch.setattr(upload_execute, "_clear_watch_source",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")))

    _run(db_session, tmp_path, job)

    assert job.status == "done" and job.targets[0].torrent_id_remote == "100"
    assert video.is_file()
    assert "upload_cleanup_failed" in [e.code for e in job.events]


def test_a_leftover_that_cannot_be_removed_keeps_the_episode_folder_and_the_job_done(
        db_session, tmp_path, env, monkeypatch):
    from nazgarr.upload import execute

    env["disk"].watch_rel_path = "releases"
    db_session.commit()
    folder = env["root"] / "releases" / "Show.S01"
    episode = write_video(folder / "Show.S01E01.mkv", 300 * KB)
    (folder / "Show.nfo").write_text("nfo")
    write_video(folder / "Locked" / "notes.txt", 10)
    job = upload_jobs.create_job(db_session, env["disk"], "releases/Show.S01/Show.S01E01.mkv")
    job.split_from_id = job.id  # un episodio di una stagione divisa
    db_session.commit()
    os.chmod(folder / "Locked", 0o555)
    try:
        os.unlink(episode)  # l'episodio è già andato
        execute._remove_split_folder(db_session, job, str(env["root"] / "releases"))
    finally:
        os.chmod(folder / "Locked", 0o755)

    assert (folder / "Locked" / "notes.txt").is_file() and not (folder / "Show.nfo").exists()
    event = job.events[-1]
    assert event.code == "watch_folder_remove_failed" and event.level == "warning"
    assert json.loads(event.params_json)["files"] == ["Locked", "Locked/notes.txt"]


def test_a_published_upload_whose_record_cannot_be_written_is_never_marked_failed(
        db_session, tmp_path, env, monkeypatch):
    from sqlalchemy.exc import OperationalError

    video = write_video(env["root"] / "media" / "The.Matrix.1999.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})

    def locked(session, job, target, torrent_id_remote):
        raise OperationalError("COMMIT", None, Exception("database is locked"))

    monkeypatch.setattr(upload_execute, "_commit_published", locked)
    _run(db_session, tmp_path, job)

    a = job.targets[0]
    assert (a.status, a.error_message, a.torrent_id_remote) == ("done", "seed_failed", "100")
    assert len(env["trackers"]["a"].uploads) == 1 and env["client"].added == []
    journal = upload_jobs.published_journal(str(tmp_path / "data" / "uploads" / str(job.id)), a.id)
    assert json.load(open(journal)) == {"torrent_id_remote": "100"}


def test_the_published_id_is_written_again_after_a_locked_commit(monkeypatch):
    from sqlalchemy.exc import OperationalError

    class Flaky:
        def __init__(self, fails):
            self.fails, self.added, self.rollbacks = fails, [], 0

        def add(self, obj):
            self.added.append(obj)

        def commit(self):
            if self.fails:
                self.fails -= 1
                raise OperationalError("COMMIT", None, Exception("database is locked"))

        def rollback(self):
            self.rollbacks += 1

    monkeypatch.setattr(upload_execute.time, "sleep", lambda s: None)
    job, target = types.SimpleNamespace(id=1), types.SimpleNamespace(id=2, torrent_id_remote=None)
    session = Flaky(2)
    upload_execute._commit_published(session, job, target, "100")
    assert target.torrent_id_remote == "100" and session.rollbacks == 2 and len(session.added) == 3

    with pytest.raises(OperationalError):
        upload_execute._commit_published(Flaky(3), job, target, "100")


def test_a_database_error_on_one_tracker_is_recorded_with_its_message(db_session, tmp_path, env, monkeypatch):
    """Un errore di SQLAlchemy ha anche lui .code e .params: prima finiva
    registrato come "e3q8", e params.items() falliva sulla tupla della query."""
    from sqlalchemy.exc import OperationalError

    job, _video = _reseed_job(db_session, tmp_path, env)
    monkeypatch.setattr(upload_execute, "run_reseed", lambda *a: (_ for _ in ()).throw(
        OperationalError("INSERT INTO x", (1,), Exception("disk I/O error"))))

    _run(db_session, tmp_path, job)

    target = job.targets[0]
    assert job.status == "failed" and target.status == "failed"
    assert "disk I/O error" in target.error_message and target.error_message != "e3q8"
    assert "reseed_failed" in [e.code for e in job.events]


# --- l'aggiunta al client e il nuovo tentativo del seed (audit 2026-10-18) ------


def test_the_client_waits_for_this_exact_torrent_and_one_already_there_is_kept(
        db_session, tmp_path, env, monkeypatch):
    """Senza l'info hash atteso qBittorrent prendeva per il nostro un torrent
    qualunque comparso nel frattempo; con, un duplicato è un errore chiaro:
    qui il primo tentativo era arrivato nel client prima di fallire."""
    from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError

    video = write_video(env["root"] / "media" / "The.Matrix.1999.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})
    client = env["client"]
    real_add, expected = client.add_torrent, []

    def add(torrent_file, save_path, expected_info_hash=None, **kwargs):
        expected.append(expected_info_hash)
        if expected_info_hash in client.save_paths:
            raise TorrentAlreadyInClientError("already there")
        real_add(torrent_file, save_path, **kwargs)
        raise RuntimeError("timed out waiting for the torrent")  # arrivato, ma l'attesa è scaduta

    monkeypatch.setattr(client, "add_torrent", add)
    _run(db_session, tmp_path, job)
    target = job.targets[0]
    assert (target.status, target.error_message) == ("done", "seed_failed")
    with open(target.torrent_path, "rb") as f:
        assert expected == [compute_info_hash(f.read())]

    upload_execute.retry_seed(db_session, job, target)

    assert target.error_message is None and client.rechecked == [expected[0]] and client.started == [expected[0]]
    assert "already_in_client" in [e.code for e in job.events]


def test_a_torrent_already_in_the_client_elsewhere_is_not_taken(db_session, tmp_path, env, monkeypatch):
    from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError

    job, _video = _reseed_job(db_session, tmp_path, env)
    client = env["client"]

    def add(torrent_file, save_path, expected_info_hash=None, **kwargs):
        client.save_paths[expected_info_hash] = "/somewhere/else"
        raise TorrentAlreadyInClientError("already there")

    monkeypatch.setattr(client, "add_torrent", add)
    _run(db_session, tmp_path, job)

    target = job.targets[0]
    assert (target.status, target.error_message) == ("failed", "upload_already_in_client")
    assert client.rechecked == []


def test_a_retried_seed_relinks_into_the_seed_folder_never_the_library(db_session, tmp_path, env, monkeypatch):
    """Prima un nuovo tentativo, senza più l'hardlink nella cartella di seed,
    puntava il client direttamente alla cartella della libreria."""
    video = write_video(env["root"] / "media" / "The.Matrix.1999.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})
    client = env["client"]
    real_add = client.add_torrent
    monkeypatch.setattr(client, "add_torrent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    _run(db_session, tmp_path, job)
    target = job.targets[0]
    os.unlink(env["root"] / "torrents" / video.name)  # tolto come hardlink orfano
    monkeypatch.setattr(client, "add_torrent", real_add)

    upload_execute.retry_seed(db_session, job, target)

    assert client.added == [(target.torrent_path, str(env["root"] / "torrents"))]
    assert os.path.samefile(env["root"] / "torrents" / video.name, video)
    assert "seed_files_linked" in [e.code for e in job.events]


@pytest.mark.parametrize("tracker_can_give_it_back", [True, False])
def test_a_retried_seed_uses_the_trackers_own_torrent(db_session, tmp_path, env, tracker_can_give_it_back):
    """Il seed fallito prima di scaricare la copia del tracker: si riscarica
    (UNIT3D riscrive il campo source, l'info hash del nostro .torrent non è
    quello che conosce il tracker); solo se non si può, il nostro, e si dice."""
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    blocker = write_video(env["root"] / "torrents" / "Movie.2024.mkv", 50 * KB)  # un altro file con quel nome
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})
    _run(db_session, tmp_path, job)
    target = job.targets[0]
    assert target.error_message == "seed_failed"
    assert os.path.basename(target.torrent_path) == f"tracker-{target.tracker_id}.torrent"
    os.unlink(blocker)
    tracker = env["trackers"]["a"]
    if tracker_can_give_it_back:
        tracker.get_torrent_detail = lambda torrent_id: types.SimpleNamespace(
            download_link=f"https://tracker/torrent/download/{torrent_id}.key")

    upload_execute.retry_seed(db_session, job, target, str(tmp_path / "data"))

    added = torf.Torrent.read(env["client"].added[-1][0])
    codes = [e.code for e in job.events]
    if tracker_can_give_it_back:
        assert added.source == "Tracker100" and target.torrent_path.endswith("-seed.torrent")
        assert "seed_retry_own_torrent" not in codes
    else:
        assert added.source == "a" and "seed_retry_own_torrent" in codes


# --- quello che entra nel torrent (audit 2026-10-18) ---------------------------


def test_only_the_planned_files_enter_a_torrent_built_from_hardlinks(db_session, tmp_path, env, monkeypatch):
    """La cartella con il nome del torrent nella cartella di seed aveva già
    un file (un upload precedente, la promo di un altro tracker): finiva
    pubblicato e in seed senza che la decisione lo mostrasse."""
    from nazgarr.upload import file_names as upload_file_names

    folder = env["root"] / "media" / "The Matrix (1999)"
    write_video(folder / "The Matrix (1999).mkv", 300 * KB)
    (folder / "The Matrix (1999).nfo").write_text("nfo")
    job = _approved(db_session, env, "media/The Matrix (1999)", {"a": _upload("Matrix A"), "b": {"action": "skip"}},
                    file_naming="generated")
    name = upload_file_names.plan(db_session, job).content_name
    stale = env["root"] / "torrents" / name / "Other.Tracker.Promo.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("promo")
    threads = []
    real_generate = torf.Torrent.generate

    def generate(self, **kwargs):
        threads.append(kwargs.get("threads"))
        return real_generate(self, **kwargs)

    monkeypatch.setattr(torf.Torrent, "generate", generate)
    _run(db_session, tmp_path, job)

    assert job.status == "done", [e.code for e in job.events]
    files = sorted("/".join(f.parts) for f in torf.Torrent.read(job.targets[0].torrent_path).files)
    assert files and all(not f.endswith("Promo.txt") for f in files)
    event = next(e for e in job.events if e.code == "upload_extra_files_left_out")
    assert json.loads(event.params_json)["files"] == [f"{name}/Other.Tracker.Promo.txt"]
    assert stale.is_file()  # non è di questo job: resta dov'è
    assert threads and 1 <= threads[0] <= upload_execute.HASH_THREADS


def test_a_symlink_added_to_the_source_after_the_decision_stops_the_upload(db_session, tmp_path, env):
    """Il controllo dei link simbolici si faceva solo alla creazione del job;
    torf li segue, e il file a cui puntano finiva nel torrent pubblicato."""
    folder = env["root"] / "media" / "Movie (2024)"
    write_video(folder / "Movie.mkv", 300 * KB)
    (folder / "Movie.nfo").write_text("nfo")
    job = _approved(db_session, env, "media/Movie (2024)", {"a": _upload("Movie A"), "b": {"action": "skip"}})
    secret = tmp_path / "secret.key"
    secret.write_text("key")
    (folder / "extra.txt").symlink_to(secret)

    _run(db_session, tmp_path, job)

    target = job.targets[0]
    assert (target.status, target.error_message) == ("failed", "upload_source_has_symlinks")
    assert env["trackers"]["a"].uploads == []


# --- un nuovo tentativo dei tracker falliti (richiesta dell'utente, 2026-10-18) --


def _shots(monkeypatch):
    calls = []
    real = upload_execute.screenshots.generate_screenshots

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(upload_execute.screenshots, "generate_screenshots", counting)
    return calls


def test_a_failed_tracker_is_retried_with_its_decision_and_no_new_match(db_session, tmp_path, env, monkeypatch):
    shots = _shots(monkeypatch)
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    env["trackers"]["a"].error = _unreachable("All connection attempts failed")
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": _upload("Matrix B")})
    _run(db_session, tmp_path, job)
    a, b = job.targets
    assert (job.status, a.status, b.status) == ("partial", "failed", "done") and len(shots) == 1

    env["trackers"]["a"].error = None  # il tracker è tornato
    retried = upload_jobs.retry_failed(db_session, job)

    assert [t.id for t in retried] == [a.id]
    assert (job.status, job.finished_at, a.status, a.error_message) == ("queued", None, "approved", None)
    assert job.queue_position is not None and job.events[-1].code == "job_retried"
    assert json.loads(job.events[-1].params_json)["trackers"] == "a"

    _run(db_session, tmp_path, job)

    assert (job.status, a.status, a.torrent_id_remote) == ("done", "done", "100"), [e.code for e in job.events]
    assert env["trackers"]["a"].uploads[0][0].name == "Matrix A"  # la decisione di allora
    assert len(env["trackers"]["b"].uploads) == 1  # "b" non si ricarica
    assert len(shots) == 1  # gli screenshot già sull'image host
    assert "https://img.example/0.png" in env["trackers"]["a"].uploads[0][0].description


def test_a_retry_checks_the_dupes_again_before_sending(db_session, tmp_path, env):
    from nazgarr.adapters.tracker.base import TorrentCandidate

    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    env["trackers"]["a"].error = _unreachable("connect timeout")
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})
    _run(db_session, tmp_path, job)
    assert job.status == "failed"
    env["trackers"]["a"].error = None
    env["trackers"]["a"].catalog = [TorrentCandidate(
        torrent_id_remote="77", info_hash=None, name="The.Matrix.1999.1080p.WEB-DL.H.264-OTHER", size_bytes=300 * KB,
        file_list=None, mediainfo_unique_id=None)]

    upload_jobs.retry_failed(db_session, job)
    _run(db_session, tmp_path, job)

    a = job.targets[0]
    assert (job.status, a.status, a.error_message) == ("failed", "failed", "upload_dupe_appeared")
    assert env["trackers"]["a"].uploads == []


def test_an_interrupted_upload_is_retried_only_once_confirmed(db_session, tmp_path, env):
    """Non si sa se il tracker l'ha ricevuto: si riprova solo dopo una
    conferma, e il dupe check rifatto trova il nostro torrent se c'è."""
    from nazgarr.adapters.tracker.base import TorrentCandidate

    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})
    a = job.targets[0]
    a.status, a.error_message = "failed", "interrupted"
    upload_jobs.transition(db_session, job, "queued", "failed")

    with pytest.raises(UploadJobError) as exc:
        upload_jobs.retry_failed(db_session, job)
    assert (exc.value.code, exc.value.params) == ("upload_retry_needs_confirm", {"trackers": "a"})
    assert job.status == "failed" and a.status == "failed"

    # Era arrivato: il tracker lo elenca, e il nuovo tentativo si ferma lì.
    env["trackers"]["a"].catalog = [TorrentCandidate(
        torrent_id_remote="100", info_hash=None, name="Matrix A", size_bytes=300 * KB, file_list=None,
        mediainfo_unique_id=None)]
    upload_jobs.retry_failed(db_session, job, confirm_interrupted=True)
    assert json.loads(job.events[-1].params_json)["confirmed"] == "a"
    _run(db_session, tmp_path, job)

    assert (a.status, a.error_message) == ("failed", "upload_dupe_appeared")
    assert env["trackers"]["a"].uploads == []


def test_what_cannot_be_retried(db_session, tmp_path, env, monkeypatch):
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})

    def refused(code):
        with pytest.raises(UploadJobError) as exc:
            upload_jobs.retry_failed(db_session, job)
        assert exc.value.code == code

    refused("upload_job_wrong_status")  # in coda, non finito
    monkeypatch.setattr(env["client"], "add_torrent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    _run(db_session, tmp_path, job)
    assert (job.status, job.targets[0].error_message) == ("done", "seed_failed")
    refused("upload_job_wrong_status")  # pubblicato: si riprova il seed, non l'upload
    upload_jobs.transition(db_session, job, "done", "partial")
    refused("upload_retry_nothing")
    job.targets[0].status, job.targets[0].torrent_id_remote = "failed", None
    db_session.commit()
    os.unlink(video)
    refused("upload_source_missing")


def test_a_watched_release_that_failed_everywhere_stays_and_leaves_after_a_retry(db_session, tmp_path, env):
    video = _watched_job(db_session, env, "My.Movie.2024.mkv", {"a": _upload("Movie A"), "b": {"action": "skip"}})
    job = db_session.query(upload_jobs.UploadJob).one()
    env["trackers"]["a"].error = _unreachable("down")
    _run(db_session, tmp_path, job)
    assert job.status == "failed" and video.is_file()

    env["trackers"]["a"].error = None
    upload_jobs.retry_failed(db_session, job)
    _run(db_session, tmp_path, job)

    assert job.status == "done" and not video.exists()
    assert (env["root"] / "torrents" / "My.Movie.2024.mkv").is_file()


def test_a_watched_release_gone_after_one_tracker_cannot_be_retried(db_session, tmp_path, env):
    """Uscita dalla cartella osservata dopo il primo tracker riuscito, la
    cartella resta con il sample: prima un nuovo tentativo partiva lo stesso,
    senza file, e il torrent nasceva dalla copia in seed dell'altro tracker."""
    env["disk"].watch_rel_path = "releases"
    db_session.commit()
    folder = env["root"] / "releases" / "My Movie 2024"
    video = write_video(folder / "My.Movie.2024.1080p.WEB-DL-NZG.mkv", 300 * KB)
    write_video(folder / "Sample" / "sample.mkv", 10 * KB)
    job = _approved(db_session, env, "releases/My Movie 2024", {"a": _upload("Movie A"), "b": _upload("Movie B")})
    job.origin = "watch"
    db_session.commit()
    env["trackers"]["b"].error = _unreachable()

    _run(db_session, tmp_path, job)

    assert (job.status, [t.status for t in job.targets]) == ("partial", ["done", "failed"])
    assert not video.exists() and (folder / "Sample" / "sample.mkv").is_file()
    with pytest.raises(UploadJobError) as exc:
        upload_jobs.retry_failed(db_session, job)
    assert exc.value.code == "upload_source_missing"
    assert job.status == "partial"


@pytest.mark.parametrize("cause, unsure", [
    (httpx.ReadTimeout("timed out"), True),  # la risposta non è arrivata: il tracker può averlo salvato
    (None, True),  # "nessun id riconoscibile", con success: true
    (httpx.ConnectError("refused"), False),  # mai partita
    (httpx.HTTPStatusError("422", request=httpx.Request("POST", "https://t"),
                           response=httpx.Response(422, request=httpx.Request("POST", "https://t"))), False),
])
def test_an_upload_failed_after_sending_is_retried_only_once_confirmed(db_session, tmp_path, env, cause, unsure):
    """Audit 2026-10-18: un timeout, un 5xx o una risposta illeggibile dopo
    l'invio non dicono se il tracker l'ha salvato; "Riprova" lo rimandava con
    un clic, e la ricerca di UNIT3D non elenca i torrent in moderazione."""
    video = write_video(env["root"] / "media" / "The.Matrix.1999.1080p.WEB-DL.H.264-GRP.mkv", 300 * KB)
    error = UploadError(f"UNIT3D upload failed: {cause!r}")
    error.__cause__ = cause
    env["trackers"]["a"].error = error
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("Matrix A"), "b": {"action": "skip"}})

    _run(db_session, tmp_path, job)

    a = job.targets[0]
    assert job.status == "failed"
    if not unsure:
        assert a.error_message == str(error)
        upload_jobs.retry_failed(db_session, job)
        assert a.status == "approved"
        return
    assert a.error_message == "upload_outcome_unknown"
    event = next(e for e in job.events if e.code == "upload_outcome_unknown")
    assert json.loads(event.params_json)["error"] == str(error)
    with pytest.raises(UploadJobError) as exc:
        upload_jobs.retry_failed(db_session, job)
    assert (exc.value.code, exc.value.params) == ("upload_retry_needs_confirm", {"trackers": "a"})
    upload_jobs.retry_failed(db_session, job, confirm_interrupted=True)
    assert a.status == "approved"


def test_a_failure_before_sending_never_asks_for_a_confirmation(db_session, tmp_path, env):
    video = write_video(env["root"] / "media" / "Movie.2024.mkv", 100 * KB)
    job = _approved(db_session, env, "media/" + video.name, {"a": _upload("A"), "b": {"action": "skip"}})
    job.targets[0].tracker.announce_url = None
    db_session.commit()

    _run(db_session, tmp_path, job)

    assert job.targets[0].error_message == "tracker_missing_announce_url"
    upload_jobs.retry_failed(db_session, job)
    assert job.status == "queued"
