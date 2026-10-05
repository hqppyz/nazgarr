import httpx
import pytest

from nazgarr.adapters.image_host.base import ImageHostError
from nazgarr.adapters.image_host.chain import ImageHostChain
from nazgarr.adapters.image_host.chevereto import CheveretoImageHost, chevereto_image_url
from nazgarr.bundled.image_hosts import ImgbbAdapter


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_imgbb_upload_returns_public_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.imgbb.com"
        return httpx.Response(200, json={"success": True, "data": {"image": {"url": "https://imgbb.com/x.png"}}})

    adapter = ImgbbAdapter(api_key="key123", client=_client(handler))
    url = adapter.upload(str(image))

    assert url == "https://imgbb.com/x.png"


def test_imgbb_upload_raises_on_failure_response(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error": {"message": "invalid key"}})

    adapter = ImgbbAdapter(api_key="bad", client=_client(handler))

    with pytest.raises(ImageHostError, match="invalid key"):
        adapter.upload(str(image))


class _FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.called = False

    def upload(self, image_path: str) -> str:
        self.called = True
        if self.error is not None:
            raise self.error
        return self.result


def test_chain_returns_first_successful_upload():
    first = _FakeAdapter(result="https://first.example/x.png")
    second = _FakeAdapter(result="https://second.example/x.png")
    chain = ImageHostChain([first, second])

    url = chain.upload("/tmp/x.png")

    assert url == "https://first.example/x.png"
    assert second.called is False


def test_chain_falls_back_to_next_on_failure():
    first = _FakeAdapter(error=ImageHostError("boom"))
    second = _FakeAdapter(result="https://second.example/x.png")
    chain = ImageHostChain([first, second])

    url = chain.upload("/tmp/x.png")

    assert url == "https://second.example/x.png"


def test_chain_raises_last_error_if_all_fail():
    first = _FakeAdapter(error=ImageHostError("first failed"))
    second = _FakeAdapter(error=ImageHostError("second failed"))
    chain = ImageHostChain([first, second])

    with pytest.raises(ImageHostError, match="second failed"):
        chain.upload("/tmp/x.png")


def test_chain_requires_at_least_one_adapter():
    with pytest.raises(ValueError):
        ImageHostChain([])


def test_chevereto_image_url_tries_multiple_shapes():
    assert chevereto_image_url({"data": {"image": {"medium": {"url": "a"}}}}) == "a"
    # L'originale vince sulla versione media.
    assert chevereto_image_url({"image": {"url": "full", "medium": {"url": "m"}}}) == "full"
    assert chevereto_image_url({"data": {"image": {"url": "b"}}}) == "b"
    assert chevereto_image_url({"image": {"medium": {"url": "c"}}}) == "c"
    assert chevereto_image_url({"image": {"url": "d"}}) == "d"
    assert chevereto_image_url({"data": {"medium": {"url": "e"}}}) == "e"
    assert chevereto_image_url({"data": {"url": "f"}}) == "f"
    assert chevereto_image_url({"nothing": "here"}) is None


def _image(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")
    return str(image)


def test_a_chevereto_host_sends_the_file_as_source_with_its_key(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://passtheima.ge/api/1/upload"
        assert request.headers["X-API-Key"] == "key123"
        assert b'name="source"; filename="shot.png"' in request.content
        return httpx.Response(200, json={"status_code": 200, "image": {"url": "https://passtheima.ge/i/x.png"}})

    host = CheveretoImageHost("key123", endpoint="https://passtheima.ge/api/1/upload", name="Passtheima",
                              client=_client(handler))

    assert host.upload(_image(tmp_path)) == "https://passtheima.ge/i/x.png"


def test_a_chevereto_error_carries_the_host_message(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"status_code": 400, "error": {"message": "Invalid API v1 key."}})

    host = CheveretoImageHost("bad", endpoint="https://www.imageride.net/api/1/upload", name="imageride",
                              client=_client(handler))

    with pytest.raises(ImageHostError, match="imageride.*Invalid API v1 key"):
        host.upload(_image(tmp_path))


def test_a_chevereto_answer_without_an_url_is_an_error(tmp_path):
    host = CheveretoImageHost("k", endpoint="https://ptscreens.com/api/1/upload", name="PTScreens",
                              client=_client(lambda request: httpx.Response(200, json={"status_code": 200})))

    with pytest.raises(ImageHostError, match="PTScreens"):
        host.upload(_image(tmp_path))
