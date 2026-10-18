"""Il passo di migrazione che toglie i candidati doppi lasciati dalle
ricerche di prima e la chiave dai link di download (audit 2026-10-18)."""

from sqlalchemy import text

from nazgarr.core import db, migrations


def _engine(tmp_path):
    engine = db.make_engine(str(tmp_path / "n.db"))
    migrations.upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO tracker (id, label, adapter_type, base_url, api_token)
                VALUES (1, 'T', 'unit3d', 'https://t.example', 'enc:x'),
                       (2, 'P', 'plugin', 'https://p.example', 'enc:y');
            """))
        conn.execute(text("INSERT INTO media_item (id, content_type, tmdb_id) VALUES (1, 'movie', 603)"))
        conn.execute(text("INSERT INTO disk (id, label, root_path) VALUES (1, 'd', '/d')"))
        conn.execute(text("INSERT INTO run_log (id, run_type, started_at) VALUES (1, 'manual', '2026-10-01')"))
        conn.execute(text("""
            INSERT INTO media_file (id, disk_id, relative_path, size_bytes, st_dev, inode, media_item_id,
                                    last_scan_id, last_seen_at)
                VALUES (1, 1, 'm.mkv', 1, 1, 1, 1, 1, '2026-10-01')"""))
        rows = [
            # tre ricerche dello stesso torrent: resta la più recente
            (1, 1, "11", 0.0, "https://t.example/torrent/download/11.secretkey"),
            (2, 1, "11", 0.0, "https://t.example/torrent/download/11.secretkey"),
            (3, 1, "11", 0.0, "https://t.example/torrent/download/11.secretkey"),
            # una review e un seed_job le tengono, anche se più vecchie
            (4, 1, "12", 0.9, None), (5, 1, "12", 0.9, None), (6, 1, "12", 0.9, None),
            # un altro tracker, un altro torrent: niente doppi
            (7, 2, "11", 0.0, "https://p.example/torrent/download/11.pluginkey"),
        ]
        for cid, tracker, remote, confidence, link in rows:
            conn.execute(text(
                "INSERT INTO candidate (id, media_item_id, tracker_id, torrent_id_remote, name, size_bytes, "
                "source, direction, confidence, download_link) VALUES "
                "(:id, 1, :tracker, :remote, 'x', 1, 'catalog_search', 'media_to_torrent', :confidence, :link)"),
                {"id": cid, "tracker": tracker, "remote": remote, "confidence": confidence, "link": link})
            conn.execute(text("INSERT INTO candidate_file (candidate_id, torrent_path, is_video, media_file_id) "
                              "VALUES (:id, 'm.mkv', 1, 1)"), {"id": cid})
        conn.execute(text("INSERT INTO match_review (id, candidate_id, media_file_id, status) "
                          "VALUES (1, 4, 1, 'rejected')"))
        conn.execute(text("INSERT INTO seed_job (id, candidate_id, source_media_file_id, final_status) "
                          "VALUES (1, 5, 1, 'failed')"))
    return engine


def test_duplicates_go_and_rows_in_use_stay(tmp_path):
    engine = _engine(tmp_path)

    assert migrations.clean_stale_candidates(engine) == {"removed": 2, "stripped": 1}

    with engine.connect() as conn:
        assert [r[0] for r in conn.execute(text("SELECT id FROM candidate ORDER BY id"))] == [3, 4, 5, 6, 7]
        files = {r[0] for r in conn.execute(text("SELECT candidate_id FROM candidate_file"))}
        assert files == {3, 4, 5, 6, 7}
        links = dict(conn.execute(text(
            "SELECT id, download_link FROM candidate WHERE download_link IS NOT NULL")).all())
    assert links[3] == "https://t.example/torrent/download/11.rsskey"
    assert links[7].endswith("11.pluginkey")  # un plugin: la chiave non si sa rimettere

    assert migrations.clean_stale_candidates(engine) == {"removed": 0, "stripped": 0}  # idempotente
