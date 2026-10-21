"""Esecuzioni che non arrivavano mai a un esito (audit 2026-10-18, finding
113): interrotte da un riavvio prima dell'info hash, col torrent sparito dal
client, o nel client di un client poi spento."""

from datetime import UTC, datetime, timedelta

import pytest

from nazgarr.core.models import Candidate, MatchReview, MediaItem, SeedJob, TorrentClient, Tracker
from nazgarr.reseed import executor, review


@pytest.fixture(autouse=True)
def _forget_missing():
    """Le assenze viste (executor._missing_since) e i reconcile già falliti
    (review._failing) sono per id di seed job, e ogni test ha il suo DB con
    gli stessi id."""
    executor._missing_since.clear()
    review._failing.clear()
    yield
    executor._missing_since.clear()
    review._failing.clear()


def _missing_for(job, minutes):
    """Come se il controllo l'avesse visto mancare per la prima volta minuti fa."""
    executor._missing_since[job.id] = datetime.now(UTC) - timedelta(minutes=minutes)


def _job(session, *, info_hash="abc", added_minutes_ago=60, client=None, tmdb_id=1):
    tracker = Tracker(label="t", adapter_type="unit3d", base_url="https://t.example", api_token="x")
    item = MediaItem(content_type="movie", tmdb_id=tmdb_id)
    session.add_all([tracker, item])
    session.commit()
    candidate = Candidate(media_item_id=item.id, tracker_id=tracker.id, torrent_id_remote="1", name="x",
                          size_bytes=1, source="catalog_search", direction="media_to_torrent", confidence=0.9)
    session.add(candidate)
    session.commit()
    session.add(MatchReview(candidate_id=candidate.id, status="approved"))
    job = SeedJob(candidate_id=candidate.id, final_status="in_progress", info_hash=info_hash,
                  torrent_client_id=client.id if client else None,
                  torrent_added_at=datetime.now(UTC) - timedelta(minutes=added_minutes_ago))
    session.add(job)
    session.commit()
    return job


def _client(session, enabled=True):
    row = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q", enabled=enabled)
    session.add(row)
    session.commit()
    return row


class _Gone:
    """Il client risponde, ma quel torrent non ce l'ha più."""

    def __init__(self):
        self.status_calls = 0

    def get_torrent_status(self, info_hash):
        self.status_calls += 1
        raise ValueError(f"Torrent {info_hash} non trovato")

    def get_torrent_info(self, info_hash):
        return None


def test_an_execution_interrupted_before_the_info_hash_fails_at_startup(db_session):
    job = _job(db_session, info_hash=None)
    other = SeedJob(candidate_id=job.candidate_id, final_status="in_progress", info_hash="def")
    db_session.add(other)
    db_session.commit()

    review.reset_interrupted_verifications(db_session)

    assert (job.final_status, job.error_message) == ("failed", review.INTERRUPTED_SEED_JOB)
    assert other.final_status == "in_progress"  # col suo info hash la segue il controllo dei recheck


def test_a_torrent_gone_from_the_client_ends_the_execution(db_session, monkeypatch):
    client = _client(db_session)
    job = _job(db_session, client=client)
    gone = _Gone()
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: gone)

    # La prima lettura che non lo trova non basta, anche per un'esecuzione
    # aggiunta un'ora fa: i 10 minuti contano di fila.
    assert review.reconcile_pending_seed_jobs(db_session) == {"reconciled": 0, "errors": 0}
    assert job.final_status == "in_progress"

    _missing_for(job, 11)
    assert review.reconcile_pending_seed_jobs(db_session) == {"reconciled": 0, "errors": 0}
    assert job.final_status == "failed" and "no longer in the client" in job.error_message
    assert review.has_pending_seed_jobs(db_session) is False  # niente più controlli ogni 2 minuti
    assert job.id not in executor._missing_since


def test_a_client_restarted_while_loading_its_torrents_does_not_fail_a_long_reseed(db_session, monkeypatch):
    """Revisione dell'audit 2026-10-18 (R7): la grazia contava da
    torrent_added_at, e un reseed in corso da più di 10 minuti falliva alla
    prima lettura di un client appena riavviato, che lo ricaricava un minuto
    dopo."""
    from nazgarr.adapters.torrent_client.base import TorrentStatus

    client = _client(db_session)
    job = _job(db_session, client=client, added_minutes_ago=30)

    class Restarting(_Gone):
        """Non lo trova alla prima lettura, poi lo ha di nuovo, in recheck."""

        def get_torrent_status(self, info_hash):
            if self.status_calls == 0:
                return super().get_torrent_status(info_hash)
            return TorrentStatus(info_hash, "checkingUP", "pending", 0.3)

    restarting = Restarting()
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: restarting)

    review.reconcile_pending_seed_jobs(db_session)
    assert job.final_status == "in_progress" and job.id in executor._missing_since
    review.reconcile_pending_seed_jobs(db_session)

    assert (job.final_status, job.recheck_status) == ("in_progress", "pending")
    assert job.id not in executor._missing_since  # riapparso: il conto ricomincia


def test_the_grace_never_counts_from_before_the_torrent_was_added(db_session, monkeypatch):
    # Visto mancare 20 minuti fa, ma aggiunto (o riaggiunto da un retry) 2 minuti fa.
    client = _client(db_session)
    job = _job(db_session, client=client, added_minutes_ago=2)
    _missing_for(job, 20)
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: _Gone())

    review.reconcile_pending_seed_jobs(db_session)

    assert job.final_status == "in_progress"


def test_a_torrent_just_added_gets_a_grace_period(db_session, monkeypatch):
    client = _client(db_session)
    job = _job(db_session, client=client, added_minutes_ago=1)
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: _Gone())

    review.reconcile_pending_seed_jobs(db_session)

    assert job.final_status == "in_progress"


def test_an_execution_of_a_disabled_client_is_not_asked_to_another_client(db_session, monkeypatch):
    disabled = _client(db_session, enabled=False)
    _client(db_session)  # quello abilitato, che non ha il torrent
    job = _job(db_session, client=disabled)
    asked = []
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: asked.append(row.id) or _Gone())

    review.reconcile_pending_seed_jobs(db_session)

    assert asked == []
    assert job.final_status == "failed" and "disabled or deleted" in job.error_message


def test_a_client_whose_adapter_cannot_look_up_one_torrent_is_never_called_missing(db_session, monkeypatch):
    # Il get_torrent_info di default (un plugin che non lo implementa) dà
    # None senza chiedere niente al client: un client irraggiungibile
    # diventava "il torrent non c'è più".
    from tests.fakes import FakeAdapter

    class Unreachable(FakeAdapter):
        def get_torrent_status(self, info_hash):
            raise ConnectionError("connection refused")

    client = _client(db_session)
    job = _job(db_session, client=client, added_minutes_ago=60)
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: Unreachable([]))

    assert review.reconcile_pending_seed_jobs(db_session) == {"reconciled": 0, "errors": 1}
    assert job.final_status == "in_progress"


def test_a_client_that_cannot_be_built_does_not_stop_the_reconcile_of_the_others(db_session, monkeypatch):
    """Un qBittorrent il cui host ora risolve ai metadati del cloud: il suo
    adapter non si costruisce (net_guard, audit 2026-10-18), e fermava il
    giro intero, senza più avviare i reseed degli altri client."""
    from nazgarr.adapters.torrent_client.base import TorrentStatus
    from tests.fakes import RecordingClient

    rebound = TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://169.254.169.254:8080",
                            enabled=True)
    db_session.add(rebound)
    db_session.commit()
    other = _client(db_session)
    stuck = _job(db_session, client=rebound)
    job = _job(db_session, info_hash="def", client=other, tmdb_id=2)
    fine = RecordingClient(status=TorrentStatus("def", "uploading", "ok", 1.0))
    real = review.build_torrent_client_adapter
    monkeypatch.setattr(review, "build_torrent_client_adapter",
                        lambda row: real(row) if row.id == rebound.id else fine)

    assert review.reconcile_pending_seed_jobs(db_session) == {"reconciled": 1, "errors": 1}
    assert stuck.final_status == "in_progress" and job.final_status == "seeding"


def test_a_reconcile_that_keeps_failing_logs_its_traceback_once(db_session, monkeypatch, caplog):
    """Un client il cui adapter non sa dire se il torrent c'è (un plugin):
    il seed job resta in corso, apposta, e il log riceveva una traccia ogni
    2 minuti, per sempre (audit 2026-10-18, finding 113)."""
    import logging

    from tests.fakes import FakeAdapter

    class Unreachable(FakeAdapter):
        def get_torrent_status(self, info_hash):
            raise ConnectionError("connection refused")

    client = _client(db_session)
    job = _job(db_session, client=client)
    monkeypatch.setattr(review, "build_torrent_client_adapter", lambda row: Unreachable([]))

    with caplog.at_level(logging.WARNING, logger="nazgarr.reseed.review"):
        review.reconcile_pending_seed_jobs(db_session)
        review.reconcile_pending_seed_jobs(db_session)

    records = [r for r in caplog.records if f"seed_job {job.id}" in r.getMessage()]
    assert [r.exc_info is not None for r in records] == [True, False]
    assert "connection refused" in records[1].getMessage()
