def test_dashboard_empty_library(client):
    response = client.get("/api/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["health_pct"] == 100.0
    assert body["last_run"] is None
    assert body["pending_review"] == 0


def test_dashboard_history_empty(client):
    response = client.get("/api/dashboard/history")

    assert response.status_code == 200
    assert response.json() == []


def test_dashboard_changes_empty(client):
    response = client.get("/api/dashboard/changes")

    assert response.status_code == 200
    assert response.json()["total"] == 0 and response.json()["baseline_only"] is False


def test_dashboard_reflects_run_log(client):
    session = client.app.state.session_factory()
    try:
        from nazgarr import pipeline

        run = pipeline.start_run(session, "bulk_import")
        run.current_phase = None
        run.finished_at = run.started_at
        run.items_scanned = 5
        run.matches_found = 2
        run.auto_executed = 1
        run.pending_review = 1
        run.health_snapshot = 80.0
        session.commit()
    finally:
        session.close()

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["last_run"]["items_scanned"] == 5
    assert dashboard["last_run"]["matches_found"] == 2

    history = client.get("/api/dashboard/history").json()
    assert len(history) == 1
    assert history[0]["health_snapshot"] == 80.0
    assert history[0]["items_scanned"] == 5
    assert history[0]["matches_found"] == 2
    assert history[0]["auto_executed"] == 1
    assert history[0]["pending_review"] == 1
    assert history[0]["errors"] == 0


def test_schedule_defaults_to_disabled(client):
    response = client.get("/api/schedule")

    assert response.status_code == 200
    assert response.json() == {"cron": None, "enabled": False}


def test_schedule_put_valid_cron_enables_and_persists(client):
    response = client.put("/api/schedule", json={"cron": "0 3 * * *"})

    assert response.status_code == 200
    assert response.json() == {"cron": "0 3 * * *", "enabled": True}
    assert client.get("/api/schedule").json()["enabled"] is True
    assert client.app.state.scheduler.get_job("scheduled_run") is not None


def test_schedule_put_invalid_cron_rejected(client):
    response = client.put("/api/schedule", json={"cron": "not a cron expression"})

    assert response.status_code == 422
    assert client.get("/api/schedule").json()["enabled"] is False


def test_schedule_put_empty_disables(client):
    client.put("/api/schedule", json={"cron": "0 3 * * *"})

    response = client.put("/api/schedule", json={"cron": ""})

    assert response.status_code == 200
    assert response.json() == {"cron": None, "enabled": False}
    assert client.app.state.scheduler.get_job("scheduled_run") is None


def test_dashboard_trend_uses_the_scan_before_the_last_and_history_by_days(client):
    from datetime import UTC, datetime, timedelta

    from nazgarr import pipeline

    session = client.app.state.session_factory()
    try:
        now = datetime.now(UTC)
        for age_days, health, ignored in ((40, 70.0, 500), (2, 80.0, 300), (0, 90.0, 100)):
            run = pipeline.start_run(session, "manual")
            run.current_phase = None
            run.finished_at = now - timedelta(days=age_days)
            run.health_snapshot, run.ignored_bytes = health, ignored
            session.commit()
    finally:
        session.close()

    body = client.get("/api/dashboard").json()
    assert (body["previous"]["health_snapshot"], body["previous"]["ignored_bytes"]) == (80.0, 300)

    last_week = client.get("/api/dashboard/history", params={"days": 7}).json()
    assert [p["health_snapshot"] for p in last_week] == [90.0, 80.0]


def test_dashboard_and_history_take_a_tracker_filter(client):
    resp = client.get("/api/dashboard?tracker=configured")
    assert resp.status_code == 200
    assert client.get("/api/dashboard/history?tracker=configured").json() == []
    assert client.get("/api/dashboard?tracker=bogus").status_code == 200  # un filtro sconosciuto = tutti


def test_without_a_library_the_history_keeps_the_torrent_numbers(client):
    # Solo torrent e upload: niente salute, ma l'andamento delle card sì.
    from datetime import UTC, datetime

    from nazgarr import pipeline

    session = client.app.state.session_factory()
    try:
        run = pipeline.start_run(session, "manual")
        run.current_phase = None
        run.finished_at = datetime.now(UTC)
        run.health_snapshot, run.orphan_torrent_bytes = None, 1234
        session.commit()
    finally:
        session.close()

    [point] = client.get("/api/dashboard/history").json()
    assert (point["health_snapshot"], point["orphan_torrent_bytes"]) == (None, 1234)


def test_the_dashboard_is_not_recomputed_while_the_data_is_unchanged(client, monkeypatch):
    """Si interroga ogni 15 secondi: la salute si ricalcola solo quando i
    dati cambiano (nazgarr/response_cache.py)."""
    from nazgarr import health

    calls = []
    real = health.compute_snapshot
    monkeypatch.setattr(health, "compute_snapshot", lambda *a, **k: calls.append(1) or real(*a, **k))

    first = client.get("/api/dashboard")
    again = client.get("/api/dashboard", headers={"If-None-Match": first.headers["etag"]})
    other_scope = client.get("/api/dashboard?tracker=configured")
    client.put("/api/settings/exclusion_patterns", json={"value": "*.nfo"})
    changed = client.get("/api/dashboard")

    assert first.status_code == 200 and again.status_code == 304
    assert other_scope.status_code == 200 and changed.status_code == 200
    assert len(calls) == 3  # la prima, l'altro filtro, dopo il cambio
    assert first.json()["health_pct"] == changed.json()["health_pct"]
