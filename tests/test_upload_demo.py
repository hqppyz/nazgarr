"""L'upload di esempio del tour (frontend/src/lib/uploadDemo.json): le
schermate di conferma del match e di decisione mostrate con dati finti, mai
un job vero (decisione dell'utente, 2026-10-05).

I dati non sono scritti a mano: nascono dall'API vera, con TMDB, tracker e
mediainfo finti, così hanno la forma che le schermate si aspettano. Per
rigenerarli dopo un cambio dell'API:

    NAZGARR_WRITE_UPLOAD_DEMO=1 .venv/bin/python -m pytest tests/test_upload_demo.py

Senza la variabile il test controlla che i dati salvati abbiano ancora le
stesse chiavi di quelli che l'API produce adesso."""

import json
import os
from pathlib import Path

from nazgarr.adapters.media_resolver.base import ResolvedMedia
from nazgarr.upload import identify as upload_identify
from tests.test_api_uploads import setup  # noqa: F401  (fixture)
from tests.upload_helpers import FakeTMDB, make_tracker, tmdb_result, write_video

DEMO = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "uploadDemo.json"
# Un film inventato: nessun titolo vero, e un id TMDB che non esiste (i link
# dell'esempio non portano a nessun film).
TITLE, YEAR, TMDB_ID, IMDB_ID = "Absolute Cinema", 1895, 99_999_999, None
NAME = "Absolute.Cinema.1895.2160p.AI.Upscaled.BluRay.x265-MaTiTa.mkv"
# I file dei test sono piccoli: nei dati salvati, la dimensione di un 2160p vero.
TEST_SIZE, SHOWN_SIZE = 300_123, 21_474_836_480
DEMO_ID = 0  # mai l'id di un job vero: il frontend serve da sé tutto quello che lo riguarda


def _build(client, tmp_path, setup, monkeypatch) -> dict:  # noqa: F811
    session = client.app.state.session_factory()
    make_tracker(session, "ITT")
    session.close()
    write_video(tmp_path / "releases" / NAME, TEST_SIZE)
    setup["resolver"].resolved = ResolvedMedia(tmdb_id=TMDB_ID, content_type="movie", title=TITLE, year=YEAR,
                                               poster_path=None)
    details = {**tmdb_result(TMDB_ID, TITLE, YEAR), "genres": ["Documentary"],
               "runtime": 1, "imdb_id": IMDB_ID, "tvdb_id": None, "cast": [], "original_language": "fr",
               "overview": "A made-up film, here only to show how an upload works."}
    fake = FakeTMDB(search={("movie", TITLE, YEAR): [tmdb_result(TMDB_ID, TITLE, YEAR)]},
                    details={("movie", TMDB_ID): details})
    monkeypatch.setattr(upload_identify, "tmdb_client", lambda session: fake)

    job_id = client.post("/api/uploads", json={"disk_id": setup["disk_id"],
                                               "relative_path": "releases/" + NAME}).json()["id"]
    match = client.get(f"/api/uploads/{job_id}").json()
    metadata = client.get(f"/api/metadata/movie/{TMDB_ID}").json()
    client.post(f"/api/uploads/{job_id}/match", json={"content_type": "movie", "tmdb_id": TMDB_ID, "kind": "movie"})
    decision = client.get(f"/api/uploads/{job_id}").json()
    text = json.dumps({"match": match, "decision": decision, "metadata": metadata})
    # Niente percorsi della macchina dei test, e l'id che nessun job vero ha.
    text = text.replace(str(tmp_path), "/data").replace(str(TEST_SIZE), str(SHOWN_SIZE))
    # Il tracker del fixture si chiama "t": un nome che si legge.
    text = text.replace('"tracker_label": "t"', '"tracker_label": "Another tracker"').replace(
        "https://t.example", "https://tracker.example")
    data = json.loads(text)
    for step in ("match", "decision"):
        data[step]["id"] = DEMO_ID
        for event in data[step].get("events", []):
            event["created_at"] = "2026-10-05T12:00:00Z"
        data[step]["created_at"] = data[step]["updated_at"] = "2026-10-05T12:00:00Z"
    return data


def _keys(value, prefix="") -> set[str]:
    if isinstance(value, dict):
        return {f"{prefix}.{k}" for k in value} | {x for k, v in value.items() for x in _keys(v, f"{prefix}.{k}")}
    if isinstance(value, list) and value:
        return _keys(value[0], prefix + "[]")
    return set()


def test_the_demo_upload_has_the_shape_of_the_api(client, tmp_path, setup, monkeypatch):  # noqa: F811
    fresh = _build(client, tmp_path, setup, monkeypatch)
    assert fresh["match"]["status"] == "awaiting_match"
    assert fresh["decision"]["status"] == "awaiting_decision"
    if os.environ.get("NAZGARR_WRITE_UPLOAD_DEMO") == "1":
        DEMO.write_text(json.dumps(fresh, indent=1, sort_keys=True) + "\n")
    stored = json.loads(DEMO.read_text())
    assert _keys(stored) == _keys(fresh), "rigenera frontend/src/lib/uploadDemo.json (vedi il docstring)"
