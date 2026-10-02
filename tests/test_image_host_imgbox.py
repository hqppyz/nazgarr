import pytest

from nazgarr.adapters.image_host import imgbox as imgbox_module
from nazgarr.adapters.image_host.base import ImageHostError
from nazgarr.adapters.image_host.imgbox import ImgboxAdapter


class _FakeGallery:
    def __init__(self, submissions, **kwargs):
        self._submissions = submissions

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def add(self, filepaths):
        for submission in self._submissions:
            yield submission


def _patch_gallery(monkeypatch, submissions):
    monkeypatch.setattr(imgbox_module.pyimgbox, "Gallery", lambda **kwargs: _FakeGallery(submissions, **kwargs))


def test_imgbox_upload_returns_image_url(monkeypatch, tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")
    _patch_gallery(
        monkeypatch, [{"success": True, "error": None, "image_url": "https://imgbox.com/full/x.png"}]
    )

    url = ImgboxAdapter().upload(str(image))

    assert url == "https://imgbox.com/full/x.png"


def test_imgbox_upload_raises_on_submission_error(monkeypatch, tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")
    _patch_gallery(monkeypatch, [{"success": False, "error": "rejected", "image_url": None}])

    with pytest.raises(ImageHostError, match="rejected"):
        ImgboxAdapter().upload(str(image))


def test_imgbox_upload_raises_on_missing_image_url(monkeypatch, tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")
    _patch_gallery(monkeypatch, [{"success": True, "error": None, "image_url": None}])

    with pytest.raises(ImageHostError):
        ImgboxAdapter().upload(str(image))


def test_imgbox_upload_wraps_unexpected_exceptions(monkeypatch, tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake png bytes")

    def boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(imgbox_module.pyimgbox, "Gallery", boom)

    with pytest.raises(ImageHostError, match="network down"):
        ImgboxAdapter().upload(str(image))
