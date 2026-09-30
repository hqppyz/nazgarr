import httpx

from app import tracker_icons

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


def _client(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        body, content_type = routes.get(str(request.url), (b"", "text/plain"))
        status = 200 if body else 404
        return httpx.Response(status, content=body, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_favicon_is_downloaded_once_and_cached(tmp_path):
    client = _client({"https://t.example/favicon.ico": (PNG, "image/png")})

    path = tracker_icons.fetch_icon(str(tmp_path), 1, "https://t.example", client)

    assert path.endswith("1.png")
    assert tracker_icons.fetch_icon(str(tmp_path), 1, "https://t.example", _client({})) == path


def test_icon_from_the_home_page_link_and_never_svg(tmp_path):
    html = '<link rel="icon" href="/logo.svg"><link rel="shortcut icon" href="/static/icon.png">'
    client = _client({
        "https://t.example": (html.encode(), "text/html"),
        "https://t.example/static/icon.png": (PNG, "image/png"),
        "https://t.example/logo.svg": (b"<svg/>", "image/svg+xml"),
    })

    assert tracker_icons.fetch_icon(str(tmp_path), 2, "https://t.example", client).endswith("2.png")


def test_no_icon_is_remembered_for_a_while_and_forgotten_on_url_change(tmp_path):
    assert tracker_icons.fetch_icon(str(tmp_path), 3, "https://t.example", _client({})) is None
    # Il segnaposto evita di riprovare subito, anche se ora il sito l'avrebbe.
    later = _client({"https://t.example/favicon.ico": (PNG, "image/png")})
    assert tracker_icons.fetch_icon(str(tmp_path), 3, "https://t.example", later) is None

    tracker_icons.forget_icon(str(tmp_path), 3)
    assert tracker_icons.fetch_icon(str(tmp_path), 3, "https://t.example", later) is not None


def test_oversized_or_non_image_responses_are_ignored(tmp_path):
    client = _client({"https://t.example/favicon.ico": (b"x" * (tracker_icons.MAX_BYTES + 1), "image/png")})
    assert tracker_icons.fetch_icon(str(tmp_path), 4, "https://t.example", client) is None
