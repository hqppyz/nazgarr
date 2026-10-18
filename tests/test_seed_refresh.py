"""Il seed appena creato registrato subito (nazgarr/library/seed_refresh.py),
e il controllo completo di un'esecuzione (nazgarr/reseed/full_check.py),
dove l'executor ha messo davvero gli hardlink."""

import hashlib
import os

import pytest

from nazgarr.core.models import SeedFile
from nazgarr.library import seed_refresh
from nazgarr.reseed import executor
from nazgarr.torrents.metainfo import compute_info_hash
from tests.test_executor import (  # noqa: F401 (fixture autouse)
    ReseedClient,
    _movie_review,
    _movie_torrent,
    _tracker_torrent,
)
from tests.test_season_pack import _bencode


@pytest.mark.parametrize(("layout", "folder", "expected"), [
    ("Subfolder", None, "torrents/Movie.2024/Movie.2024.mkv"),
    ("NoSubfolder", "Release.Name", "torrents/Movie.2024.mkv"),
    ("Original", "Release.Name", "torrents/Release.Name/Movie.2024.mkv"),
    ("Original", None, "torrents/Movie.2024.mkv"),
])
def test_a_new_seed_is_registered_where_the_executor_put_its_hardlink(db_session, tmp_path, layout, folder,
                                                                         expected):
    """Con il layout "Subfolder" o "NoSubfolder" di qBittorrent e qui si
    ricostruiva sempre la cartella del torrent: nessun hardlink trovato, e
    l'elemento restava orfano fino alla scansione dopo (audit 2026-10-18)."""
    root, review = _movie_review(db_session, tmp_path, folder=folder)
    adapter = ReseedClient(layout=layout)
    seed_job = executor.execute_review(db_session, review, adapter)
    assert (root / expected).is_file()

    counts = seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)

    assert counts["seed_files"] == 1
    row = db_session.query(SeedFile).one()
    assert (row.relative_path, row.media_file_id) == (expected, review.media_file_id)


def test_another_file_at_the_hardlink_path_is_not_linked_to_the_library_file(db_session, tmp_path):
    root, review = _movie_review(db_session, tmp_path)
    adapter = ReseedClient(layout="Original")
    seed_job = executor.execute_review(db_session, review, adapter)
    link = root / "torrents" / "Movie.2024.mkv"
    os.unlink(link)
    link.write_bytes(b"another file")

    seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)

    row = db_session.query(SeedFile).one()
    assert row.relative_path == "torrents/Movie.2024.mkv" and row.media_file_id is None


def test_a_symlink_to_the_library_file_is_never_taken_for_its_hardlink(db_session, tmp_path):
    """Lo stat passava dal percorso già risolto (audit 2026-10-18): un link
    simbolico alla posizione "Original", verso il file della libreria, ne
    aveva l'inode, sceglieva quella posizione ed era registrato come
    hardlink in seed, da un percorso che lo scanner salta."""
    root, review = _movie_review(db_session, tmp_path, folder="Release.Name")
    adapter = ReseedClient(layout="NoSubfolder")
    seed_job = executor.execute_review(db_session, review, adapter)
    assert (root / "torrents" / "Movie.2024.mkv").is_file()  # l'hardlink vero, senza la cartella
    os.makedirs(root / "torrents" / "Release.Name")
    os.symlink(root / "media" / "movies" / "Movie.2024.mkv", root / "torrents" / "Release.Name" / "Movie.2024.mkv")

    seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)

    row = db_session.query(SeedFile).one()
    assert (row.relative_path, row.media_file_id) == ("torrents/Movie.2024.mkv", review.media_file_id)


def test_a_symlink_in_place_of_the_hardlink_or_of_its_folder_is_not_registered(db_session, tmp_path):
    root, review = _movie_review(db_session, tmp_path, folder="Release.Name")
    adapter = ReseedClient(layout="Original")
    seed_job = executor.execute_review(db_session, review, adapter)
    link = root / "torrents" / "Release.Name" / "Movie.2024.mkv"
    os.unlink(link)
    os.symlink(root / "media" / "movies" / "Movie.2024.mkv", link)

    assert seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)["seed_files"] == 0
    assert db_session.query(SeedFile).count() == 0

    # Una cartella sopra che è un link, anche verso un hardlink vero dentro il disco.
    os.unlink(link)
    os.rmdir(root / "torrents" / "Release.Name")
    os.makedirs(root / "elsewhere")
    os.link(root / "media" / "movies" / "Movie.2024.mkv", root / "elsewhere" / "Movie.2024.mkv")
    os.symlink(root / "elsewhere", root / "torrents" / "Release.Name")

    assert seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)["seed_files"] == 0
    assert db_session.query(SeedFile).count() == 0


def test_a_library_folder_that_is_itself_a_link_inside_the_disk_still_counts(db_session, tmp_path):
    """Come per lo scanner, la cartella configurata può essere un link dentro
    il disco: si rifiutano solo i link sotto di lei."""
    root, review = _movie_review(db_session, tmp_path)
    adapter = ReseedClient(layout="Original")
    seed_job = executor.execute_review(db_session, review, adapter)
    assert review.media_file.disk.media_folders == ["media/movies"]
    os.rename(root / "media" / "movies", root / "real-movies")
    os.symlink(root / "real-movies", root / "media" / "movies")

    seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)

    row = db_session.query(SeedFile).one()
    assert (row.relative_path, row.media_file_id) == ("torrents/Movie.2024.mkv", review.media_file_id)


@pytest.mark.parametrize(("layout", "folder"), [
    ("Subfolder", None), ("NoSubfolder", "Release.Name"), ("Original", "Release.Name"), ("Original", None),
])
def test_the_full_check_of_an_execution_reads_the_hardlinks_where_the_executor_put_them(
        db_session, tmp_path, layout, folder):
    """build_locator ricostruiva sempre la cartella del torrent: con
    "Subfolder" o "NoSubfolder" non trovava gli hardlink, leggeva il file
    della libreria e diceva "library", cioè hardlink mancanti (audit
    2026-10-18). Ora la stessa regola dell'executor (seed_refresh.hardlink_folder)."""
    from nazgarr.reseed import full_check

    _root, review = _movie_review(db_session, tmp_path, folder=folder)
    torrent = _movie_torrent()
    if folder:  # la cartella del candidato è quella del .torrent (full_check._sync_folder)
        torrent = _bencode({"info": {"name": folder, "piece length": 16, "pieces": hashlib.sha1(b"content").digest(),
                                     "files": [{"length": 7, "path": ["Movie.2024.mkv"]}]}})
    adapter = ReseedClient(layout=layout)
    adapter.info_hash = compute_info_hash(torrent)
    seed_job = executor.execute_review(db_session, review, adapter)

    result = full_check.run_full_check(db_session, review.candidate, seed_job, fetch_torrent=lambda _: torrent)

    assert [f.location for f in result.files] == ["seed"] and result.percent == 100.0
    assert full_check.verdict(result) == (True, None)
