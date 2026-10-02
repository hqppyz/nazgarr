import os

from nazgarr.torrent_create import create_torrent


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
