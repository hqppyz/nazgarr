"""Nessuna credenziale nei messaggi di errore salvati nel DB (seed job,
upload, run, consegne dei webhook, eventi dei job): gli stessi schemi dei log
(nazgarr/core/logs.py), applicati prima di ogni scrittura, ovunque il
messaggio sia stato costruito. Un errore di httpx riporta l'URL completo,
es. /torrent/download/<id>.<rsskey>, e questi campi l'API li restituisce,
anche a una API key di sola lettura."""

from sqlalchemy import event as sa_event
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from nazgarr.core.logs import redact

# errors_json (ogni errore di una run, nazgarr/reseed/pipeline.py::_note_error)
# ha lo stesso testo di last_error, ed è quello che /api/runs mostra; detail
# è degli eventi dei webhook di Radarr/Sonarr e dei torrent non importati
# (audit 2026-10-18). Gli schemi lavorano anche sul JSON: nessuno consuma
# le virgolette. tests/test_logging_redaction.py controlla che ogni colonna
# *_error, *_detail, errors_json e detail dei modelli sia qui.
COLUMNS = frozenset({
    "error_message", "last_error", "verify_detail", "phase_detail", "params_json", "errors_json", "detail",
})


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
