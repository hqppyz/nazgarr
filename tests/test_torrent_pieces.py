import hashlib

from nazgarr.torrents.pieces import verify_file_pieces


def _pieces(content: bytes, piece_length: int) -> list[bytes]:
    return [hashlib.sha1(content[i : i + piece_length]).digest() for i in range(0, len(content), piece_length)]


def test_verify_clean_single_file(tmp_path):
    content = b"0123456789abcdef" * 4  # 64 byte, 4 piece esatte
    path = tmp_path / "movie.mkv"
    path.write_bytes(content)

    result = verify_file_pieces(
        str(path), piece_length=16, pieces=_pieces(content, 16), total_length=64, file_offset=0, file_length=64
    )

    assert result.ok == 4
    assert result.mismatches == 0
    assert result.boundary == 0
    assert result.clean is True


def test_verify_detects_mismatch(tmp_path):
    content = b"0123456789abcdef" * 4
    tampered = bytearray(content)
    tampered[20] = tampered[20] ^ 0xFF  # corrompe un byte dentro la seconda piece
    path = tmp_path / "movie.mkv"
    path.write_bytes(bytes(tampered))

    result = verify_file_pieces(
        str(path), piece_length=16, pieces=_pieces(content, 16), total_length=64, file_offset=0, file_length=64
    )

    assert result.mismatches > 0
    assert result.clean is False


def test_verify_isolates_file_within_multi_file_torrent(tmp_path):
    # Torrent virtuale: file_a (16 byte) + file_b (32 byte), piece da 16 byte
    # -> 3 piece totali, tutte allineate ai confini file in questo caso.
    file_a = b"a" * 16
    file_b = b"b" * 32
    concatenated = file_a + file_b
    pieces = _pieces(concatenated, 16)

    path_b = tmp_path / "file_b.mkv"
    path_b.write_bytes(file_b)

    result = verify_file_pieces(
        str(path_b), piece_length=16, pieces=pieces, total_length=48, file_offset=16, file_length=32
    )

    assert result.ok == 2
    assert result.mismatches == 0
    assert result.boundary == 0


def test_verify_counts_boundary_pieces_not_verifiable_in_isolation(tmp_path):
    # file_a (10 byte) + file_b (10 byte), piece da 16 byte: due piece totali.
    # La prima (byte 0-15) e' a cavallo tra i due file (inizia prima di
    # file_offset=10) -> non verificabile isolando solo file_b, boundary.
    # La seconda (byte 16-19) sta interamente dentro file_b -> verificabile.
    file_a = b"a" * 10
    file_b = b"b" * 10
    concatenated = file_a + file_b
    pieces = _pieces(concatenated, 16)

    path_b = tmp_path / "file_b.mkv"
    path_b.write_bytes(file_b)

    result = verify_file_pieces(
        str(path_b), piece_length=16, pieces=pieces, total_length=20, file_offset=10, file_length=10
    )

    assert result.boundary == 1
    assert result.ok == 1
    assert result.mismatches == 0
    assert result.clean is True


def test_verify_returns_empty_result_on_missing_file():
    result = verify_file_pieces(
        "/nonexistent/path.mkv", piece_length=16, pieces=[b"x" * 20], total_length=16, file_offset=0, file_length=16
    )

    assert result.ok == 0
    assert result.mismatches == 0
    assert result.boundary == 0
    assert result.clean is False


def test_zero_length_file_returns_empty_result(tmp_path):
    path = tmp_path / "empty.mkv"
    path.write_bytes(b"")

    result = verify_file_pieces(str(path), piece_length=16, pieces=[], total_length=0, file_offset=0, file_length=0)

    assert result.clean is False


def test_sampling_reads_only_a_spread_of_pieces(tmp_path, monkeypatch):
    content = bytes(range(256)) * 64  # 16 KiB, 1024 piece da 16 byte
    path = tmp_path / "movie.mkv"
    path.write_bytes(content)
    import builtins

    reads = []
    real_open = builtins.open

    class Spy:
        def __init__(self, fh):
            self._fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._fh.close()

        def seek(self, pos):
            reads.append(pos)
            return self._fh.seek(pos)

        def read(self, n):
            return self._fh.read(n)

    monkeypatch.setattr(builtins, "open", lambda p, mode="r": Spy(real_open(p, mode)))
    result = verify_file_pieces(
        str(path), piece_length=16, pieces=_pieces(content, 16), total_length=len(content),
        file_offset=0, file_length=len(content), max_pieces=8,
    )

    assert result.ok == 8 and result.mismatches == 0 and result.clean
    assert reads[0] == 0 and reads[-1] == len(content) - 16  # primo e ultimo piece compresi
    assert len(reads) == 8


def test_sampling_still_catches_a_corrupted_sampled_piece(tmp_path):
    content = b"0123456789abcdef" * 64
    tampered = bytearray(content)
    tampered[-1] ^= 0xFF  # ultimo piece: sempre nel campione
    path = tmp_path / "movie.mkv"
    path.write_bytes(bytes(tampered))

    result = verify_file_pieces(
        str(path), piece_length=16, pieces=_pieces(content, 16), total_length=len(content),
        file_offset=0, file_length=len(content), max_pieces=8,
    )

    assert result.mismatches == 1
    assert result.clean is False


class _ReadSpy:
    """Un file aperto che registra quanti byte gli si chiedono per volta."""

    def __init__(self, fh, sizes):
        self._fh, self._sizes = fh, sizes

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._fh.close()

    def close(self):
        self._fh.close()

    def seek(self, pos):
        return self._fh.seek(pos)

    def read(self, n):
        self._sizes.append(n)
        return self._fh.read(n)


def test_a_piece_is_hashed_in_bounded_reads_whatever_its_length(tmp_path, monkeypatch):
    # Un .torrent del tracker decide il piece length: un piece grande quanto
    # il file portava l'intero video in memoria con una sola read().
    import builtins

    from nazgarr.torrents import pieces as pieces_module

    content = bytes(range(256)) * 4  # 1 KiB, un solo piece
    path = tmp_path / "movie.mkv"
    path.write_bytes(content)
    sizes = []
    real_open = builtins.open
    monkeypatch.setattr(pieces_module, "HASH_CHUNK", 100)
    monkeypatch.setattr(builtins, "open", lambda p, mode="r": _ReadSpy(real_open(p, mode), sizes))

    result = verify_file_pieces(
        str(path), piece_length=len(content), pieces=_pieces(content, len(content)), total_length=len(content),
        file_offset=0, file_length=len(content),
    )

    assert result.ok == 1 and result.mismatches == 0
    assert sizes and max(sizes) <= 100


def test_a_file_shorter_than_its_piece_is_a_mismatch(tmp_path):
    content = b"0123456789abcdef" * 2
    path = tmp_path / "movie.mkv"
    path.write_bytes(content[:-3])  # troncato dopo la scansione

    result = verify_file_pieces(
        str(path), piece_length=16, pieces=_pieces(content, 16), total_length=32, file_offset=0, file_length=32,
    )

    assert (result.ok, result.mismatches) == (1, 1)


def test_only_boundary_pieces_is_no_proof(tmp_path):
    # Due file da 10 byte, piece da 32: l'unico piece è a cavallo, mai letto.
    content = b"a" * 10 + b"b" * 10
    path = tmp_path / "file_b.mkv"
    path.write_bytes(b"X" * 10)  # contenuto sbagliato, stessa size

    result = verify_file_pieces(
        str(path), piece_length=32, pieces=_pieces(content, 32), total_length=20, file_offset=10, file_length=10,
    )

    assert (result.ok, result.mismatches, result.boundary) == (0, 0, 1)
    assert result.clean is False


def test_a_tiny_wrong_episode_in_a_pack_is_never_piece_verified(tmp_path):
    # Il caso riprodotto: E01 sbagliato ma della size giusta, più piccolo di
    # un piece. Prima risultava verificato a 0.99 e il pack veniva consigliato.
    from nazgarr.torrents import layout as torrent_layout
    from nazgarr.torrents.metainfo import TorrentFileEntry, TorrentInfo

    e01, e02 = b"1" * 24, b"2" * 40
    stream = e01 + e02
    parsed = TorrentInfo(
        name="Show.S01", piece_length=32, pieces=_pieces(stream, 32), is_multi_file=True, total_length=64,
        files=[TorrentFileEntry("Show.S01E01.mkv", 24, 0), TorrentFileEntry("Show.S01E02.mkv", 40, 24)],
    )
    (tmp_path / "e01.mkv").write_bytes(b"X" * 24)
    (tmp_path / "e02.mkv").write_bytes(e02)
    matches = [
        torrent_layout.FileMatch(
            layout_file=torrent_layout.LayoutFile(entry.path, entry.length, True),
            local=torrent_layout.LocalFile("media", i, 1, name, str(tmp_path / name), entry.length),
        )
        for i, (entry, name) in enumerate(zip(parsed.files, ("e01.mkv", "e02.mkv"), strict=True), start=1)
    ]

    evaluation = torrent_layout.evaluate(
        matches, torrent_layout.Layout(folder="Show.S01", files=[m.layout_file for m in matches], torrent=parsed),
        anchor_id=1, unique_ids=None, single_unique_id=None, compute_unique_id=lambda _: None,
        fetch_torrent=lambda: parsed,
    )

    e01_match = evaluation.files[0]
    assert e01_match.piece_verified is None and e01_match.confidence == torrent_layout.CONFIDENCE_SIZE_ONLY
    assert evaluation.confidence == torrent_layout.CONFIDENCE_SIZE_ONLY
    assert evaluation.piece_verified is None
