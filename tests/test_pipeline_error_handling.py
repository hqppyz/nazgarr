"""Copre il bug diagnosticato in nazgarr/reseed/pipeline.py: un'eccezione a metà di
una fase (qui, l'indicizzazione di un client torrent irraggiungibile) non
deve avvelenare la sessione SQLAlchemy per il resto della run — senza
session.rollback(), il commit finale (errors/finished_at/health_snapshot)
falliva a sua volta, in silenzio, lasciando la run agganciata per sempre
come "in corso" senza mai un errore visibile (sintomo riportato
dall'utente: "ha chiamato il client e poi più nulla")."""


def test_failing_torrent_client_does_not_poison_the_run(client):
    client.post(
        "/api/torrent-clients",
        json={
            "label": "Unreachable qui",
            "adapter_type": "qui",
            "base_url": "http://qui.invalid.example",
            "api_token": "x",
            "qui_instance_id": 1,
        },
    )

    trigger = client.post("/api/runs")
    run_id = trigger.json()["id"]

    run = client.get(f"/api/runs/{run_id}").json()

    # La run deve comunque finire — non restare agganciata come "in corso"
    # a causa della sessione avvelenata dall'eccezione del client torrent.
    assert run["finished_at"] is not None
    assert run["errors"] >= 1
    assert run["last_error"] is not None
    assert "Unreachable qui" in run["last_error"]

    # health.compute_snapshot() gira DOPO l'indicizzazione fallita, nello
    # stesso commit finale: se la sessione fosse rimasta avvelenata,
    # anche questo sarebbe silenziosamente saltato/fallito.
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["health_pct"] is not None


def test_a_failing_health_snapshot_still_finishes_the_run(db_session, monkeypatch, tmp_path):
    # Il rollback dell'errore buttava via anche finished_at: la run restava
    # "in corso" fino al riavvio e ogni run dopo era rifiutata (audit
    # 2026-10-18, finding 40).
    from nazgarr.library import health
    from nazgarr.reseed import pipeline

    def broken(*args, **kwargs):
        raise RuntimeError("snapshot bug")

    monkeypatch.setattr(health, "compute_snapshot", broken)
    run = pipeline.start_run(db_session, "manual")
    pipeline.run_bulk_import(db_session, run, str(tmp_path))

    db_session.refresh(run)
    assert run.finished_at is not None
    assert run.errors >= 1 and "snapshot bug" in run.last_error
    assert run.pending_review == 0
    assert pipeline.run_in_progress(db_session) is False
    pipeline.try_start_run(db_session, "manual")  # nessun RunInProgressError


def test_a_failing_final_commit_still_closes_the_run(db_session, monkeypatch, tmp_path):
    from nazgarr.reseed import pipeline

    run = pipeline.start_run(db_session, "manual")
    real_commit = db_session.commit
    calls = {"n": 0}
    original_finish = pipeline._BulkRun.finish

    def finish(self):
        def failing_once():
            # Il primo commit dopo la fotografia (quello finale) fallisce.
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("disk I/O error")
            return real_commit()

        snapshot = pipeline._save_tracker_snapshots

        def save_then_break(*a, **k):
            snapshot(*a, **k)
            monkeypatch.setattr(db_session, "commit", failing_once)

        monkeypatch.setattr(pipeline, "_save_tracker_snapshots", save_then_break)
        return original_finish(self)

    monkeypatch.setattr(pipeline._BulkRun, "finish", finish)
    pipeline.run_bulk_import(db_session, run, str(tmp_path))
    monkeypatch.setattr(db_session, "commit", real_commit)

    db_session.expire_all()
    assert pipeline.run_in_progress(db_session) is False
    assert "could not be saved" in db_session.get(type(run), run.id).last_error
