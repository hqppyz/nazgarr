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


def test_adapters_of_the_same_tracker_share_rate_limit_and_search_cache():
    """Ogni operazione costruisce il suo adapter: con shared=True (quelli
    dell'app) il budget di richieste e la cache delle ricerche sono del
    tracker, non dell'adapter."""
    from nazgarr.adapters.tracker import base

    base.reset_shared_state()
    calls = []
    slept = []

    def handler(request):
        calls.append(request.url.params.get("tmdbId"))
        return httpx.Response(200, json={"data": []})

    try:
        first = _adapter(handler, rate_limit_per_min=2, shared=True, sleep=slept.append)
        second = _adapter(handler, rate_limit_per_min=2, shared=True, sleep=slept.append)
        first.search_by_tmdb(1)
        second.search_by_tmdb(1)  # dalla cache del tracker: nessuna richiesta
        second.search_by_tmdb(2)
        assert calls == ["1", "2"] and slept == []
        first.search_by_tmdb(3)  # terza richiesta del minuto sullo stesso tracker
        assert calls == ["1", "2", "3"] and len(slept) == 1 and 55 < slept[0] <= 60

        alone = _adapter(handler, rate_limit_per_min=2, sleep=slept.append)  # non condiviso (test)
        alone.search_by_tmdb(1)
        assert calls[-1] == "1" and len(slept) == 1
    finally:
        base.reset_shared_state()


def test_the_rate_limiter_never_lets_threads_exceed_the_limit_together():
    import threading

    from nazgarr.adapters.tracker.base import _RateLimiter

    limiter = _RateLimiter(5)
    waits = []
    lock = threading.Lock()

    def sleep(seconds):
        with lock:
            waits.append(seconds)

    threads = [threading.Thread(target=limiter.wait, args=(sleep,)) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(waits) == 3  # le prime 5 subito, le altre 3 aspettano la finestra


def _gzip_bomb_chunks(decoded_bytes: int, chunk: int = 1024):
    """Un corpo gzip di soli zeri che si espande a decoded_bytes, mandato a
    pezzi da `chunk` byte compressi, e quanti pezzi sono stati letti."""
    import zlib

    packer = zlib.compressobj(9, zlib.DEFLATED, 31)  # 31: formato gzip
    block = b"\0" * (1024 * 1024)
    raw = b"".join(packer.compress(block) for _ in range(decoded_bytes // len(block))) + packer.flush()
    sent = []

    def stream():
        for i in range(0, len(raw), chunk):
            sent.append(i)
            yield raw[i:i + chunk]

    return stream, sent, -(-len(raw) // chunk)


def test_a_gzip_bomb_torrent_is_refused_before_it_is_all_in_memory():
    # ~60 KB sul filo, 60 MB decompressi: prima il limite di 20 MB scattava
    # solo con tutto il corpo già decompresso in memoria.
    stream, sent, total_chunks = _gzip_bomb_chunks(60 * 1024 * 1024)
    adapter = _adapter(lambda r: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=stream()))

    with pytest.raises(UploadError, match="bigger than 20 MB"):
        adapter.download_torrent("https://tracker.example/torrent/download/1.abc")
    assert len(sent) < total_chunks / 2  # fermato poco oltre il limite, non a fine corpo


def _peak_bytes(call) -> int:
    """Il picco di memoria allocata (tracemalloc) mentre gira call()."""
    import tracemalloc

    tracemalloc.start()
    try:
        call()
    finally:
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return peak


def _refused(call):
    def run():
        with pytest.raises(UploadError) as info:
            call()
        run.message = str(info.value)
    return run


def test_a_gzip_bomb_in_network_sized_chunks_never_fills_the_memory():
    # httpx decomprime ogni blocco grezzo (fino a 64 KiB da httpcore) in una
    # sola chiamata: 60 MB di zeri stanno in un blocco solo, e si espandevano
    # tutti prima del primo conteggio. Ora si decomprime a passi limitati.
    stream, _, _ = _gzip_bomb_chunks(60 * 1024 * 1024, chunk=64 * 1024)
    adapter = _adapter(lambda r: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=stream()))

    run = _refused(lambda: adapter.download_torrent("https://tracker.example/torrent/download/1.abc"))
    assert _peak_bytes(run) < 2 * Unit3dTrackerAdapter.MAX_TORRENT_BYTES
    assert "bigger than 20 MB" in run.message


def _stacked_gzip(decoded_bytes: int) -> bytes:
    import zlib

    inner = zlib.compressobj(9, zlib.DEFLATED, 31)
    block = b"\0" * (1024 * 1024)
    once = b"".join(inner.compress(block) for _ in range(decoded_bytes // len(block))) + inner.flush()
    outer = zlib.compressobj(9, zlib.DEFLATED, 31)
    return outer.compress(once) + outer.flush()


def test_stacked_content_encodings_are_refused_before_any_decoding():
    # "gzip, gzip": httpx incatenava i decoder, e un paio di KB sul filo
    # diventavano GB in memoria (2,4 GB misurati con 1.827 byte) prima che il
    # tetto di 20 MB scattasse. Più di uno strato non si legge affatto.
    body = _stacked_gzip(64 * 1024 * 1024)
    assert len(body) < 4096
    adapter = _adapter(lambda r: httpx.Response(200, headers={"Content-Encoding": "gzip, gzip"}, content=iter([body])))

    run = _refused(lambda: adapter.download_torrent("https://tracker.example/torrent/download/1.abc"))
    assert _peak_bytes(run) < 2 * Unit3dTrackerAdapter.MAX_TORRENT_BYTES
    assert "unsupported Content-Encoding (gzip, gzip)" in run.message

    with pytest.raises(UploadError, match="unsupported Content-Encoding"):
        adapter.search_by_tmdb(1)
    split = _adapter(lambda r: httpx.Response(
        200, headers=[("Content-Encoding", "gzip"), ("Content-Encoding", "deflate")], content=iter([body])))
    with pytest.raises(UploadError, match="unsupported Content-Encoding"):
        split.search_by_tmdb(1)
    brotli = _adapter(lambda r: httpx.Response(200, headers={"Content-Encoding": "br"}, content=iter([b"x"])))
    with pytest.raises(UploadError, match="unsupported Content-Encoding"):
        brotli.download_torrent("https://tracker.example/torrent/download/1.abc")


def test_a_single_gzip_or_deflate_layer_is_still_read():
    import json
    import zlib

    payload = json.dumps({"data": []}).encode()

    def packed(wbits):
        packer = zlib.compressobj(6, zlib.DEFLATED, wbits)
        return packer.compress(payload) + packer.flush()

    seen = []
    for coding, wbits in (("gzip", 31), ("x-gzip", 31), ("deflate", 15), ("deflate", -15), ("identity", None)):
        body = payload if wbits is None else packed(wbits)
        chunks = [body[i:i + 3] for i in range(0, len(body), 3)]  # a pezzi, anche l'intestazione

        def handler(request, coding=coding, chunks=chunks):
            seen.append(request.headers.get("accept-encoding"))
            return httpx.Response(200, headers={"Content-Encoding": coding}, content=iter(chunks))

        assert list(_adapter(handler).search_by_tmdb(1)) == [], coding
    # Il server non riceve mai l'offerta di una codifica che qui non si legge.
    assert set(seen) == {"gzip, deflate"}

    broken = _adapter(lambda r: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=iter([b"not gzip"])))
    with pytest.raises(UploadError, match="cannot be decompressed"):
        broken.search_by_tmdb(1)


def test_a_declared_length_over_the_limit_is_refused_without_reading():
    read = []

    def body():
        read.append(1)
        yield b"d4:infod4:name1:xee"

    adapter = _adapter(lambda r: httpx.Response(
        200, headers={"Content-Length": str(Unit3dTrackerAdapter.MAX_TORRENT_BYTES + 1)}, content=body()))

    with pytest.raises(UploadError, match="bigger than 20 MB"):
        adapter.download_torrent("https://tracker.example/torrent/download/1.abc")
    assert read == []


def test_a_search_answer_over_the_limit_or_not_json_is_an_upload_error(monkeypatch):
    monkeypatch.setattr(Unit3dTrackerAdapter, "MAX_JSON_BYTES", 1000)
    big = _adapter(lambda r: httpx.Response(200, json={"data": [], "pad": "x" * 2000}))
    with pytest.raises(UploadError, match="bigger than 1000 bytes"):
        big.search_by_tmdb(1)

    html = _adapter(lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(UploadError, match="not valid JSON"):
        html.search_by_tmdb(1)

    odd = _adapter(lambda r: httpx.Response(200, json=[1, 2]))
    with pytest.raises(UploadError, match="Unexpected answer"):
        odd.search_by_tmdb(1)


def test_a_body_that_trickles_past_the_deadline_is_dropped(monkeypatch):
    # Il timeout di httpx vale per ogni lettura: un byte alla volta lo
    # rispettava per sempre. Qui la scadenza totale è già passata.
    import time

    monkeypatch.setattr(Unit3dTrackerAdapter, "_deadline", lambda self: time.monotonic() - 1)

    def trickle():
        for _ in range(100):
            yield b"x"

    adapter = _adapter(lambda r: httpx.Response(200, content=trickle()))
    with pytest.raises(UploadError, match="too slow"):
        adapter.download_torrent("https://tracker.example/torrent/download/1.abc")


def _page(ids, next_cursor=None, next_link=None):
    body = {"data": [_search_item(f"https://tracker.example/torrent/download/{i}.k") | {"id": str(i)} for i in ids]}
    body["meta"] = {"per_page": 100, "next_cursor": next_cursor}
    body["links"] = {"next": next_link}
    return body


def test_the_search_follows_every_page_of_the_catalogue():
    # Prima solo la prima pagina (25 torrent): i più vecchi non diventavano
    # mai candidati, e il controllo dei dupe poteva non vedere un doppione.
    from nazgarr.adapters.tracker.base import catalog_truncated

    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=_page([1, 2], "c2") if cursor is None else _page([3]))

    results = _adapter(handler).search_by_tmdb(7)

    assert [c.torrent_id_remote for c in results] == ["1", "2", "3"]
    assert seen == [{"tmdbId": "7", "perPage": "100"}, {"tmdbId": "7", "perPage": "100", "cursor": "c2"}]
    assert catalog_truncated(results) is False


def test_a_page_link_without_a_cursor_is_followed_by_its_parameters_only():
    seen = []

    def handler(request):
        seen.append((request.url.host, dict(request.url.params)))
        if "page" not in request.url.params:
            return httpx.Response(200, json=_page([1], next_link="https://elsewhere.example/api/torrents/filter?page=2"))
        return httpx.Response(200, json=_page([2]))

    results = _adapter(handler).search_by_tmdb(7)

    assert [c.torrent_id_remote for c in results] == ["1", "2"]
    assert seen[1] == ("tracker.example", {"tmdbId": "7", "perPage": "100", "page": "2"})  # mai l'altro host


def test_the_search_stops_at_the_page_cap_and_says_it_is_truncated(monkeypatch):
    from nazgarr.adapters.tracker.base import catalog_truncated

    monkeypatch.setattr(Unit3dTrackerAdapter, "MAX_SEARCH_PAGES", 3)
    calls = []

    def handler(request):
        calls.append(1)
        n = len(calls)
        return httpx.Response(200, json=_page([n], f"c{n + 1}"))

    adapter = _adapter(handler)
    results = adapter.search_by_tmdb(7)

    assert len(calls) == 3 and len(results) == 3
    assert catalog_truncated(results) is True
    assert catalog_truncated(adapter.search_by_tmdb(7)) is True  # anche dalla cache
    assert len(calls) == 3


def test_a_tracker_repeating_the_same_cursor_does_not_loop():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=_page([len(calls)], "same"))

    from nazgarr.adapters.tracker.base import catalog_truncated

    results = _adapter(handler).search_by_tmdb(7)
    # Le pagine dopo il cursore ripetuto non si sono mai lette: il catalogo
    # non è completo, e il controllo dei dupe deve poterlo dire.
    assert len(calls) == 2 and catalog_truncated(results) is True


def test_a_download_link_downgraded_to_http_or_another_scheme_is_not_followed():
    seen = []
    adapter = _adapter(lambda r: (seen.append(r), httpx.Response(200, content=b"d4:infod4:name1:xee"))[1])

    for link in ("http://tracker.example/torrent/download/1.key",   # la passkey in chiaro
                 "ftp://tracker.example/torrent/download/1.key"):
        with pytest.raises(UploadError, match="scheme"):
            adapter.download_torrent(link)
    assert seen == []


def test_a_tracker_name_that_now_resolves_to_the_cloud_metadata_is_not_called(monkeypatch):
    # Il base_url si controlla quando si salva; un DNS cambiato dopo restava
    # libero di portare le richieste (col token) a 169.254.169.254.
    import socket

    from nazgarr.core import net_guard

    def resolve(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", resolve)
    seen = []
    adapter = _adapter(lambda r: (seen.append(r), httpx.Response(200, json={"data": []}))[1])

    with pytest.raises(UploadError, match="refused"):
        adapter.search_by_tmdb(1)
    with pytest.raises(UploadError, match="refused"):
        adapter.download_torrent("https://dl.tracker.example/torrent/download/1.x")
    assert seen == []


def test_a_download_link_with_an_invalid_host_label_is_an_upload_error():
    # "x..tracker.example" passa la regola dell'host (finisce con
    # .tracker.example), ma getaddrinfo solleva un UnicodeError, non un
    # gaierror: usciva grezzo da download_torrent e fermava il matching.
    seen = []
    adapter = _adapter(lambda r: (seen.append(r), httpx.Response(200, content=b"d4:infod4:name1:xee"))[1])

    for link in ("https://x..tracker.example/torrent/download/1",
                 "https://" + "a" * 70 + ".tracker.example/torrent/download/1"):
        with pytest.raises(UploadError, match="Invalid host"):
            adapter.download_torrent(link)
    assert seen == []


@pytest.mark.parametrize("bad", [-30, -1, 0])
def test_a_rate_limit_below_one_still_lets_requests_through_one_per_minute(bad):
    """Audit 2026-10-18: con un rate limit negativo salvato sul tracker ogni
    wait() sollevava IndexError, e ogni ricerca di quel tracker falliva."""
    from nazgarr.adapters.tracker import base
    from nazgarr.adapters.tracker.base import _RateLimiter

    limiter = _RateLimiter(bad)
    waits = []
    limiter.wait(waits.append)
    limiter.wait(waits.append)
    assert limiter.max_per_min == 1 and len(waits) == 1  # la seconda aspetta la finestra

    try:
        shared = base._shared_limiter("https://neg.example", 30)
        assert base._shared_limiter("https://neg.example", bad) is shared and shared.max_per_min == 1
    finally:
        base.reset_shared_state()


def test_the_search_cache_drops_expired_searches_and_stays_bounded(monkeypatch):
    """Audit 2026-10-18, finding 130 (residuo): la cache delle ricerche
    controllava la scadenza solo in lettura e non toglieva mai niente, così
    teneva ogni titolo cercato su ogni tracker per tutta la vita del processo."""
    from nazgarr.adapters.tracker import base

    clock = [1000.0]
    monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
    cache = base.SearchCache(max_entries=3)
    cache.store(1, 600, ["a"])
    cache.store(2, 600, ["b"])
    clock[0] += 601
    cache.store(3, 600, ["c"])
    assert list(cache) == [3]  # le scadute escono a ogni scrittura

    cache.store(4, 600, ["d"])
    cache.store(5, 600, ["e"])
    assert cache.lookup(3, 600) == ["c"]  # la più vecchia, appena usata
    cache.store(6, 600, ["f"])
    assert list(cache) == [5, 3, 6]  # oltre il tetto esce quella usata meno di recente
    assert cache.lookup(4, 600) is None
    assert isinstance(cache, dict) and cache.pop(5, None) == (1601.0, 600, ["e"])  # upload/execute._forget_search


def test_the_search_cache_of_a_replaced_token_is_forgotten(monkeypatch):
    from nazgarr.adapters.tracker import base

    clock = [1000.0]
    monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
    base.reset_shared_state()

    def handler(request):
        return httpx.Response(200, json={"data": []})

    try:
        _adapter(handler, shared=True).search_by_tmdb(1)
        assert len(base._shared_search_caches) == 1
        clock[0] += 601
        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://tracker.example")
        replaced = base.Unit3dTrackerAdapter(base_url="https://tracker.example", api_token="new-token", shared=True,
                                             http_client=client)
        replaced.search_by_tmdb(1)
        assert len(base._shared_search_caches) == 1  # quella del vecchio token, scaduta, non c'è più
    finally:
        base.reset_shared_state()
