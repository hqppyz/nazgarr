import os

from app import not_imported, pipeline, scanner, torrent_indexer
from app.adapters.torrent_client.base import ClientTorrentFileInfo, ClientTorrentInfo, TorrentClientAdapter
from app.arr import ArrIndex
from app.models import ClientTorrent, Disk, MediaFile, MediaItem, NotImportedTorrent, TorrentClient


class FakeAdapter(TorrentClientAdapter):
    def __init__(self, torrents):
        self._torrents = torrents

    def add_torrent(self, *args, **kwargs):
        raise NotImplementedError

    def get_torrent_status(self, *args, **kwargs):
        raise NotImplementedError

    def list_torrents(self):
        return self._torrents


def _setup(db_session, tmp_path):
    root = tmp_path / "disk"
    for folder in ("media/movies/New (2001)", "media/movies/Copy (2003)", "media/movies/The Movie (2001)",
                   "media/movies/Linked (2005)", "torrents"):
        (root / folder).mkdir(parents=True)
    disk = Disk(label="d", root_path=str(root), media_rel_path="media", torrents_rel_path="torrents")
    tc = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add_all([disk, tc])
    db_session.commit()

    (root / "media/movies/New (2001)/New.2160p.mkv").write_bytes(b"new remux" * 50)
    (root / "torrents/Old.1080p.mkv").write_bytes(b"old web-dl" * 40)  # sostituito da un upgrade
    (root / "media/movies/Copy (2003)/Copy.mkv").write_bytes(b"same bytes" * 30)
    (root / "torrents/Copy.mkv").write_bytes(b"same bytes" * 30)  # copia, inode diverso
    (root / "media/movies/The Movie (2001)/The.Movie.2001.2160p.mkv").write_bytes(b"x" * 900)
    (root / "torrents/The.Movie.2001.1080p.WEB-DL.mkv").write_bytes(b"y" * 800)  # solo dal nome
    (root / "torrents/Random.Thing.mkv").write_bytes(b"z" * 70)
    (root / "torrents/info.nfo").write_bytes(b"nfo")
    (root / "media/movies/Linked (2005)/Linked.mkv").write_bytes(b"linked" * 10)
    os.link(root / "media/movies/Linked (2005)/Linked.mkv", root / "torrents/Linked.mkv")

    run = pipeline.start_run(db_session, "manual")
    scanner.scan_disk(db_session, disk, run)
    for title, year, folder in (("New", 2001, "New (2001)"), ("Copy", 2003, "Copy (2003)"),
                                ("The Movie", 2001, "The Movie (2001)")):
        item = MediaItem(content_type="movie", tmdb_id=year * 10 + len(title), title=title, year=year)
        db_session.add(item)
        db_session.commit()
        for mf in db_session.query(MediaFile).filter(MediaFile.relative_path.like(f"media/movies/{folder}/%")):
            mf.media_item_id = item.id
    db_session.commit()

    def torrent(h, name):
        size = (root / "torrents" / name).stat().st_size
        return ClientTorrentInfo(info_hash=h, name=name, save_path=str(root / "torrents"), state="uploading",
                                 files=[ClientTorrentFileInfo(path_in_torrent=name, size_bytes=size)], ratio=2.5)

    torrent_indexer.index_torrent_client(db_session, tc, FakeAdapter([
        torrent("h-old", "Old.1080p.mkv"), torrent("h-copy", "Copy.mkv"),
        torrent("h-name", "The.Movie.2001.1080p.WEB-DL.mkv"), torrent("h-random", "Random.Thing.mkv"),
        torrent("h-nfo", "info.nfo"), torrent("h-linked", "Linked.mkv"),
    ]), run)
    new_item = db_session.query(MediaItem).filter_by(title="New").one()
    index = ArrIndex()
    old_size = (root / "torrents/Old.1080p.mkv").stat().st_size
    index.add_import("/downloads/torrents/Old.1080p.mkv", "/movies/New (2001)/Old.1080p.mkv", old_size,
                     ("movie", new_item.tmdb_id, None, None))
    return index


def _categories(db_session):
    return {
        db_session.get(ClientTorrent, row.client_torrent_id).info_hash: row
        for row in db_session.query(NotImportedTorrent).all()
    }


def test_each_not_imported_torrent_gets_its_reason(db_session, tmp_path):
    index = _setup(db_session, tmp_path)

    not_imported.classify_not_imported(db_session, index)

    rows = _categories(db_session)
    assert {h: r.category for h, r in rows.items()} == {
        "h-old": "superseded", "h-copy": "copy", "h-name": "superseded",
        "h-random": "never_imported", "h-nfo": "extras_only",
    }  # h-linked è importato (hardlink): non compare
    assert rows["h-old"].matched_by == "arr"
    assert rows["h-old"].replaced_by.relative_path.endswith("New.2160p.mkv")
    assert rows["h-name"].matched_by == "name"
    assert rows["h-copy"].matched_by == "hash"


def test_without_radarr_sonarr_upgrades_are_still_found_by_name(db_session, tmp_path):
    _setup(db_session, tmp_path)

    not_imported.classify_not_imported(db_session, None)

    rows = _categories(db_session)
    assert rows["h-name"].category == "superseded"
    assert rows["h-old"].category == "never_imported"  # "Old" non corrisponde a nessun titolo
    assert "not configured" in rows["h-random"].detail


def test_api_lists_torrents_with_their_replacement(db_session, tmp_path):
    from app.api.torrents import list_not_imported

    index = _setup(db_session, tmp_path)
    not_imported.classify_not_imported(db_session, index)

    body = list_not_imported(session=db_session)

    old = next(t for t in body.torrents if t.info_hash == "h-old")
    assert (old.category, old.title, old.ratio) == ("superseded", "New", 2.5)
    assert old.replaced_by.relative_path.endswith("New.2160p.mkv") and old.replaced_by.quality == "2160p"
    assert body.summary["superseded"].count == 2
    # Dove sta su disco: la sorgente per ripubblicarlo con un upload.
    assert (old.source.relative_path, old.source.is_dir) == ("torrents/Old.1080p.mkv", False)


def test_excluded_torrents_are_flagged_and_left_out_of_the_totals(db_session, tmp_path):
    from app import settings_repo
    from app.api.torrents import list_not_imported

    index = _setup(db_session, tmp_path)
    settings_repo.set_setting(db_session, "exclusion_patterns", "*Random*")
    not_imported.classify_not_imported(db_session, index)

    body = list_not_imported(session=db_session)
    random = next(t for t in body.torrents if t.info_hash == "h-random")
    # Esclusi: Random (pattern) e il torrent del solo info.nfo (preset di default *.nfo).
    assert random.excluded is True and body.excluded_count == 2
    assert "never_imported" not in body.summary  # l'unico never_imported era escluso
    assert body.classified and body.computed_at is not None and body.with_arr is True


def test_a_skipped_scan_is_reported_until_the_next_computation(db_session, tmp_path):
    from app.api.torrents import list_not_imported

    index = _setup(db_session, tmp_path)
    not_imported.mark_skipped(db_session, "a torrent client could not be indexed")
    assert list_not_imported(session=db_session).skipped_reason == "a torrent client could not be indexed"

    not_imported.classify_not_imported(db_session, index)
    assert list_not_imported(session=db_session).skipped_reason is None
