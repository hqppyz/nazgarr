"""Nessuna credenziale nei messaggi di errore salvati nel DB (seed job,
upload, run, consegne dei webhook, eventi dei job): gli stessi schemi dei log
(app/logging_config.py), applicati prima di ogni scrittura, ovunque il
messaggio sia stato costruito. Un errore di httpx riporta l'URL completo,
es. /torrent/download/<id>.<rsskey>, e questi campi l'API li restituisce,
anche a una API key di sola lettura."""

from sqlalchemy import event as sa_event
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.logging_config import redact

COLUMNS = frozenset({"error_message", "last_error", "verify_detail", "phase_detail", "params_json"})


def _before_flush(session: Session, _flush_context, _instances) -> None:
    for obj in (*session.new, *session.dirty):
        mapper = inspect(obj).mapper
        for name in COLUMNS.intersection(mapper.columns.keys()):
            value = getattr(obj, name, None)
            if isinstance(value, str) and value:
                cleaned = redact(value)
                if cleaned != value:
                    setattr(obj, name, cleaned)


sa_event.listen(Session, "before_flush", _before_flush)
