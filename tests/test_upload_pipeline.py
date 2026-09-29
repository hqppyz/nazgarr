import json

import pytest

from app import upload, upload_profiles
from app.adapters.media_resolver.base import ResolvedMedia
from app.adapters.tracker.base import TorrentCandidate, UploadError
from app.models import Tracker
from app.upload import UploadPreparationError


class _FakeResolver:
    def __init__(self, resolved=None):
        self._resolved = resolved

    def resolve(self, file_path, content_type):
        return self._resolved


class _FakeImageHostChain:
    def __init__(self):
        self.uploaded = []

    def upload(self, image_path: str) -> str:
        self.uploaded.append(image_path)
        return f"https://img.example/{len(self.uploaded)}.png"


class _FakeTrackerAdapter:
    def __init__(self, candidates=None, torrent_id="999", error=None):
        self._candidates = candidates or []
        self._torrent_id = torrent_id
        self._error = error
        self.upload_calls = []

    def search_by_tmdb(self, tmdb_id):
        return self._candidates

    def upload_torrent(self, fields, torrent_path):
        self.upload_calls.append((fields, torrent_path))
        if self._error is not None:
            raise self._error
        return self._torrent_id


def _tracker(db_session, announce_url="https://tracker.example/announce"):
    t = Tracker(
        label="t", adapter_type="unit3d", base_url="https://tracker.example", api_token="x",
        announce_url=announce_url,
    )
    db_session.add(t)
    db_session.commit()
    return t


def _video(tmp_path):
    path = tmp_path / "Movie.2024.1080p.WEB.mkv"
    path.write_bytes(b"x" * 20000)
    return str(path)


def test_create_draft_resolves_content_when_resolver_available(db_session):
    tracker = _tracker(db_session)
    resolver = _FakeResolver(ResolvedMedia(tmdb_id=157336, content_type="movie"))

    job = upload.create_draft(db_session, "/media/Movie.2024.mkv", tracker, resolver)

    assert job.status == "draft"
    assert job.tmdb_id == 157336
    assert job.tracker_id == tracker.id


def test_create_draft_without_resolver_leaves_tmdb_id_none(db_session):
    tracker = _tracker(db_session)

    job = upload.create_draft(db_session, "/media/Movie.2024.mkv", tracker, resolver=None)

    assert job.tmdb_id is None


def test_prepare_creates_torrent_mediainfo_screenshots_and_description(db_session, tmp_path, monkeypatch):
    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)

    def _fake_generate_screenshots(video_path, output_dir, count=4, tonemap=False):
        return [str(tmp_path / "shot0.png"), str(tmp_path / "shot1.png")]

    monkeypatch.setattr(upload.screenshots, "generate_screenshots", _fake_generate_screenshots)
    for name in ("shot0.png", "shot1.png"):
        (tmp_path / name).write_bytes(b"fake png")
    image_host_chain = _FakeImageHostChain()

    result = upload.prepare(db_session, job, tracker, profile, image_host_chain, str(tmp_path / "data"))

    assert result.status == "ready"
    assert result.torrent_path and result.info_hash
    assert result.mediainfo_text is not None
    assert json.loads(result.screenshot_urls_json) == [
        "https://img.example/1.png", "https://img.example/2.png",
    ]
    assert "https://img.example/1.png" in result.description_rendered
    assert result.category_id == 1  # movie, dal profilo itt bundlato


def test_prepare_respects_screenshot_count_and_tonemap_settings(db_session, tmp_path, monkeypatch):
    from app import settings_repo

    settings_repo.set_setting(db_session, "upload_screenshot_count", "2")
    settings_repo.set_setting(db_session, "upload_tonemap_hdr", "true")

    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)

    calls = []

    def _fake_generate_screenshots(video_path, output_dir, count=4, tonemap=False):
        calls.append({"count": count, "tonemap": tonemap})
        return []

    monkeypatch.setattr(upload.screenshots, "generate_screenshots", _fake_generate_screenshots)

    upload.prepare(db_session, job, tracker, profile, _FakeImageHostChain(), str(tmp_path / "data"))

    assert calls == [{"count": 2, "tonemap": True}]


def test_prepare_prepends_description_header_when_configured(db_session, tmp_path, monkeypatch):
    from app import settings_repo

    settings_repo.set_setting(db_session, "upload_description_header", "[b]Encoded by me[/b]")

    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)
    monkeypatch.setattr(upload.screenshots, "generate_screenshots", lambda *a, **k: [])

    result = upload.prepare(db_session, job, tracker, profile, _FakeImageHostChain(), str(tmp_path / "data"))

    assert result.description_rendered.startswith("[b]Encoded by me[/b]\n\n")


def test_prepare_appends_signature_after_template(db_session, tmp_path, monkeypatch):
    from app import settings_repo

    settings_repo.set_setting(db_session, "upload_description_header", "HEADER")
    settings_repo.set_setting(db_session, "upload_description_signature", "[i]Uploaded with Nazgarr[/i]")

    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)
    monkeypatch.setattr(upload.screenshots, "generate_screenshots", lambda *a, **k: [])

    result = upload.prepare(db_session, job, tracker, profile, _FakeImageHostChain(), str(tmp_path / "data"))

    assert result.description_rendered.startswith("HEADER\n\n")
    assert result.description_rendered.endswith("\n\n[i]Uploaded with Nazgarr[/i]")


def test_prepare_raises_without_announce_url(db_session, tmp_path):
    tracker = _tracker(db_session, announce_url=None)
    profile = upload_profiles.create_upload_profile(db_session, tracker, "itt")
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)

    with pytest.raises(UploadPreparationError):
        upload.prepare(db_session, job, tracker, profile, _FakeImageHostChain(), str(tmp_path / "data"))


def test_dupe_check_delegates_to_tracker_adapter():
    candidate = TorrentCandidate(
        torrent_id_remote="1", info_hash=None, name="x", size_bytes=1, file_list=None, mediainfo_unique_id=None
    )
    adapter = _FakeTrackerAdapter(candidates=[candidate])

    result = upload.dupe_check(157336, adapter)

    assert result == [candidate]


def test_submit_requires_resolved_fields(db_session, tmp_path):
    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, None)
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)
    job.torrent_path = str(tmp_path / "x.torrent")
    db_session.commit()

    with pytest.raises(UploadPreparationError):
        upload.submit(db_session, job, _FakeTrackerAdapter(), profile)


def test_submit_success_marks_uploaded_with_torrent_id(db_session, tmp_path):
    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, None)
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)
    job.torrent_path = str(tmp_path / "x.torrent")
    job.category_id, job.type_id, job.resolution_id, job.tmdb_id = 1, 3, 3, 157336
    db_session.commit()
    adapter = _FakeTrackerAdapter(torrent_id="4242")

    result = upload.submit(db_session, job, adapter, profile)

    assert result.status == "uploaded"
    assert result.torrent_id_remote == "4242"
    assert len(adapter.upload_calls) == 1


def test_submit_forwards_profile_anonymous_and_personal_release_flags(db_session, tmp_path):
    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, None)
    profile.default_anonymous = True
    profile.default_personal_release = True
    db_session.commit()
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)
    job.torrent_path = str(tmp_path / "x.torrent")
    job.category_id, job.type_id, job.resolution_id, job.tmdb_id = 1, 3, 3, 157336
    db_session.commit()
    adapter = _FakeTrackerAdapter(torrent_id="4242")

    upload.submit(db_session, job, adapter, profile)

    fields = adapter.upload_calls[0][0]
    assert fields.anonymous is True
    assert fields.personal_release is True


def test_submit_failure_marks_failed_and_reraises(db_session, tmp_path):
    tracker = _tracker(db_session)
    profile = upload_profiles.create_upload_profile(db_session, tracker, None)
    job = upload.create_draft(db_session, _video(tmp_path), tracker, resolver=None)
    job.torrent_path = str(tmp_path / "x.torrent")
    job.category_id, job.type_id, job.resolution_id, job.tmdb_id = 1, 3, 3, 157336
    db_session.commit()
    adapter = _FakeTrackerAdapter(error=UploadError("tracker rifiuta"))

    with pytest.raises(UploadError):
        upload.submit(db_session, job, adapter, profile)

    assert job.status == "failed"
    assert job.error_message == "tracker rifiuta"
