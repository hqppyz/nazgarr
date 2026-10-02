from datetime import UTC, datetime

from nazgarr import settings_repo
from nazgarr.models import Disk, DiskTorrentClient, RunLog, TorrentClient, Tracker
from nazgarr.setup_status import setup_status


def _done(session):
    return {key: step["done"] for key, step in setup_status(session)["steps"].items()}


def test_a_fresh_instance_has_everything_to_do(db_session):
    status = setup_status(db_session)

    assert status["complete"] is False
    assert not any(_done(db_session).values())
    assert status["required"] == ["storage", "clients", "metadata", "trackers", "first_scan"]


def test_each_step_follows_the_real_configuration(db_session, tmp_path):
    disk = Disk(label="d", root_path=str(tmp_path), media_rel_path="media")
    client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add_all([disk, client])
    db_session.commit()
    # Un disco senza cartella torrent non basta; un client abilitato sì, anche
    # senza dischi collegati (vale per tutti, confrontando i percorsi).
    assert _done(db_session)["storage"] is False and _done(db_session)["clients"] is True
    client.enabled = False
    db_session.commit()
    assert _done(db_session)["clients"] is False
    client.enabled = True

    disk.torrents_rel_path = "torrents"
    db_session.add(DiskTorrentClient(disk_id=disk.id, torrent_client_id=client.id))
    db_session.add(Tracker(label="T", adapter_type="unit3d", base_url="https://t.example", api_token="x"))
    db_session.add(RunLog(run_type="manual", started_at=datetime.now(UTC), finished_at=datetime.now(UTC)))
    db_session.commit()
    settings_repo.set_setting(db_session, "tmdb_api_key", "k")

    done = _done(db_session)
    assert all(done[key] for key in ("storage", "clients", "metadata", "trackers", "first_scan"))
    assert done["upload"] is False and done["arr"] is False  # facoltativi
    assert setup_status(db_session)["complete"] is True


def test_the_endpoint_answers_after_login(client):
    body = client.get("/api/system/setup-status").json()
    assert body["complete"] is False and set(body["steps"]) >= {"storage", "first_scan", "upload"}


def test_the_media_folder_is_optional(db_session, tmp_path):
    # Solo torrent e upload: basta la cartella dei torrent.
    db_session.add(Disk(label="d", root_path=str(tmp_path), torrents_rel_path="torrents"))
    db_session.commit()

    assert _done(db_session)["storage"] is True
