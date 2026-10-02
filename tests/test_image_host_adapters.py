import httpx
import pytest

from nazgarr.adapters.image_host.base import ImageHostError
from nazgarr.adapters.image_host.chain import ImageHostChain
from nazgarr.adapters.image_host.chevereto import chevereto_image_url
from nazgarr.adapters.image_host.dalexni import DalexniAdapter
from nazgarr.adapters.image_host.imgbb import ImgbbAdapter
from nazgarr.adapters.image_host.lensdump import LensdumpAdapter
from nazgarr.adapters.image_host.onlyimage import OnlyimageAdapter
from nazgarr.adapters.image_host.pixhost import PixhostAdapter
from nazgarr.adapters.image_host.ptpimg import PtpimgAdapter
from nazgarr.adapters.image_host.ptscreens import PtscreensAdapter
from nazgarr.adapters.image_host.seedpool_cdn import SeedpoolCdnAdapter
from nazgarr.adapters.image_host.utppm import UtppmAdapter


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ptpimg_upload_returns_public_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ptpimg.me"
        return httpx.Response(200, json=[{"code": "abc123", "ext": "png"}])

    adapter = PtpimgAdapter(api_key="key123", client=_client(handler))
    url = adapter.upload(str(image))

    assert url == "https://ptpimg.me/abc123.png"


def test_ptpimg_upload_raises_on_bad_response(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"unexpected": "shape"}])

    adapter = PtpimgAdapter(api_key="key123", client=_client(handler))

    with pytest.raises(ImageHostError):
        adapter.upload(str(image))


def test_ptpimg_upload_raises_on_http_error(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    adapter = PtpimgAdapter(api_key="key123", client=_client(handler))

    with pytest.raises(ImageHostError):
        adapter.upload(str(image))


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


def test_pixhost_upload_returns_public_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.pixhost.to"
        return httpx.Response(
            200,
            json={"show_url": "https://pixhost.to/show/1/x.png", "th_url": "https://t77.pixhost.to/thumbs/1/x.png"},
        )

    adapter = PixhostAdapter(client=_client(handler))
    url = adapter.upload(str(image))

    # L'immagine vera, non la pagina HTML di show_url.
    assert url == "https://img77.pixhost.to/images/1/x.png"


def test_pixhost_upload_raises_on_missing_show_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    adapter = PixhostAdapter(client=_client(handler))

    with pytest.raises(ImageHostError):
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


def test_lensdump_upload_returns_public_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "key123"
        return httpx.Response(200, json={"data": {"image": {"url": "https://lensdump.com/x.png"}}})

    adapter = LensdumpAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://lensdump.com/x.png"


def test_ptscreens_upload_returns_public_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "key123"
        return httpx.Response(200, json={"image": {"medium": {"url": "https://ptscreens.com/x.png"}}})

    adapter = PtscreensAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://ptscreens.com/x.png"


def test_onlyimage_upload_returns_public_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"image": {"url": "https://onlyimage.org/x.png"}})

    adapter = OnlyimageAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://onlyimage.org/x.png"


def test_utppm_upload_returns_public_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"image": {"url": "https://utp.pm/x.png"}}})

    adapter = UtppmAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://utp.pm/x.png"


def test_dalexni_upload_prefers_the_full_image(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": {
            "url": "https://dalexni.com/full.png", "medium": {"url": "https://dalexni.com/x.png"},
        }})

    adapter = DalexniAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://dalexni.com/full.png"


def test_dalexni_upload_returns_medium_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"success": True, "data": {"medium": {"url": "https://dalexni.com/x.png"}, "thumb": {"url": "t"}}}
        )

    adapter = DalexniAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://dalexni.com/x.png"


def test_dalexni_falls_back_to_thumb_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": {"thumb": {"url": "https://dalexni.com/t.png"}}})

    adapter = DalexniAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://dalexni.com/t.png"


def test_dalexni_raises_on_unsuccessful_response(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False})

    adapter = DalexniAdapter(api_key="key123", client=_client(handler))
    with pytest.raises(ImageHostError):
        adapter.upload(str(image))


def test_seedpool_cdn_upload_prefers_the_full_image(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer key123"
        return httpx.Response(
            200,
            json={"files": [{"url": "https://i.seedpool.org/full.png", "thumbnail_url": "https://i.seedpool.org/t.png"}]},
        )

    adapter = SeedpoolCdnAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://i.seedpool.org/full.png"


def test_seedpool_cdn_falls_back_to_base_url(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"files": [{"url": "https://i.seedpool.org/full.png"}]})

    adapter = SeedpoolCdnAdapter(api_key="key123", client=_client(handler))
    assert adapter.upload(str(image)) == "https://i.seedpool.org/full.png"
