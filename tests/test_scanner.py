"""Fase 1 — definition of done (docs/ROADMAP.md): dato un disco con path
media e torrent reali, l'app produce correttamente la lista di file
con/senza hardlink.
"""

import os
from datetime import UTC, datetime

from nazgarr.core.models import Disk, MediaFile
from nazgarr.library import scanner
from nazgarr.library import states as library
from nazgarr.reseed import pipeline


def _make_disk(db_session, tmp_path, torrents_rel_path="torrents"):
    root = tmp_path / "disk1"
    (root / "media" / "movies").mkdir(parents=True)
    (root / torrents_rel_path).mkdir(parents=True)

    disk = Disk(
        label="disk1", root_path=str(root), media_rel_path="media/movies",
        torrents_rel_path=torrents_rel_path,
    )
    db_session.add(disk)
    db_session.commit()

    return disk, root


def _run_scan(db_session, disk):
    run = pipeline.start_run(db_session, run_type="bulk_import")
    counts = scanner.scan_disk(db_session, disk, run)
    return run, counts


def test_hardlinked_file_is_linked(db_session, tmp_path):
    # Lo scanner rileva solo l'hardlink (seed_file.media_file_id) — lo stato
    # "seeding" completo richiede anche il tracciamento del client (Fase 2,
    # vedi tests/test_library_states.py), qui deliberatamente non configurato.
    disk, root = _make_disk(db_session, tmp_path)

    media_file_path = root / "media" / "movies" / "Movie.2024.mkv"
    media_file_path.write_bytes(b"fake video content")
    torrent_file_path = root / "torrents" / "Movie.2024.mkv"
    os.link(media_file_path, torrent_file_path)  # hardlink reale, stesso inode

    _run_scan(db_session, disk)

    media_states = library.media_file_states(db_session)
    seed_states = library.seed_file_states(db_session)

    assert len(media_states) == 1
    assert len(seed_states) == 1
    assert seed_states[0]["media_file_id"] == media_states[0]["id"]
    # Senza un client configurato, nessun file può essere "seeding" a tutti gli effetti.
    assert media_states[0]["state"] == "orphan_media"
    assert seed_states[0]["state"] == "orphan_torrent"


def test_media_file_without_hardlink_is_orphan(db_session, tmp_path):
    disk, root = _make_disk(db_session, tmp_path)

    (root / "media" / "movies" / "Lonely.2024.mkv").write_bytes(b"no link for me")

    _run_scan(db_session, disk)

    media_states = library.media_file_states(db_session)
    assert len(media_states) == 1
    assert media_states[0]["state"] == "orphan_media"


def test_seed_file_without_media_counterpart_is_orphan_torrent(db_session, tmp_path):
    disk, root = _make_disk(db_session, tmp_path)

    (root / "torrents" / "Standalone.2024.mkv").write_bytes(b"seeding but not in library")

    _run_scan(db_session, disk)

    seed_states = library.seed_file_states(db_session)
    assert len(seed_states) == 1
    assert seed_states[0]["state"] == "orphan_torrent"
    assert seed_states[0]["media_file_id"] is None


def test_non_video_file_on_media_side_is_indexed_too(db_session, tmp_path):
    # Anche lato libreria ogni file viene registrato: nfo e sottotitoli
    # servono a ricreare i torrent che li contengono. Nasconderli è compito
    # delle esclusioni, mai dello scanner.
    disk, root = _make_disk(db_session, tmp_path)

    (root / "media" / "movies" / "readme.txt").write_bytes(b"not a video")

    _run_scan(db_session, disk)

    states = library.media_file_states(db_session)
    assert [s["relative_path"] for s in states] == [os.path.join("media", "movies", "readme.txt")]


def test_non_video_file_on_torrent_side_is_still_indexed(db_session, tmp_path):
    # Lato torrent NON filtriamo per estensione (sottotitoli/nfo/sample
    # fanno parte del torrent, servono dalla Fase 2 per client_torrent_file).
    disk, root = _make_disk(db_session, tmp_path)

    (root / "torrents" / "movie.srt").write_bytes(b"subtitle")

    _run_scan(db_session, disk)

    seed_states = library.seed_file_states(db_session)
    assert len(seed_states) == 1
    assert seed_states[0]["relative_path"] == os.path.join("torrents", "movie.srt")


def test_rescanning_does_not_duplicate_rows(db_session, tmp_path):
    disk, root = _make_disk(db_session, tmp_path)

    media_file_path = root / "media" / "movies" / "Movie.2024.mkv"
    media_file_path.write_bytes(b"fake video content")
    os.link(media_file_path, root / "torrents" / "Movie.2024.mkv")

    _run_scan(db_session, disk)
    _second_run, second_counts = _run_scan(db_session, disk)

    media_states = library.media_file_states(db_session)
    seed_states = library.seed_file_states(db_session)
    assert len(media_states) == 1
    assert len(seed_states) == 1
    assert seed_states[0]["media_file_id"] == media_states[0]["id"]
    # 1 media_file + 1 seed_file ri-scansionati, non duplicati (upsert su disk_id+relative_path)
    assert second_counts == {"media_files_scanned": 1, "seed_files_scanned": 1}


def test_disk_without_torrents_rel_path_only_scans_media(db_session, tmp_path):
    root = tmp_path / "disk2"
    (root / "media" / "movies").mkdir(parents=True)
    disk = Disk(label="disk2", root_path=str(root), media_rel_path="media/movies")  # torrents_rel_path non configurato
    db_session.add(disk)
    db_session.commit()

    (root / "media" / "movies" / "Movie.2024.mkv").write_bytes(b"content")

    _run_scan(db_session, disk)

    assert len(library.media_file_states(db_session)) == 1
    assert library.seed_file_states(db_session) == []


def test_disk_without_media_rel_path_only_scans_torrents(db_session, tmp_path):
    root = tmp_path / "disk3"
    (root / "torrents").mkdir(parents=True)
    disk = Disk(label="disk3", root_path=str(root), torrents_rel_path="torrents")  # media_rel_path non configurato
    db_session.add(disk)
    db_session.commit()

    (root / "torrents" / "Standalone.2024.mkv").write_bytes(b"content")

    _run_scan(db_session, disk)

    assert library.media_file_states(db_session) == []
    assert len(library.seed_file_states(db_session)) == 1


def test_scan_populates_content_hash(db_session, tmp_path):
    disk, root = _make_disk(db_session, tmp_path)
    (root / "media" / "movies" / "Movie.2024.mkv").write_bytes(b"fake video content")

    _run_scan(db_session, disk)

    mf = db_session.query(MediaFile).one()
    assert mf.content_hash is not None


def test_bulk_upsert_writes_more_rows_than_a_single_sqlite_statement_allows(db_session):
    """Con ogni file della libreria registrato, un disco arriva a decine di
    migliaia di righe: in un'unica istruzione superava il limite di
    parametri di SQLite e lo scan falliva (0 file scansionati)."""
    from nazgarr.core.db_utils import UPSERT_CHUNK_ROWS, bulk_upsert
    from nazgarr.core.models import Disk, MediaFile

    disk = Disk(label="d", root_path="/mnt/d", media_rel_path="media")
    db_session.add(disk)
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    import sqlite3

    limit = sqlite3.connect(":memory:").getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    rows = [
        {"disk_id": disk.id, "relative_path": f"media/f{i}.nfo", "size_bytes": i, "st_dev": 1, "inode": i,
         "nlink": 1, "content_hash": None, "last_scan_id": run.id, "last_seen_at": datetime.now(UTC)}
        for i in range(limit // 9 + UPSERT_CHUNK_ROWS)  # oltre il limite in un'unica istruzione
    ]

    bulk_upsert(db_session, MediaFile.__table__, rows, conflict_cols=["disk_id", "relative_path"],
                update_cols=["size_bytes"])
    db_session.commit()

    assert db_session.query(MediaFile).count() == len(rows)


def test_symlinks_are_never_listed(tmp_path):
    from nazgarr.library.scanner import _list_files

    (tmp_path / "media").mkdir()
    real = tmp_path / "media" / "Movie.mkv"
    real.write_bytes(b"x")
    secret = tmp_path / "nazgarr.db"
    secret.write_bytes(b"db")
    (tmp_path / "media" / "innocent.mkv").symlink_to(secret)

    assert _list_files(str(tmp_path / "media")) == [str(real)]


def test_the_content_hash_is_reread_only_for_changed_files(db_session, tmp_path, monkeypatch):
    """La seconda scansione riusa l'hash dei file invariati (stesso inode,
    dimensione e mtime) e rilegge solo quelli cambiati."""
    disk, root = _make_disk(db_session, tmp_path)
    same = root / "media" / "movies" / "Same.2024.mkv"
    changed = root / "media" / "movies" / "Changed.2024.mkv"
    same.write_bytes(b"a" * 1000)
    changed.write_bytes(b"b" * 1000)
    _run_scan(db_session, disk)
    before = {mf.relative_path: mf.content_hash for mf in db_session.query(MediaFile)}

    changed.write_bytes(b"c" * 1000)  # stessa dimensione, contenuto e mtime nuovi
    os.utime(changed, ns=(1, os.stat(changed).st_mtime_ns + 10**9))
    read = []
    real = scanner.compute_fast_hash
    monkeypatch.setattr(scanner, "compute_fast_hash", lambda path: read.append(os.path.basename(path)) or real(path))
    _run_scan(db_session, disk)
    db_session.expire_all()
    after = {mf.relative_path: mf.content_hash for mf in db_session.query(MediaFile)}

    assert read == ["Changed.2024.mkv"]
    assert after["media/movies/Same.2024.mkv"] == before["media/movies/Same.2024.mkv"]
    assert after["media/movies/Changed.2024.mkv"] != before["media/movies/Changed.2024.mkv"]
