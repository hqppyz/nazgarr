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

Il 409 dice cosa c'è in corso (Busy.code, revisione dell'audit 2026-10-18):
run_in_progress per una run, side_work_in_progress per il lavoro a lato.
Prima era sempre "C'è una scansione in corso", anche quando nessuna
scansione girava e l'indicatore delle run non mostrava niente.

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
    """Una run in corso o un altro lavoro a lato: non adesso. `code` è il
    codice dell'errore per l'API (nazgarr/core/errors.py)."""

    def __init__(self, run: bool = False):
        super().__init__("run in progress" if run else "other work in progress")
        self.run = run

    @property
    def code(self) -> str:
        return "run_in_progress" if self.run else "side_work_in_progress"


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
        # Preso da un altro lavoro a lato, o da una run che sta partendo.
        raise Busy(run=pipeline.run_in_progress(session))
    try:
        if pipeline.run_in_progress(session):
            raise Busy(run=True)
        yield
    finally:
        lock.release()


def start_run(session: Session, run_type: str, wait_seconds: float | None = None) -> RunLog:
    """Come pipeline.try_start_run, ma aspetta il lavoro a lato in corso al
    massimo wait_seconds (START_WAIT_SECONDS): Busy se non basta,
    RunInProgressError se una run è già in corso."""
    lock = _lock()
    if not lock.acquire(timeout=START_WAIT_SECONDS if wait_seconds is None else wait_seconds):
        if pipeline.run_in_progress(session):
            raise pipeline.RunInProgressError()
        raise Busy()
    try:
        if pipeline.run_in_progress(session):
            raise pipeline.RunInProgressError()
        return pipeline.start_run(session, run_type)
    finally:
        lock.release()
