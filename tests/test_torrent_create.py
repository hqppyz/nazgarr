import os

from nazgarr.torrents.create import create_torrent


def test_create_torrent_writes_file_and_returns_info_hash(tmp_path):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"x" * 20000)
    output = tmp_path / "movie.torrent"

    result_path, info_hash = create_torrent(str(source), "https://tracker.example/announce", str(output))

    assert result_path == str(output)
    assert os.path.isfile(output)
    assert len(info_hash) == 40  # sha1 hex


def test_create_torrent_overwrites_existing_file(tmp_path):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"x" * 20000)
    output = tmp_path / "movie.torrent"
    output.write_bytes(b"stale")

    create_torrent(str(source), "https://tracker.example/announce", str(output))

    assert output.stat().st_size > len(b"stale")


def test_the_torrent_says_it_was_created_by_nazgarr(tmp_path):
    import torf

    source = tmp_path / "movie.mkv"
    source.write_bytes(b"x" * 20000)
    output = tmp_path / "movie.torrent"

    _, info_hash = create_torrent(str(source), "https://tracker.example/announce", str(output))

    created_by = torf.Torrent.read(str(output)).created_by
    assert created_by.startswith("Nazgarr ") and created_by.endswith("(https://github.com/lktorrentz/nazgarr)")
    # Fuori dal dizionario info: l'info hash non cambia.
    plain = torf.Torrent(path=str(source), trackers=["https://tracker.example/announce"], private=True)
    plain.generate()
    assert plain.infohash == info_hash
