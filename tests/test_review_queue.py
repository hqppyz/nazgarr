"""La coda di revisione servita in blocco e a pagine (nazgarr/api/reviews.py,
audit 2026-10-18): le query non crescono con le review, e una pagina non
taglia mai a metà gli episodi di una stagione."""

from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import event

from nazgarr.api import reviews as api
from nazgarr.core.models import (
    Candidate,
    CandidateFile,
    ClientTorrent,
    ClientTorrentFile,
    Disk,
    MatchReview,
    MediaFile,
    MediaItem,
    SeedFile,
    TorrentClient,
    Tracker,
)
from nazgarr.reseed import pipeline


@contextmanager
def _counting(session):
    statements = []
    engine = session.get_bind()

    def count(*_args):
        statements.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", count)


class _Library:
    def __init__(self, session):
        self.session = session
        self.tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
        self.disk = Disk(label="d", root_path="/mnt/d")
        self.client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
        session.add_all([self.tracker, self.disk, self.client])
        session.commit()
        self.run = pipeline.start_run(session, "manual")
        self.n = 0

    def review(self, *, tmdb_id=None, season=None, episode=None, videos=1, seeding=False) -> MatchReview:
        s = self.session
        self.n += 1
        item = MediaItem(content_type="tv" if season else "movie", tmdb_id=tmdb_id or 10_000 + self.n,
                         season_number=season, episode_number=episode, title=f"Title {self.n}")
        s.add(item)
        s.commit()
        mf = MediaFile(disk_id=self.disk.id, relative_path=f"media/{self.n}.mkv", size_bytes=10, st_dev=1,
                       inode=self.n, media_item_id=item.id, last_scan_id=self.run.id, last_seen_at=datetime.now(UTC))
        s.add(mf)
        s.commit()
        candidate = Candidate(media_item_id=item.id, tracker_id=self.tracker.id, torrent_id_remote=str(self.n),
                              name=f"T{self.n}", size_bytes=10, source="catalog_search",
                              direction="media_to_torrent", confidence=0.5)
        candidate.files = [CandidateFile(torrent_path=f"{self.n}-{v}.mkv", size_bytes=10, is_video=True,
                                         media_file_id=mf.id if v == 0 else None) for v in range(videos)]
        s.add(candidate)
        s.commit()
        if seeding:  # in seed altrove: un cross-seed
            sf = SeedFile(disk_id=self.disk.id, relative_path=f"torrents/{self.n}.mkv", size_bytes=10, st_dev=1,
                          inode=self.n, last_scan_id=self.run.id, last_seen_at=datetime.now(UTC))
            ct = ClientTorrent(torrent_client_id=self.client.id, info_hash=f"h{self.n}", name="x", save_path="/x",
                               state="uploading", tracker_url="https://other.example",
                               last_polled_at=datetime.now(UTC))
            s.add_all([sf, ct])
            s.commit()
            s.add(ClientTorrentFile(client_torrent_id=ct.id, path_in_torrent="x.mkv", size_bytes=10,
                                    seed_file_id=sf.id, last_scan_id=self.run.id))
        row = MatchReview(candidate_id=candidate.id, media_file_id=mf.id, status="pending")
        s.add(row)
        s.commit()
        return row


def _queue_statements(session, library: _Library, count: int) -> int:
    for i in range(count):
        library.review(seeding=i % 2 == 0, videos=2 if i % 3 == 0 else 1)
    session.expire_all()
    with _counting(session) as statements:
        listed = api.list_reviews(session)
    assert len(listed) == session.query(MatchReview).count()
    return len(statements)


def test_the_queue_costs_the_same_queries_with_more_reviews(db_session):
    # Prima una quindicina di query per review (seeding_on con due GROUP BY
    # su tutta la libreria): 2000 review erano 30 mila query.
    library = _Library(db_session)
    few = _queue_statements(db_session, library, 3)
    many = _queue_statements(db_session, library, 30)
    assert many <= few + 2, (few, many)


def test_a_review_still_says_where_its_file_seeds(db_session):
    library = _Library(db_session)
    row = library.review(seeding=True)

    [response] = api.list_reviews(db_session)

    assert response.id == row.id and response.seeding_on == ["other.example"]
    assert response.torrent_client_id == library.client.id


def test_a_page_never_splits_the_episodes_of_a_season(db_session):
    library = _Library(db_session)
    movie = library.review()
    episodes = [library.review(tmdb_id=1399, season=1, episode=e) for e in (3, 1, 2)]
    other = library.review()

    first = api.review_queue(offset=0, limit=2, session=db_session)
    # La stagione comincia nella prima pagina: ci sta tutta, oltre il limite.
    assert [r.id for r in first.items] == [movie.id, episodes[1].id, episodes[2].id, episodes[0].id]
    assert (first.total, first.next_offset) == (5, 4)

    second = api.review_queue(offset=first.next_offset, limit=2, session=db_session)
    assert [r.id for r in second.items] == [other.id]
    assert second.next_offset is None


def test_the_full_list_follows_the_queue_order(db_session):
    library = _Library(db_session)
    first = library.review(tmdb_id=7, season=1, episode=2)
    movie = library.review()
    second = library.review(tmdb_id=7, season=1, episode=1)

    assert [r.id for r in api.list_reviews(db_session)] == [second.id, first.id, movie.id]
