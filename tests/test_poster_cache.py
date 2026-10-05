import os

import httpx

from nazgarr.library.poster_cache import download_poster


def test_downloads_and_caches_poster(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"fake-jpeg-bytes")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posters_dir = str(tmp_path / "posters")

    local_path = download_poster(posters_dir, "movie", 157336, "/interstellar.jpg", client=client)

    assert os.path.exists(local_path)
    assert local_path == os.path.join(posters_dir, "movie-157336.jpg")
    with open(local_path, "rb") as f:
        assert f.read() == b"fake-jpeg-bytes"
    assert len(calls) == 1
    assert calls[0].endswith("/t/p/w500/interstellar.jpg")


def test_does_not_redownload_if_already_cached(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"fake-jpeg-bytes")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posters_dir = str(tmp_path / "posters")

    download_poster(posters_dir, "movie", 157336, "/interstellar.jpg", client=client)
    download_poster(posters_dir, "movie", 157336, "/interstellar.jpg", client=client)

    assert len(calls) == 1
