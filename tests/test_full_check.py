import hashlib
import os
import threading
from datetime import UTC, datetime

from nazgarr.core.models import Candidate, CandidateFile, Disk, MediaFile, MediaItem, SeedJob, Tracker
from nazgarr.reseed import full_check, pipeline

PIECE = 16


def _bencode(value) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, str):
        return _bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0].encode() if isinstance(kv[0], str) else kv[0])
        return b"d" + b"".join(_bencode(k) + _bencode(v) for k, v in items) + b"e"
    raise TypeError(type(value))


def _torrent(folder: str, files: dict[str, bytes]) -> bytes:
    stream = b"".join(files.values())
    pieces = b"".join(hashlib.sha1(stream[i:i + PIECE]).digest() for i in range(0, len(stream), PIECE))
    info = {
        "name": folder, "piece length": PIECE, "pieces": pieces,
        "files": [{"length": len(data), "path": path.split("/")} for path, data in files.items()],
    }
    return _bencode({"info": info})


# Due file con lunghezze non multiple del piece: il secondo piece è a cavallo.
FILES = {"Movie.2001.mkv": b"A" * 24 + b"B" * 16, "Movie.2001.nfo": b"nfo-data-here!!"}


def _setup(db_session, tmp_path, library: dict[str, bytes]):
    root = tmp_path / "disk"
    (root / "media/Movie (2001)").mkdir(parents=True)
    (root / "torrents").mkdir()
    disk = Disk(label="d", root_path=str(root), media_rel_path="media", torrents_rel_path="torrents")
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    item = MediaItem(content_type="movie", tmdb_id=1)
    db_session.add_all([disk, tracker, item])
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    candidate = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="Movie", size_bytes=55,
        source="catalog_search", direction="media_to_torrent", confidence=0.9, folder="Movie",
        download_link="https://t.example/dl/1",
    )
    db_session.add(candidate)
    db_session.commit()
    for name, data in library.items():
        rel = f"media/Movie (2001)/{name}"
        (root / rel).write_bytes(data)
        mf = MediaFile(disk_id=disk.id, relative_path=rel, size_bytes=len(data), st_dev=1, inode=1,
                       media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC))
        db_session.add(mf)
        db_session.commit()
        db_session.add(CandidateFile(candidate_id=candidate.id, torrent_path=name, size_bytes=len(data),
                                     is_video=name.endswith(".mkv"), media_file_id=mf.id))
    db_session.commit()
    return disk, candidate


def _check(db_session, candidate, seed_job=None):
    content = _torrent("Movie", FILES)
    return full_check.run_full_check(db_session, candidate, seed_job, fetch_torrent=lambda _: content)


def test_identical_files_verify_at_100_percent_including_the_boundary_piece(db_session, tmp_path):
    _, candidate = _setup(db_session, tmp_path, FILES)

    result = _check(db_session, candidate)

    assert (result.ok, result.pieces, result.mismatched, result.unreadable) == (4, 4, 0, 0)
    assert result.percent == 100.0
    assert [f.location for f in result.files] == ["library", "library"]


def test_a_changed_byte_is_reported_on_the_file_and_piece_it_belongs_to(db_session, tmp_path):
    changed = dict(FILES)
    changed["Movie.2001.mkv"] = b"A" * 24 + b"B" * 15 + b"X"
    _, candidate = _setup(db_session, tmp_path, changed)

    result = _check(db_session, candidate)

    assert result.mismatched == 1 and result.bad_pieces == [2]  # il piece 32..48, a cavallo dei due file
    video, nfo = result.files
    assert (video.ok, video.mismatched, video.first_bad_offset) == (2, 1, 32)
    assert (nfo.ok, nfo.mismatched) == (1, 1)


def test_a_missing_file_makes_its_pieces_unreadable_not_mismatched(db_session, tmp_path):
    _, candidate = _setup(db_session, tmp_path, {"Movie.2001.mkv": FILES["Movie.2001.mkv"]})

    result = _check(db_session, candidate)

    assert result.mismatched == 0 and result.unreadable == 2
    assert result.files[1].local_path is None


def test_after_an_execution_the_files_are_read_where_the_client_sees_them(db_session, tmp_path):
    disk, candidate = _setup(db_session, tmp_path, FILES)
    video = next(f for f in candidate.files if f.is_video)
    seed_dir = tmp_path / "disk/torrents/Movie"
    seed_dir.mkdir()
    os.link(tmp_path / "disk" / video.media_file.relative_path, seed_dir / "Movie.2001.mkv")  # nfo mai linkato
    job = SeedJob(candidate_id=candidate.id, source_media_file_id=video.media_file_id, final_status="failed")
    db_session.add(job)
    db_session.commit()

    result = _check(db_session, candidate, job)

    assert [f.location for f in result.files] == ["seed", "library"]
    assert result.percent == 100.0


def test_background_check_runs_and_reports_progress(db_session, tmp_path):
    _, candidate = _setup(db_session, tmp_path, FILES)
    content = _torrent("Movie", FILES)
    factory = lambda: db_session  # noqa: E731 — la stessa sessione del test

    state = full_check.start_check(factory, db_session, candidate.id, fetch_torrent=lambda _: content)
    full_check._executor.submit(lambda: None).result()  # aspetta la coda (un worker)

    assert state.status == "done", state.error
    assert state.bytes_done == state.bytes_total == 55
    assert state.result["percent"] == 100.0


def _review(db_session, candidate):
    from nazgarr.core.models import MatchReview

    video = next(f for f in candidate.files if f.is_video)
    r = MatchReview(candidate_id=candidate.id, media_file_id=video.media_file_id, status="pending")
    db_session.add(r)
    db_session.commit()
    return r


def _approve_and_wait(db_session, candidate, monkeypatch, executed):
    from nazgarr.reseed import review

    monkeypatch.setattr(review, "_try_execute", lambda session, r, skip_recheck=False: executed.append(r.id))
    r = _review(db_session, candidate)
    content = _torrent("Movie", FILES)
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_session.get_bind())
    # Il thread del controllo resta occupato finché non si apre il cancello:
    # lo stato intermedio si guarda prima che il controllo possa partire, se
    # no dipendeva da chi arrivava prima (test instabile).
    gate = threading.Event()
    full_check._executor.submit(gate.wait)
    review.request_approval(db_session, r, factory, fetch_torrent=lambda _: content)
    assert r.verify_status == "verifying" and r.status == "pending"  # ancora in coda, niente eseguito
    gate.set()
    full_check._executor.submit(lambda: None).result()
    # Chiude la transazione aperta: in WAL vedrebbe ancora il DB di prima
    # dell'esito salvato dal thread del controllo (expire_all non basta).
    db_session.commit()
    db_session.expire_all()
    return r, full_check.get_check(r.verify_check_id)


def test_approve_executes_only_after_the_full_check_passes(db_session, tmp_path, monkeypatch):
    _, candidate = _setup(db_session, tmp_path, FILES)
    executed = []

    r, state = _approve_and_wait(db_session, candidate, monkeypatch, executed)

    assert (r.verify_status, r.status, executed) == ("passed", "approved", [r.id])
    assert (state.verdict, state.stage) == ("passed", "executing")


def test_a_failed_check_leaves_the_review_in_the_queue_and_touches_nothing(db_session, tmp_path, monkeypatch):
    changed = dict(FILES)
    changed["Movie.2001.mkv"] = b"Z" * 40
    _, candidate = _setup(db_session, tmp_path, changed)
    executed = []

    r, state = _approve_and_wait(db_session, candidate, monkeypatch, executed)

    assert (r.verify_status, r.status, executed) == ("failed", "pending", [])
    assert "pieces differ" in r.verify_detail and state.execution == "skipped"


def test_a_missing_extra_passes_because_the_client_downloads_it(db_session, tmp_path, monkeypatch):
    _, candidate = _setup(db_session, tmp_path, {"Movie.2001.mkv": FILES["Movie.2001.mkv"]})
    executed = []

    r, _ = _approve_and_wait(db_session, candidate, monkeypatch, executed)

    assert (r.verify_status, executed) == ("passed", [r.id])


def test_with_the_setting_off_approve_executes_right_away(db_session, tmp_path, monkeypatch):
    from nazgarr.core import settings_repo
    from nazgarr.reseed import review

    _, candidate = _setup(db_session, tmp_path, FILES)
    settings_repo.set_setting(db_session, review.VERIFY_SETTING, "false")
    executed = []
    monkeypatch.setattr(review, "_try_execute", lambda session, r, skip_recheck=False: executed.append(r.id))
    r = _review(db_session, candidate)

    review.request_approval(db_session, r, lambda: db_session)

    assert (r.status, r.verify_status, executed) == ("approved", None, [r.id])


def _approve_recording_skip(db_session, candidate, monkeypatch, skip_setting):
    from sqlalchemy.orm import sessionmaker

    from nazgarr.core import settings_repo
    from nazgarr.reseed import review

    if skip_setting:
        settings_repo.set_setting(db_session, review.SKIP_RECHECK_SETTING, "true")
    calls = []
    monkeypatch.setattr(review, "_try_execute", lambda session, r, skip_recheck=False: calls.append(skip_recheck))
    content = _torrent("Movie", FILES)
    review.request_approval(db_session, _review(db_session, candidate), sessionmaker(bind=db_session.get_bind()),
                            fetch_torrent=lambda _: content)
    full_check._executor.submit(lambda: None).result()
    return calls


def test_the_client_recheck_is_skipped_only_when_enabled_and_verified_100_percent(db_session, tmp_path, monkeypatch):
    _, candidate = _setup(db_session, tmp_path, FILES)
    assert _approve_recording_skip(db_session, candidate, monkeypatch, skip_setting=False) == [False]


def test_with_the_option_on_a_full_verification_skips_the_client_recheck(db_session, tmp_path, monkeypatch):
    _, candidate = _setup(db_session, tmp_path, FILES)
    assert _approve_recording_skip(db_session, candidate, monkeypatch, skip_setting=True) == [True]


def test_a_missing_extra_always_needs_the_client_recheck(db_session, tmp_path, monkeypatch):
    # L'nfo manca in locale: il controllo passa, ma il client deve scaricarlo.
    _, candidate = _setup(db_session, tmp_path, {"Movie.2001.mkv": FILES["Movie.2001.mkv"]})
    assert _approve_recording_skip(db_session, candidate, monkeypatch, skip_setting=True) == [False]



def test_the_check_takes_the_torrent_folder_the_catalog_did_not_report(db_session, tmp_path):
    # Segnalato (2026-10-06): un file solo dentro una cartella, il candidato
    # senza cartella (dal catalogo). Il controllo prima di eseguire scarica il
    # .torrent: la cartella si corregge prima che nasca un hardlink.
    single = {"Movie.2001.mkv": FILES["Movie.2001.mkv"]}
    _, candidate = _setup(db_session, tmp_path, single)
    candidate.folder = None
    db_session.commit()

    result = full_check.run_full_check(db_session, candidate, fetch_torrent=lambda _: _torrent("Movie", single))

    assert candidate.folder == "Movie"
    assert result.ok == result.pieces
