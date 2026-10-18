"""Le ricerche mirate ("Cerca ora" dalla scheda, la ricerca dopo un import
dei webhook) costruiscono gli indici dei file locali una volta per tutti i
tracker, e solo per i dischi dei file cercati (audit 2026-10-18, finding 34):
prima li ricostruiva ogni tracker."""

from datetime import UTC, datetime

import pytest

from nazgarr.core.models import RunLog, Tracker
from nazgarr.integrations import adapter_factory
from nazgarr.torrents.layout import LocalFiles
from tests.test_season_pack import PackTracker, _library, _no_mediainfo, _pack_candidate


@pytest.fixture
def two_trackers(db_session, tmp_path, monkeypatch):
    """La stagione di test_season_pack su due tracker che rispondono col pack,
    e le letture degli indici dei file locali."""
    _no_mediainfo(monkeypatch)
    disk, _tracker, files = _library(db_session, tmp_path)
    db_session.add(Tracker(label="t2", adapter_type="unit3d", base_url="https://t2.example", api_token="x"))
    for run in db_session.query(RunLog):  # la scansione che ha messo i file in libreria è finita
        run.finished_at = datetime.now(UTC)
    db_session.commit()
    loads = []
    original = LocalFiles.load.__func__
    monkeypatch.setattr(LocalFiles, "load", classmethod(lambda cls, s, disk_ids=None: (
        loads.append(disk_ids), original(cls, s, disk_ids))[1]))
    adapters = []
    monkeypatch.setattr(adapter_factory, "build_tracker_adapter",
                        lambda row: adapters.append(PackTracker([_pack_candidate()])) or adapters[-1])
    return disk, files, loads, adapters


def test_search_now_builds_the_local_indexes_once_for_every_tracker(db_session, two_trackers):
    from nazgarr.api import library as api

    disk, _files, loads, adapters = two_trackers

    result = api.search_item_now("tv", 1399, db_session)

    assert len(adapters) == 2 and all(a.searches for a in adapters)
    assert result.candidates >= 2
    assert loads == [{disk.id}]


def test_the_search_after_an_import_builds_them_once_too(db_session, two_trackers):
    from nazgarr.integrations import arr_webhooks

    disk, files, loads, adapters = two_trackers

    arr_webhooks._search(db_session, [mf.id for mf in files])

    assert len(adapters) == 2 and all(a.searches for a in adapters)
    assert loads == [{disk.id}]
