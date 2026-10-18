"""Il passo di migrazione che toglie la chiave personale del tracker dai
link dei dupe degli upload già salvati (audit 2026-10-18, finding 55)."""

import json

from sqlalchemy import text

from nazgarr.core import db, migrations

KEYED = "https://t.example/torrent/download/11.secretkey"


def _engine(tmp_path, dupes_by_target):
    engine = db.make_engine(str(tmp_path / "n.db"))
    migrations.upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO tracker (id, label, adapter_type, base_url, api_token)
                VALUES (1, 'T', 'unit3d', 'https://t.example', 'enc:x'),
                       (2, 'P', 'plugin', 'https://p.example', 'enc:y');
            """))
        conn.execute(text("INSERT INTO disk (id, label, root_path) VALUES (1, 'd', '/d')"))
        for target_id, (tracker_id, raw) in dupes_by_target.items():
            conn.execute(text("INSERT INTO upload_job (id, disk_id, relative_path, source_path, status) "
                              "VALUES (:id, 1, 'm.mkv', '/d/m.mkv', 'awaiting_decision')"), {"id": target_id})
            conn.execute(text("INSERT INTO upload_target (id, job_id, tracker_id, status, dupes_json) "
                              "VALUES (:id, :id, :tracker, 'awaiting_decision', :raw)"),
                         {"id": target_id, "tracker": tracker_id, "raw": raw})
    return engine


def _dupes(engine, target_id):
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT dupes_json FROM upload_target WHERE id = :id"), {"id": target_id}).scalar()
    return raw


def test_the_key_leaves_every_stored_dupe_link_of_a_unit3d_tracker(tmp_path):
    dupes = [
        {"torrent_id_remote": "11", "verdict": "identical", "download_link": KEYED,
         "verification": {"status": "passed", "info_hash": "ab"}},
        {"torrent_id_remote": "12", "verdict": "different", "download_link": "https://t.example/torrents/12"},
        {"torrent_id_remote": "13", "verdict": "different", "download_link": None},
    ]
    engine = _engine(tmp_path, {
        1: (1, json.dumps(dupes)),
        2: (2, json.dumps([{"torrent_id_remote": "11", "download_link": "https://p.example/torrent/download/11.k"}])),
        3: (1, "not json /torrent/download/1.x"),
    })

    assert migrations.strip_dupe_download_keys(engine) == {"stripped": 1}

    stored = json.loads(_dupes(engine, 1))
    assert "secretkey" not in _dupes(engine, 1)
    assert [d["download_link"] for d in stored] == [
        "https://t.example/torrent/download/11.rsskey", "https://t.example/torrents/12", None]
    assert stored[0]["verification"] == {"status": "passed", "info_hash": "ab"}  # il resto non si tocca
    assert "11.k" in _dupes(engine, 2)  # un plugin: non si saprebbe rimettere la chiave
    assert _dupes(engine, 3) == "not json /torrent/download/1.x"
    assert migrations.strip_dupe_download_keys(engine) == {"stripped": 0}  # idempotente
