"""Nessuna credenziale nei messaggi di errore salvati nel DB (seed job,
upload, run, consegne dei webhook, eventi dei job): gli stessi schemi dei log
(nazgarr/core/logs.py), applicati prima di ogni scrittura, ovunque il
messaggio sia stato costruito. Un errore di httpx riporta l'URL completo,
es. /torrent/download/<id>.<rsskey>, e questi campi l'API li restituisce,
anche a una API key di sola lettura."""

import json

from sqlalchemy import event as sa_event
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from nazgarr.core.logs import redact

# errors_json (ogni errore di una run, nazgarr/reseed/pipeline.py::_note_error)
# ha lo stesso testo di last_error, ed è quello che /api/runs mostra; detail
# è degli eventi dei webhook di Radarr/Sonarr e dei torrent non importati
# (audit 2026-10-18). tests/test_logging_redaction.py controlla che ogni
# colonna *_error, *_detail, errors_json e detail dei modelli sia qui.
COLUMNS = frozenset({
    "error_message", "last_error", "verify_detail", "phase_detail", "params_json", "errors_json", "detail",
})


def _redact_leaves(value):
    """Ogni stringa dentro un valore JSON già letto, chiavi escluse."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_leaves(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_leaves(item) for key, item in value.items()}
    return value


def _redact_json(text: str) -> str:
    """Una colonna *_json si ripulisce per struttura, non come testo: gli
    schemi dei log consumano la barra di una virgoletta escapata (token=abc\\"
    diventa token=<redacted>), e il JSON che resta non si legge più, con
    /api/runs che perde l'elenco degli errori (audit 2026-10-18). Si riscrive
    con i default di json.dumps, quelli di chi scrive queste colonne, e solo
    se qualcosa è cambiato. Un testo che non è JSON si ripulisce come testo."""
    try:
        parsed = json.loads(text)
    except ValueError:
        return redact(text)
    cleaned = _redact_leaves(parsed)
    return text if cleaned == parsed else json.dumps(cleaned)


def _before_flush(session: Session, _flush_context, _instances) -> None:
    for obj in (*session.new, *session.dirty):
        mapper = inspect(obj).mapper
        for name in COLUMNS.intersection(mapper.columns.keys()):
            value = getattr(obj, name, None)
            if isinstance(value, str) and value:
                cleaned = _redact_json(value) if name.endswith("_json") else redact(value)
                if cleaned != value:
                    setattr(obj, name, cleaned)


sa_event.listen(Session, "before_flush", _before_flush)
