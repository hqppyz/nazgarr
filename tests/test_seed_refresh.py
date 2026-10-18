"""Il seed appena creato registrato subito (nazgarr/library/seed_refresh.py),
dove l'executor ha messo davvero gli hardlink."""

import os

import pytest

from nazgarr.core.models import SeedFile
from nazgarr.library import seed_refresh
from nazgarr.reseed import executor
from tests.test_executor import LayoutAdapter, _movie_review, _tracker_torrent  # noqa: F401 (fixture autouse)


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
    adapter = LayoutAdapter(layout)
    seed_job = executor.execute_review(db_session, review, adapter)
    assert (root / expected).is_file()

    counts = seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)

    assert counts["seed_files"] == 1
    row = db_session.query(SeedFile).one()
    assert (row.relative_path, row.media_file_id) == (expected, review.media_file_id)


def test_another_file_at_the_hardlink_path_is_not_linked_to_the_library_file(db_session, tmp_path):
    root, review = _movie_review(db_session, tmp_path)
    adapter = LayoutAdapter("Original")
    seed_job = executor.execute_review(db_session, review, adapter)
    link = root / "torrents" / "Movie.2024.mkv"
    os.unlink(link)
    link.write_bytes(b"another file")

    seed_refresh.refresh_seeded_torrent(db_session, seed_job, adapter, None)

    row = db_session.query(SeedFile).one()
    assert row.relative_path == "torrents/Movie.2024.mkv" and row.media_file_id is None
