from datetime import UTC, datetime

from nazgarr.core.models import Candidate, MatchReview, MediaFile, MediaItem, SeedJob, Tracker
from nazgarr.reseed import pipeline, review


def _tracker(db_session):
    t = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    db_session.add(t)
    db_session.commit()
    return t


def _candidate(db_session, item, tracker, *, confidence, direction="media_to_torrent"):
    c = Candidate(
        media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x", size_bytes=1,
        source="catalog_search", direction=direction, confidence=confidence,
    )
    db_session.add(c)
    db_session.commit()
    return c


def _media_item(db_session):
    item = MediaItem(content_type="movie", tmdb_id=1)
    db_session.add(item)
    db_session.commit()
    return item


def _media_file_stub(db_session, item):
    # I test di review.py non toccano il filesystem: bastano id validi via FK,
    # non serve un Disk reale per la sola logica di classificazione.
    from nazgarr.core.models import Disk

    disk = Disk(label="d", root_path="/mnt/d")
    db_session.add(disk)
    db_session.commit()
    run = pipeline.start_run(db_session, "manual")
    mf = MediaFile(
        disk_id=disk.id, relative_path="movies/x.mkv", size_bytes=1,
        st_dev=1, inode=1, media_item_id=item.id, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(mf)
    db_session.commit()
    return mf


def _seed_file_stub(db_session, media_file):
    from nazgarr.core.models import SeedFile

    run = pipeline.start_run(db_session, "manual")
    sf = SeedFile(
        disk_id=media_file.disk_id, relative_path="torrents/x.mkv", size_bytes=1,
        st_dev=1, inode=2, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(sf)
    db_session.commit()
    return sf


def test_high_confidence_creates_auto_approved_review(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    candidate = _candidate(db_session, item, tracker, confidence=0.99)

    result = review.create_review_for_media_file(db_session, mf, [candidate])

    assert result.status == "auto_approved"
    assert result.decided_by == "system"


def test_low_confidence_creates_pending_review(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    candidate = _candidate(db_session, item, tracker, confidence=0.5)

    result = review.create_review_for_media_file(db_session, mf, [candidate])

    assert result.status == "pending"
    assert result.decided_by is None


def test_torrent_to_client_uses_higher_threshold(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    sf = _seed_file_stub(db_session, mf)
    # 0.97 supera la soglia media_to_torrent (0.95) ma non quella
    # torrent_to_client (0.98 di default) — deve restare pending.
    candidate = _candidate(db_session, item, tracker, confidence=0.97, direction="torrent_to_client")

    result = review._create_review(db_session, [candidate], media_file_id=None, seed_file_id=sf.id)

    assert result.status == "pending"


def test_zero_confidence_candidates_produce_no_review(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    candidate = _candidate(db_session, item, tracker, confidence=0.0)

    result = review.create_review_for_media_file(db_session, mf, [candidate])

    assert result is None
    assert db_session.query(MatchReview).count() == 0


def test_rematching_supersedes_previous_active_review(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    first = _candidate(db_session, item, tracker, confidence=0.5)
    review.create_review_for_media_file(db_session, mf, [first])

    second = _candidate(db_session, item, tracker, confidence=0.99)
    new_review = review.create_review_for_media_file(db_session, mf, [second])

    reviews = db_session.query(MatchReview).order_by(MatchReview.id).all()
    assert len(reviews) == 2
    assert reviews[0].status == "rejected"
    assert reviews[0].decided_by == "system"
    assert new_review.status == "auto_approved"


def test_custom_threshold_from_settings(db_session):
    from nazgarr.core import settings_repo

    settings_repo.set_setting(db_session, "confidence_threshold_auto_media_to_torrent", "0.5")
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    candidate = _candidate(db_session, item, tracker, confidence=0.5)

    result = review.create_review_for_media_file(db_session, mf, [candidate])

    assert result.status == "auto_approved"


def test_approve_without_torrent_client_leaves_review_approved_no_seed_job(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    candidate = _candidate(db_session, item, tracker, confidence=0.99)
    match_review = MatchReview(candidate_id=candidate.id, status="pending")
    db_session.add(match_review)
    db_session.commit()

    review.approve(db_session, match_review)

    assert match_review.status == "approved"
    assert db_session.query(SeedJob).count() == 0  # nessun client configurato: esecuzione rimandata


def test_reject_marks_review_rejected(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    candidate = _candidate(db_session, item, tracker, confidence=0.5)
    match_review = MatchReview(candidate_id=candidate.id, status="pending")
    db_session.add(match_review)
    db_session.commit()

    review.reject(db_session, match_review)

    assert match_review.status == "rejected"
    assert match_review.decided_by == "user"


def test_list_ready_for_review_excludes_reviews_with_seed_job(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    candidate = _candidate(db_session, item, tracker, confidence=0.99)
    match_review = MatchReview(candidate_id=candidate.id, status="auto_approved")
    db_session.add(match_review)
    db_session.commit()
    seed_job = SeedJob(candidate_id=candidate.id, final_status="in_progress")
    db_session.add(seed_job)
    db_session.commit()

    assert review.list_ready_for_review(db_session) == []


def _review_for(db_session, candidate, **file_ids):
    r = MatchReview(candidate_id=candidate.id, status="pending", **file_ids)
    db_session.add(r)
    db_session.commit()
    return r


def test_queue_is_cleaned_of_files_that_no_longer_need_anything(db_session):
    from nazgarr.core.models import ClientTorrent, ClientTorrentFile, TorrentClient

    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    sf = _seed_file_stub(db_session, mf)
    still_orphan_mf = MediaFile(
        disk_id=mf.disk_id, relative_path="movies/y.mkv", size_bytes=1, st_dev=1, inode=5,
        media_item_id=item.id, last_scan_id=mf.last_scan_id, last_seen_at=datetime.now(UTC),
    )
    db_session.add(still_orphan_mf)
    db_session.commit()
    c = _candidate(db_session, item, tracker, confidence=0.5)
    c2 = _candidate(db_session, item, tracker, confidence=0.5, direction="torrent_to_client")
    m2t_open = _review_for(db_session, c, media_file_id=still_orphan_mf.id)
    m2t_linked = _review_for(db_session, c, media_file_id=mf.id)
    t2c_tracked = _review_for(db_session, c2, seed_file_id=sf.id)

    # mf ha ora un hardlink (sf.media_file_id), sf è ora tracciato da un client.
    sf.media_file_id = mf.id
    client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add(client)
    db_session.commit()
    # In seed sul tracker della review (il suo announce): con i cross-seed la
    # review si chiude solo quando il file seeda su QUEL tracker.
    ct = ClientTorrent(torrent_client_id=client.id, info_hash="h", name="x", save_path="/x", state="uploading",
                       tracker_url=tracker.base_url, last_polled_at=datetime.now(UTC))
    db_session.add(ct)
    db_session.commit()
    db_session.add(ClientTorrentFile(client_torrent_id=ct.id, path_in_torrent="x.mkv", size_bytes=1,
                                     seed_file_id=sf.id, last_scan_id=sf.last_scan_id))
    db_session.commit()

    assert review.close_resolved_reviews(db_session) == 2
    assert m2t_open.status == "pending"
    assert (m2t_linked.status, m2t_linked.decided_by) == ("rejected", "system")
    assert (t2c_tracked.status, t2c_tracked.decided_by) == ("rejected", "system")


def test_review_of_a_file_gone_from_disk_is_closed(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    gone = _media_file_stub(db_session, item)
    later = pipeline.start_run(db_session, "manual")
    db_session.add(MediaFile(  # l'ultimo scan del disco ha visto solo questo file
        disk_id=gone.disk_id, relative_path="movies/other.mkv", size_bytes=1, st_dev=1, inode=8,
        media_item_id=item.id, last_scan_id=later.id, last_seen_at=datetime.now(UTC),
    ))
    db_session.commit()
    r = _review_for(db_session, _candidate(db_session, item, tracker, confidence=0.5), media_file_id=gone.id)

    assert review.close_resolved_reviews(db_session) == 1
    assert r.status == "rejected"


def test_review_of_a_file_excluded_meanwhile_leaves_the_queue(db_session):
    from nazgarr.core import settings_repo

    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)  # movies/x.mkv
    r = _review_for(db_session, _candidate(db_session, item, tracker, confidence=0.5), media_file_id=mf.id)
    settings_repo.set_setting(db_session, "exclusion_patterns", "movies/x.mkv")

    assert review.close_resolved_reviews(db_session) == 1
    assert (r.status, r.decided_by) == ("rejected", "system")


def test_approval_adds_the_torrent_to_the_client_chosen_for_its_tracker(db_session, monkeypatch):
    from nazgarr.core.models import TorrentClient

    public = TorrentClient(label="qbit public", adapter_type="qui", base_url="http://q", enabled=True)
    private = TorrentClient(label="qbit private", adapter_type="qui", base_url="http://q", enabled=True)
    db_session.add_all([public, private])
    db_session.commit()
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    candidate = _candidate(db_session, item, tracker, confidence=0.5)

    tracker.torrent_client_id = private.id
    db_session.commit()
    built = []
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: built.append(row.label) or object())
    adapter, client_id = review._client_for_candidate(db_session, candidate)
    assert (built, client_id) == (["qbit private"], private.id)

    private.enabled = False  # client disabilitato: si torna al primo abilitato
    db_session.commit()
    _adapter, client_id = review._client_for_candidate(db_session, candidate)
    assert client_id == public.id


def test_review_for_a_content_the_file_no_longer_is_leaves_the_queue(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    r = _review_for(db_session, _candidate(db_session, item, tracker, confidence=0.5), media_file_id=mf.id)
    corrected = MediaItem(content_type="movie", tmdb_id=2)
    db_session.add(corrected)
    db_session.commit()
    mf.media_item_id = corrected.id  # identità corretta da Radarr: il torrent era di un altro film
    db_session.commit()

    assert review.close_resolved_reviews(db_session) == 1
    assert (r.status, r.decided_by) == ("rejected", "system")


def test_a_seeding_execution_whose_torrent_left_the_client_no_longer_blocks_a_new_review(db_session):
    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    sf = _seed_file_stub(db_session, mf)
    old = _candidate(db_session, item, tracker, confidence=0.99)
    db_session.add(SeedJob(candidate_id=old.id, source_media_file_id=mf.id, final_status="seeding", info_hash="ABC"))
    db_session.commit()
    # Ora il file del torrent è orfano lato client: stesso torrent, verso torrent -> client.
    again = _candidate(db_session, item, tracker, confidence=0.99, direction="torrent_to_client")

    created = review.create_review_for_seed_file(db_session, sf, [again])

    assert created is not None and created.candidate_id == again.id


def test_a_seeding_execution_still_in_the_client_keeps_its_torrent_busy(db_session):
    from nazgarr.core.models import ClientTorrent, TorrentClient

    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    sf = _seed_file_stub(db_session, mf)
    old = _candidate(db_session, item, tracker, confidence=0.99)
    client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add(client)
    db_session.commit()
    db_session.add_all([
        SeedJob(candidate_id=old.id, source_media_file_id=mf.id, final_status="seeding", info_hash="ABC"),
        ClientTorrent(torrent_client_id=client.id, info_hash="abc", name="x", save_path="/x", state="uploading",
                      last_polled_at=datetime.now(UTC)),
    ])
    db_session.commit()
    again = _candidate(db_session, item, tracker, confidence=0.99, direction="torrent_to_client")

    assert review.create_review_for_seed_file(db_session, sf, [again]) is None


def test_a_seeding_execution_whose_torrent_left_the_client_is_shown_as_removed():
    job = SeedJob(final_status="seeding", info_hash="ABC")

    assert review.seed_job_display_status(job, {"abc"}) == "seeding"
    assert review.seed_job_display_status(job, set()) == "removed"
    assert review.seed_job_display_status(SeedJob(final_status="failed", info_hash="x"), set()) == "failed"


def test_each_tracker_keeps_its_own_proposal_for_the_same_file(db_session):
    # Cross-seed: lo stesso file può avere una review su ogni tracker; una
    # nuova ricerca sostituisce solo quella del suo tracker.
    a = _tracker(db_session)
    b = Tracker(label="b", adapter_type="unit3d", base_url="https://b.example", api_token="x")
    db_session.add(b)
    db_session.commit()
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)

    on_a = review.create_review_for_media_file(db_session, mf, [_candidate(db_session, item, a, confidence=0.5)])
    on_b = review.create_review_for_media_file(db_session, mf, [_candidate(db_session, item, b, confidence=0.5)])
    assert (on_a.status, on_b.status) == ("pending", "pending")

    again_on_a = review.create_review_for_media_file(db_session, mf, [_candidate(db_session, item, a, confidence=0.6)])
    db_session.refresh(on_a)
    db_session.refresh(on_b)
    assert (on_a.status, on_b.status, again_on_a.status) == ("rejected", "pending", "pending")


def test_a_torrent_already_in_a_client_is_not_proposed_again(db_session):
    from nazgarr.core.models import ClientTorrent, TorrentClient

    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add(client)
    db_session.commit()
    db_session.add(ClientTorrent(torrent_client_id=client.id, info_hash="abc", name="x", save_path="/x",
                                 state="uploading", last_polled_at=datetime.now(UTC)))
    db_session.commit()
    candidate = _candidate(db_session, item, tracker, confidence=0.9)
    candidate.info_hash = "ABC"
    db_session.commit()

    assert review.create_review_for_media_file(db_session, mf, [candidate]) is None


def test_a_review_says_where_the_file_already_seeds(db_session):
    from nazgarr.api.reviews import ReviewResponse
    from nazgarr.core.models import ClientTorrent, ClientTorrentFile, TorrentClient

    tracker = _tracker(db_session)
    item = _media_item(db_session)
    mf = _media_file_stub(db_session, item)
    sf = _seed_file_stub(db_session, mf)
    sf.media_file_id = mf.id
    client = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q")
    db_session.add(client)
    db_session.commit()
    ct = ClientTorrent(torrent_client_id=client.id, info_hash="h", name="x", save_path="/x", state="uploading",
                       tracker_url="https://www.t.example", last_polled_at=datetime.now(UTC))
    other = ClientTorrent(torrent_client_id=client.id, info_hash="h2", name="x", save_path="/x", state="uploading",
                          tracker_url="https://public.example", last_polled_at=datetime.now(UTC))
    db_session.add_all([ct, other])
    db_session.commit()
    for torrent in (ct, other):
        db_session.add(ClientTorrentFile(client_torrent_id=torrent.id, path_in_torrent="x.mkv", size_bytes=1,
                                         seed_file_id=sf.id, last_scan_id=sf.last_scan_id))
    db_session.commit()
    row = _review_for(db_session, _candidate(db_session, item, tracker, confidence=0.5), media_file_id=mf.id)

    assert ReviewResponse.from_model(row).seeding_on == ["public.example", "t"]
