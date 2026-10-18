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
    assert calls[0].endswith("/t/p/w342/interstellar.jpg")  # nessuna vista lo mostra più largo di ~200 px


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


def test_an_oversized_or_interrupted_download_leaves_no_poster_behind(tmp_path, monkeypatch):
    """Letto con un tetto (audit 2026-10-18), e scritto solo a download
    finito: un file troncato non si riscaricava mai più."""
    import pytest

    from nazgarr.library import poster_cache

    from tests.http_helpers import chunked

    monkeypatch.setattr(poster_cache, "MAX_POSTER_BYTES", 100)
    # A pezzi, come dalla rete: un corpo dato coi byte httpx lo legge tutto da sé.
    stream, sent, total = chunked(b"x" * 1000, 40)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=stream())))
    posters_dir = str(tmp_path / "posters")

    with pytest.raises(httpx.HTTPError, match="bigger than 100 bytes"):
        download_poster(posters_dir, "movie", 1, "/big.jpg", client=client)
    assert os.listdir(posters_dir) == []
    assert len(sent) == 3 < total  # fermato appena passato il tetto, non a fine corpo

    def broken(request):
        raise httpx.ReadError("connection reset")

    with pytest.raises(httpx.ReadError):
        download_poster(posters_dir, "movie", 1, "/x.jpg", client=httpx.Client(transport=httpx.MockTransport(broken)))
    assert os.listdir(posters_dir) == []
