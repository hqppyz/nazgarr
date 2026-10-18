"""Nessuna dipendenza esterna per costruire un .torrent di test: un
encoder bencode minimale, solo per i test (l'app non ha mai bisogno di
codificare, solo di decodificare — vedi nazgarr/torrents/metainfo.py)."""

import hashlib

import pytest

from nazgarr.torrents.metainfo import (
    MAX_PIECE_LENGTH,
    TorrentMetainfoError,
    compute_info_hash,
    decode,
    parse_torrent_info,
)


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
        items = sorted(value.items(), key=lambda kv: kv[0] if isinstance(kv[0], bytes) else kv[0].encode())
        body = b"".join(_bencode(k) + _bencode(v) for k, v in items)
        return b"d" + body + b"e"
    raise TypeError(type(value))


def _piece_hashes(content: bytes, piece_length: int) -> bytes:
    return b"".join(
        hashlib.sha1(content[i : i + piece_length]).digest() for i in range(0, len(content), piece_length)
    )


def _single_file_torrent(content: bytes, piece_length: int = 16, name: str = "movie.mkv") -> bytes:
    info = {
        "name": name,
        "piece length": piece_length,
        "pieces": _piece_hashes(content, piece_length),
        "length": len(content),
    }
    return _bencode({"info": info, "announce": "https://tracker.example/announce"})


def _multi_file_torrent(files: dict[str, bytes], piece_length: int = 16, name: str = "Release.Name") -> bytes:
    concatenated = b"".join(files.values())
    info = {
        "name": name,
        "piece length": piece_length,
        "pieces": _piece_hashes(concatenated, piece_length),
        "files": [{"length": len(content), "path": [fname]} for fname, content in files.items()],
    }
    return _bencode({"info": info})


def test_decode_roundtrips_basic_types():
    assert decode(_bencode(42)) == 42
    assert decode(_bencode(b"hello")) == b"hello"
    assert decode(_bencode([1, 2, b"x"])) == [1, 2, b"x"]
    assert decode(_bencode({"a": 1, "b": b"y"})) == {b"a": 1, b"b": b"y"}


def test_decode_raises_on_malformed_input():
    with pytest.raises(TorrentMetainfoError):
        decode(b"not bencode")


def test_the_root_folder_is_the_name_of_a_multi_file_torrent_only():
    single = parse_torrent_info(_single_file_torrent(b"0123456789abcdef"))
    multi = parse_torrent_info(_multi_file_torrent({"a.mkv": b"0" * 16, "b.mkv": b"1" * 16}))
    assert (single.is_multi_file, multi.is_multi_file, multi.name) == (False, True, "Release.Name")


def test_compute_info_hash_is_deterministic_and_sensitive_to_content():
    t1 = _single_file_torrent(b"0123456789abcdef")
    t2 = _single_file_torrent(b"0123456789abcdef")
    t3 = _single_file_torrent(b"fedcba9876543210")

    assert compute_info_hash(t1) == compute_info_hash(t2)
    assert compute_info_hash(t1) != compute_info_hash(t3)
    assert len(compute_info_hash(t1)) == 40  # sha1 hex digest


def test_parse_torrent_info_single_file():
    content = b"0123456789abcdef" * 3  # 48 byte, 3 piece esatte
    torrent_bytes = _single_file_torrent(content, piece_length=16)

    info = parse_torrent_info(torrent_bytes)

    assert info.name == "movie.mkv"
    assert info.piece_length == 16
    assert len(info.pieces) == 3
    assert info.is_multi_file is False
    assert info.total_length == 48
    assert info.files == [("movie.mkv", 48, 0)]


def test_parse_torrent_info_multi_file_computes_offsets():
    files = {"a.mkv": b"x" * 16, "b.mkv": b"y" * 32}
    torrent_bytes = _multi_file_torrent(files, piece_length=16)

    info = parse_torrent_info(torrent_bytes)

    assert info.is_multi_file is True
    assert info.total_length == 48
    assert info.files[0].path == "a.mkv" and info.files[0].offset == 0 and info.files[0].length == 16
    assert info.files[1].path == "b.mkv" and info.files[1].offset == 16 and info.files[1].length == 32


def test_parse_torrent_info_raises_on_missing_info_dict():
    with pytest.raises(TorrentMetainfoError):
        parse_torrent_info(_bencode({"announce": "x"}))


@pytest.mark.parametrize("name,parts", [
    ("Movie", [b"..", b"..", b"etc", b"passwd"]),
    ("Movie", [b"", b"mnt", b"disk1", b"private.mkv"]),
    ("Movie", [b"a/b", b"c.mkv"]),
    ("Movie", [b"ok\x00.mkv"]),
    ("..", [b"a.mkv"]),
    ("a/b/c", [b"a.mkv"]),
])
def test_a_torrent_with_paths_that_leave_its_folder_is_refused(name, parts):
    # Un .torrent arriva dal tracker, cioè da chiunque ci abbia caricato qualcosa.
    info = {b"name": name.encode(), b"piece length": 16384, b"pieces": b"\x00" * 20,
            b"files": [{b"length": 1, b"path": parts}]}
    with pytest.raises(TorrentMetainfoError, match="non sicura"):
        parse_torrent_info(_bencode({b"info": info}))


@pytest.mark.parametrize("data", [
    b"l" * 5000 + b"e" * 5000,           # nidificazione infinita
    b"dli1eei2ee",                        # una lista come chiave
    b"d4:name999:xe",                     # stringa più lunga del file
    b"i12",                               # intero senza fine
    b"",
])
def test_a_hostile_torrent_is_a_metainfo_error_never_a_crash(data):
    with pytest.raises(TorrentMetainfoError):
        decode(data)


def _info(overrides: dict) -> dict:
    """Un dizionario info valido (un file da 32 byte, due piece da 16), con
    i campi da sostituire per i casi ostili."""
    info = {b"name": b"Movie", b"piece length": 16, b"pieces": b"\x00" * 40,
            b"files": [{b"length": 32, b"path": [b"a.mkv"]}]}
    info.update(overrides)
    return {k: v for k, v in info.items() if v is not None}


@pytest.mark.parametrize("info", [
    _info({b"name": 7}),                                          # nome intero
    _info({b"name": [b"Movie"]}),                                 # nome lista
    _info({b"files": 3}),                                         # files intero
    _info({b"files": b"a.mkv"}),                                  # files stringa
    _info({b"files": [{b"length": 32, b"path": b"a.mkv"}]}),      # path stringa (si itera a interi)
    _info({b"files": [{b"length": 32, b"path": [1, 2]}]}),        # parti del path intere
    _info({b"files": [{b"length": 32, b"path": []}]}),            # path vuoto
    _info({b"files": [{b"length": -5, b"path": [b"a.mkv"]}, {b"length": 37, b"path": [b"b.mkv"]}]}),
    _info({b"files": None, b"length": -32}),                      # file singolo negativo
    _info({b"files": None, b"length": "32"}),                     # lunghezza stringa
    _info({b"piece length": 0}),
    _info({b"piece length": -16}),
    _info({b"piece length": b"16"}),
])
def test_type_confused_or_negative_fields_are_a_metainfo_error_never_a_crash(info):
    with pytest.raises(TorrentMetainfoError):
        parse_torrent_info(_bencode({b"info": info}))


def test_a_huge_piece_length_is_refused_before_anything_is_read():
    # Un piece della dimensione del file faceva leggere l'intero video in memoria.
    info = _info({b"piece length": MAX_PIECE_LENGTH * 2, b"pieces": b"\x00" * 20,
                    b"files": [{b"length": 3 * MAX_PIECE_LENGTH, b"path": [b"a.mkv"]}]})
    with pytest.raises(TorrentMetainfoError, match="piece length"):
        parse_torrent_info(_bencode({b"info": info}))


def test_the_largest_allowed_piece_length_still_parses():
    info = _info({b"piece length": MAX_PIECE_LENGTH, b"pieces": b"\x00" * 20,
                    b"files": [{b"length": MAX_PIECE_LENGTH, b"path": [b"a.mkv"]}]})
    assert parse_torrent_info(_bencode({b"info": info})).piece_length == MAX_PIECE_LENGTH


@pytest.mark.parametrize("hashes", [1, 3, 0])
def test_the_hash_count_must_cover_the_content_exactly(hashes):
    # Con un hash in meno il controllo completo dava il 100% senza leggere la coda.
    with pytest.raises(TorrentMetainfoError, match="hash"):
        parse_torrent_info(_bencode({b"info": _info({b"pieces": b"\x00" * 20 * hashes})}))


def test_a_last_piece_shorter_than_the_others_counts_as_one():
    content = b"x" * 33  # 16 + 16 + 1
    assert len(parse_torrent_info(_single_file_torrent(content, piece_length=16)).pieces) == 3


@pytest.mark.parametrize("data", [
    b"d4:infoi12x",                 # intero troncato dentro lo span di info
    b"d4:info",                     # finisce dopo la chiave
    b"d3:fooli1e",                  # lista mai chiusa prima di info
    b"de",                          # niente info
    b"x",
])
def test_compute_info_hash_on_a_broken_torrent_is_a_metainfo_error(data):
    with pytest.raises(TorrentMetainfoError):
        compute_info_hash(data)
