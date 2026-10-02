import httpx
import pytest

from nazgarr.adapters.tracker.base import (
    NotSupportedError,
    TrackerRateLimitedError,
    Unit3dTrackerAdapter,
    UploadError,
)


def _adapter(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://tracker.example")
    return Unit3dTrackerAdapter(base_url="https://tracker.example", api_token="tok123", http_client=client, **kwargs)


def test_search_by_tmdb_parses_single_file_candidate():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["tmdbId"] == "157336"
        assert request.headers["Authorization"] == "Bearer tok123"
        return httpx.Response(200, json={
            "data": [{
                "type": "torrent", "id": "42",
                "attributes": {
                    "name": "Interstellar.2014.2160p.UHD.BluRay.mkv",
                    "size": 123456789,
                    "files": [{"name": "Interstellar.2014.2160p.UHD.BluRay.mkv", "size": 123456789}],
                    "media_info": "General\nUnique ID                               : 12345 (0x3039)\n",
                    "folder": None,
                    "download_link": "https://tracker.example/download/42",
                },
            }],
        })

    adapter = _adapter(handler)
    candidates = adapter.search_by_tmdb(157336)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.torrent_id_remote == "42"
    assert c.info_hash is None  # mai esposto da UNIT3D
    assert c.size_bytes == 123456789
    assert c.mediainfo_unique_id == "12345"
    assert c.download_link == "https://tracker.example/download/42"


def test_search_by_tmdb_caches_results(monkeypatch):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"data": []})

    adapter = _adapter(handler, cache_ttl_seconds=600)
    adapter.search_by_tmdb(1)
    adapter.search_by_tmdb(1)

    assert call_count == 1


def test_embedded_folder_stripped_from_pack_filenames():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{
                "type": "torrent", "id": "43",
                "attributes": {
                    "name": "Show.S01",
                    "size": 999,
                    "files": [
                        {"name": "Release.Name/Show.S01E01.mkv", "size": 100},
                        {"name": "Release.Name/Show.S01E02.mkv", "size": 200},
                    ],
                    "media_info": None,
                    "folder": None,
                    "download_link": "https://tracker.example/download/43",
                },
            }],
        })

    adapter = _adapter(handler)
    candidate = adapter.search_by_tmdb(1)[0]

    assert candidate.folder == "Release.Name"
    assert candidate.file_list == ["Show.S01E01.mkv", "Show.S01E02.mkv"]
    assert candidate.file_sizes == {"Show.S01E01.mkv": 100, "Show.S01E02.mkv": 200}


def test_extract_unique_ids_by_filename_for_a_pack():
    media_info = (
        "General\nComplete name                            : Release/Show.S01E01.mkv\n"
        "Unique ID                               : 111 (0x6f)\n"
        "General\nComplete name                            : Release/Show.S01E02.mkv\n"
        "Unique ID                               : 222 (0xde)\n"
    )
    result = Unit3dTrackerAdapter._extract_unique_ids_by_filename(media_info)

    assert result == {"Show.S01E01.mkv": "111", "Show.S01E02.mkv": "222"}


def test_get_own_history_raises_not_supported():
    adapter = _adapter(lambda request: httpx.Response(200, json={}))
    with pytest.raises(NotSupportedError):
        adapter.get_own_history()


def test_raises_on_http_error():
    handler = lambda request: httpx.Response(401, json={})  # noqa: E731
    adapter = _adapter(handler)

    with pytest.raises(UploadError):
        adapter.search_by_tmdb(1)


def test_429_waits_retry_after_then_succeeds():
    responses = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"data": []})]
    slept: list[float] = []
    adapter = _adapter(lambda request: responses.pop(0), sleep=slept.append)

    assert adapter.search_by_tmdb(1) == []
    assert slept == [7.0]


def test_429_without_retry_after_backs_off_exponentially_then_gives_up():
    slept: list[float] = []
    adapter = _adapter(lambda request: httpx.Response(429), sleep=slept.append)

    with pytest.raises(TrackerRateLimitedError):
        adapter.search_by_tmdb(1)
    assert slept == [5.0, 10.0, 20.0]


def test_retry_after_is_capped():
    responses = [httpx.Response(429, headers={"Retry-After": "3600"}), httpx.Response(200, json={"data": []})]
    slept: list[float] = []
    adapter = _adapter(lambda request: responses.pop(0), sleep=slept.append)

    adapter.search_by_tmdb(1)
    assert slept == [Unit3dTrackerAdapter._MAX_RETRY_WAIT_SECONDS]


def test_rate_limited_error_is_still_an_upload_error():
    # Il flusso di upload intercetta UploadError come un 502 pulito.
    assert issubclass(TrackerRateLimitedError, UploadError)


def test_download_torrent_goes_through_the_adapter_without_bearer_token():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"d4:infod4:name1:xee")

    adapter = _adapter(handler)
    content = adapter.download_torrent("https://tracker.example/torrent/download/1.abc")

    assert content == b"d4:infod4:name1:xee"
    assert "authorization" not in seen[0].headers


def test_redirect_to_login_is_a_clear_error():
    adapter = _adapter(lambda r: httpx.Response(302, headers={"location": "https://tracker.example/login"}))

    with pytest.raises(UploadError, match="no longer valid"):
        adapter.download_torrent("https://tracker.example/torrent/download/1.oldkey")


def _search_item(download_link):
    return {"type": "torrent", "id": "5", "attributes": {
        "name": "x", "size": 1, "files": [], "download_link": download_link,
    }}


def test_rss_key_is_learned_from_api_download_links_and_used_to_rewrite_old_links():
    adapter = _adapter(lambda r: httpx.Response(
        200, json={"data": [_search_item("https://tracker.example/torrent/download/5.newkey123")]}
    ))
    assert adapter.rewrite_download_link("https://tracker.example/torrent/download/9.oldkey") == (
        "https://tracker.example/torrent/download/9.oldkey"  # chiave ancora ignota: invariato
    )

    adapter.search_by_tmdb(1)

    assert adapter.rss_key == "newkey123"
    assert adapter.rewrite_download_link("https://tracker.example/torrent/download/9.oldkey") == (
        "https://tracker.example/torrent/download/9.newkey123"
    )
    # Mai un link di un altro tracker, né un URL con un'altra forma.
    assert adapter.rewrite_download_link("https://other.example/torrent/download/9.k") == (
        "https://other.example/torrent/download/9.k"
    )
    assert adapter.rewrite_download_link("https://tracker.example/torrents/9") == "https://tracker.example/torrents/9"


def test_a_configured_rss_key_is_used_before_any_api_call():
    adapter = _adapter(lambda r: httpx.Response(500), rss_key="manualkey")
    assert adapter.rewrite_download_link("https://tracker.example/torrent/download/9.old") == (
        "https://tracker.example/torrent/download/9.manualkey"
    )


def test_a_download_link_to_another_host_is_not_followed():
    seen = []
    adapter = _adapter(lambda r: (seen.append(r), httpx.Response(200, content=b"d4:infod4:name1:xee"))[1])

    with pytest.raises(UploadError, match="outside the tracker"):
        adapter.download_torrent("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(UploadError, match="outside the tracker"):
        adapter.download_torrent("https://evil.example/torrent/download/1.x")
    assert seen == []
    # Un sottodominio del tracker va bene (CDN dei download).
    assert adapter.download_torrent("https://dl.tracker.example/torrent/download/1.x")
