

def test_every_error_of_a_run_is_kept_not_only_the_last():
    import json

    from nazgarr.core.models import RunLog
    from nazgarr.reseed.pipeline import _note_error

    run = RunLog(run_type="manual")
    _note_error(run, "tracker 'a': boom")
    _note_error(run, "TMDB resolution: timeout")

    assert json.loads(run.errors_json) == ["tracker 'a': boom", "TMDB resolution: timeout"]
    assert run.last_error == "TMDB resolution: timeout"


def test_the_indexing_progress_follows_the_count_the_client_reports(db_session, monkeypatch, tmp_path):
    """Revisione dell'audit 2026-10-18: on_progress(fatti, totale) può
    coprire un gruppo di torrent (qBittorrent riporta in una chiamata sola
    tutti quelli coi file riusati, rTorrent uno ogni 100), e contare le
    chiamate fermava la fase a 1/8 per un client di 10.000 torrent."""
    from nazgarr.core.models import TorrentClient
    from nazgarr.integrations import adapter_factory
    from nazgarr.reseed import pipeline
    from tests.fakes import FakeAdapter

    class Grouped(FakeAdapter):
        def list_torrents(self, on_progress=None):
            on_progress(5, 10)  # i file riusati, tutti insieme
            on_progress(5, 10)  # nessun torrent in più
            on_progress(10, 10)
            return []

    db_session.add(TorrentClient(label="q", adapter_type="qbittorrent", base_url="http://q", enabled=True))
    db_session.commit()
    monkeypatch.setattr(adapter_factory, "build_torrent_client_adapter", lambda row: Grouped([]))
    run = pipeline.start_run(db_session, "manual")

    pipeline._BulkRun(db_session, run, str(tmp_path)).index()

    assert (run.phase_done, run.phase_total) == (10, 10)
