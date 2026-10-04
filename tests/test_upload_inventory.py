"""Una sola regola per i file che entrano nel torrent (nazgarr/upload_inventory.py):
analisi, nomi e hashing vedono gli stessi file."""

import pytest
import torf

from nazgarr import upload_inventory
from nazgarr.upload_inventory import SAMPLE_MAX_BYTES, in_torrent, is_sample


@pytest.mark.parametrize(("relative", "size", "kept"), [
    ("Movie.2024.mkv", 5 * 2**30, True),
    ("Sample/sample.mkv", 10, False),  # nella cartella sample
    ("samples/Movie.mkv", 5 * 2**30, False),
    ("movie-sample.mkv", 10 * 2**20, False),  # parola a sé, piccolo
    ("Free.Sample.2020.1080p.mkv", 5 * 2**30, True),  # un film che si chiama così
    ("Show.S01E03.The.Sample.mkv", 2 * 2**30, True),
    ("Show.S01E03.The.Sample.480p.mkv", 180 * 2**20, True),  # un episodio SD piccolo, non un sample
    ("sample-grp.mkv", 30 * 2**20, False),
    ("sample.mkv", 30 * 2**20, False),
    ("Resampled.2020.mkv", 10, True),  # non è la parola "sample"
    ("Thumbs.db", 1, False),
    (".DS_Store", 1, False),
    (".hidden/Movie.mkv", 5 * 2**30, False),
    ("Movie.mkv.part", 5 * 2**30, False),
    ("Movie.mkv.!qB", 5 * 2**30, False),
    ("Subs/English.srt", 1, True),
])
def test_what_goes_in_the_torrent(relative, size, kept):
    assert in_torrent(relative, size) is kept


def test_a_sample_is_only_small_or_in_a_sample_folder():
    assert is_sample("x.sample.mkv", SAMPLE_MAX_BYTES - 1)
    assert not is_sample("x.sample.mkv", SAMPLE_MAX_BYTES)


def test_a_movie_with_sample_in_its_title_is_hashed_with_its_folder(tmp_path, monkeypatch):
    """Con i glob "*sample*" il torrent di questo film usciva vuoto."""
    monkeypatch.setattr(upload_inventory, "SAMPLE_MAX_BYTES", 1024)  # file piccoli nel test
    from types import SimpleNamespace

    from nazgarr.upload_execute import hash_pieces

    folder = tmp_path / "Free.Sample.2020.1080p-GRP"
    (folder / "Sample").mkdir(parents=True)
    (folder / "Free.Sample.2020.1080p-GRP.mkv").write_bytes(b"v" * 4096)
    (folder / "Free.Sample.2020.1080p-GRP-sample.mkv").write_bytes(b"s" * 64)  # sample accanto al film
    (folder / "Sample" / "free.sample.mkv").write_bytes(b"s" * 64)
    (folder / "Thumbs.db").write_bytes(b"x")

    class Session:
        def refresh(self, _job):
            pass

        def commit(self):
            pass

    job = SimpleNamespace(source_path=str(folder), status="running", progress_json=None)
    torrent = hash_pieces(Session(), job)

    assert [str(f) for f in torrent.files] == ["Free.Sample.2020.1080p-GRP/Free.Sample.2020.1080p-GRP.mkv"]
    assert torrent.mode == "multifile"  # la cartella resta, anche con un file solo
    assert [f.relative for f in upload_inventory.torrent_files(str(folder))] == ["Free.Sample.2020.1080p-GRP.mkv"]
    assert isinstance(torrent, torf.Torrent)
