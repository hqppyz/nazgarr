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
