import httpx
import pytest

from app.adapters.tracker.base import Unit3dTrackerAdapter, UploadError, UploadFields


def _adapter(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://tracker.example")
    return Unit3dTrackerAdapter(base_url="https://tracker.example", api_token="tok123", http_client=client)


def _fields(**overrides):
    defaults = dict(
        name="Movie.2024.1080p.mkv", description="desc", mediainfo="General\n...",
        category_id=1, type_id=3, resolution_id=3, tmdb_id=157336,
    )
    defaults.update(overrides)
    return UploadFields(**defaults)


def _torrent_file(tmp_path):
    path = tmp_path / "x.torrent"
    path.write_bytes(b"d8:announce...e")
    return str(path)


def test_upload_torrent_returns_torrent_id_on_success(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/torrents/upload"
        assert request.headers["Authorization"] == "Bearer tok123"
        return httpx.Response(
            200, json={"success": True, "message": "ok", "data": "https://tracker.example/torrents/download/12345.abcde"}
        )

    adapter = _adapter(handler)
    torrent_id = adapter.upload_torrent(_fields(), _torrent_file(tmp_path))

    assert torrent_id == "12345"


def test_upload_torrent_sends_expected_form_fields(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"success": True, "data": "/torrents/download/1.x"})

    adapter = _adapter(handler)
    adapter.upload_torrent(_fields(season_number=2, episode_number=5, anonymous=True), _torrent_file(tmp_path))

    body = captured["body"]
    assert b'name="category_id"' in body
    assert b"\r\n1\r\n" in body  # category_id value
    assert b'name="season_number"' in body
    assert b'name="anonymous"' in body


def test_upload_torrent_raises_on_api_rejection(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "message": "duplicate torrent"})

    adapter = _adapter(handler)

    with pytest.raises(UploadError, match="duplicate torrent"):
        adapter.upload_torrent(_fields(), _torrent_file(tmp_path))


def test_upload_torrent_raises_on_unparseable_response(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": "not-a-url"})

    adapter = _adapter(handler)

    with pytest.raises(UploadError):
        adapter.upload_torrent(_fields(), _torrent_file(tmp_path))


def test_upload_torrent_raises_on_missing_local_file(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("non dovrebbe fare la richiesta se il .torrent locale manca")

    adapter = _adapter(handler)

    with pytest.raises(UploadError):
        adapter.upload_torrent(_fields(), str(tmp_path / "missing.torrent"))


def test_upload_torrent_sends_freeleech_internal_and_mal(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"success": True, "data": "/torrents/download/1.x"})

    adapter = _adapter(handler)
    adapter.upload_torrent(_fields(free=50, internal=True, mal_id=5114), _torrent_file(tmp_path))

    body = captured["body"]
    assert b'name="free"\r\n\r\n50\r\n' in body
    assert b'name="internal"\r\n\r\n1\r\n' in body
    assert b'name="mal"\r\n\r\n5114\r\n' in body
