"""Una cosa alla volta fra le run e il lavoro a lato (audit 2026-10-18).

Le run sono esclusive fra loro: pipeline.try_start_run controlla e inserisce
la riga RunLog sotto pipeline._start_lock. Il lavoro a lato che scrive le
stesse tabelle (gli eventi dei webhook di Radarr/Sonarr con la loro ricerca
facoltativa, "Cerca ora", il ricalcolo dei Non importati) controllava solo
che nessuna run fosse in corso, poi lavorava senza tenere niente: una run
programmata o "Scan now" poteva partire a metà e arrivare al matching dello
stesso tracker (un IntegrityError su match_attempt e il resto del tracker
saltato, o due review attive per lo stesso file).

Ora quel lavoro tiene per tutta la sua durata lo stesso lock con cui una run
parte (side_work):
- lo prende senza aspettare: se è preso (una run sta partendo, o c'è già un
  altro lavoro a lato) o se una run è in corso, Busy, e chi chiama salta (lo
  scheduler riprova al giro dopo) o risponde 409;
- una run programmata che parte nel frattempo aspetta che finisca, invece di
  partire a metà o di essere saltata; una volta partita, la sua riga RunLog
  ancora aperta tiene fuori il lavoro a lato finché non finisce, come prima.
"Scan now" aspetta al massimo START_WAIT_SECONDS (start_run), poi 409: una
richiesta HTTP non resta appesa per i minuti di un "Cerca ora".

Nessun lavoro a lato avvia una run né chiama un altro lavoro a lato: il lock
non è rientrante, e non serve che lo sia.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from nazgarr.core.models import RunLog
from nazgarr.reseed import pipeline

START_WAIT_SECONDS = 10.0


class Busy(Exception):
    """Una run in corso o un altro lavoro a lato: non adesso."""


def _lock() -> threading.Lock:
    # Lo stesso lock di try_start_run: una run che parte (dallo scheduler o
    # da qui) aspetta il lavoro a lato in corso.
    return pipeline._start_lock


@contextmanager
def side_work(session: Session) -> Iterator[None]:
    """Il lavoro a lato, mai insieme a una run né a un altro lavoro a lato.
    Solleva Busy prima di cominciare, se non è il momento."""
    lock = _lock()
    if not lock.acquire(blocking=False):
        raise Busy()
    try:
        if pipeline.run_in_progress(session):
            raise Busy()
        yield
    finally:
        lock.release()


def start_run(session: Session, run_type: str, wait_seconds: float = START_WAIT_SECONDS) -> RunLog:
    """Come pipeline.try_start_run, ma aspetta il lavoro a lato in corso al
    massimo wait_seconds: RunInProgressError se non basta, o se una run è già
    in corso."""
    lock = _lock()
    if not lock.acquire(timeout=wait_seconds):
        raise pipeline.RunInProgressError()
    try:
        if pipeline.run_in_progress(session):
            raise pipeline.RunInProgressError()
        return pipeline.start_run(session, run_type)
    finally:
        lock.release()
