"""Avanzamento live di una run, per il popup di stato (RunStatusIndicator):
per ogni fase quanti elementi sono stati fatti su quanti, un testo di
dettaglio (disco, client o tracker corrente, attesa per un rate limit) e
quando è iniziata — da cui il frontend ricava barra, x/y e stima del tempo
rimanente.

Tutto vive su run_log: `phase_total`/`phase_done`/`phase_detail` per la
fase in corso, `phases_json` per il riepilogo di tutte le fasi (anche
quelle già concluse, mostrate nello stepper). Scritto nel DB al massimo
ogni COMMIT_EVERY elementi o COMMIT_INTERVAL_SECONDS, mai a ogni file: il
poller legge GET /api/runs ogni pochi secondi, un commit per file
rallenterebbe lo scan senza nessun beneficio visibile.
"""

import json
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from nazgarr.core.models import RunLog

PHASES = ("scanning", "resolving", "indexing", "matching", "executing", "reconciling")

COMMIT_EVERY = 50
COMMIT_INTERVAL_SECONDS = 1.0


class RunCancelled(BaseException):  # noqa: N818 (non è un errore: è una richiesta dell'utente)
    """L'utente ha chiesto di fermare la run ("Stop run"). BaseException e
    non Exception di proposito: ogni fase intercetta Exception per isolare
    i propri errori e proseguire (un file, un client, un tracker) — una
    richiesta di stop deve invece attraversarle tutte fino alla pipeline."""


class RunProgress:
    def __init__(self, session: Session, run: RunLog):
        self._session = session
        self._run = run
        self._phases: dict[str, dict] = json.loads(run.phases_json) if run.phases_json else {}
        self._current: str | None = None
        self._pending = 0
        self._last_commit = 0.0

    # --- fasi -----------------------------------------------------------

    def start_phase(self, phase: str, total: int | None = None, detail: str | None = None) -> None:
        self._close_current()
        self._current = phase
        self._phases[phase] = {
            "status": "running", "done": 0, "total": total, "skipped": 0,
            "started_at": datetime.now(UTC).isoformat(),
        }
        self._run.current_phase = phase
        self._run.phase_total = total
        self._run.phase_done = 0
        self._run.phase_detail = detail
        self._flush()

    def add_total(self, n: int) -> None:
        """Il totale di una fase che si scopre a pezzi (un disco o un
        tracker alla volta)."""
        state = self._state()
        state["total"] = (state.get("total") or 0) + n
        self._run.phase_total = state["total"]
        self._flush()

    def advance(self, n: int = 1, *, skipped: int = 0) -> None:
        state = self._state()
        state["done"] += n
        state["skipped"] += skipped
        self._run.phase_done = state["done"]
        self._pending += n + skipped
        now = time.monotonic()
        if self._pending >= COMMIT_EVERY or now - self._last_commit >= COMMIT_INTERVAL_SECONDS:
            self._flush()

    def detail(self, text: str | None) -> None:
        """Sempre scritto subito: è ciò che l'utente legge per capire
        perché la run sembra ferma (es. attesa per un rate limit)."""
        self._run.phase_detail = text
        self._flush()

    def result(self, *, candidates: int = 0, executed: int = 0) -> None:
        self._run.matches_found = (self._run.matches_found or 0) + candidates
        self._run.auto_executed = (self._run.auto_executed or 0) + executed

    def finish(self) -> None:
        self._close_current()
        self._run.current_phase = None
        self._run.phase_total = None
        self._run.phase_done = None
        self._run.phase_detail = None
        # Anche dopo uno stop: qui la richiesta è già stata gestita, un
        # nuovo controllo la rilancerebbe e la run non finirebbe mai.
        self._flush(check_cancel=False)

    # --- interni --------------------------------------------------------

    def _state(self) -> dict:
        if self._current is None:
            raise RuntimeError("Nessuna fase in corso")
        return self._phases[self._current]

    def _close_current(self) -> None:
        if self._current is None:
            return
        state = self._phases[self._current]
        state["status"] = "done"
        state["finished_at"] = datetime.now(UTC).isoformat()
        if state.get("total") is None:
            state["total"] = state["done"]

    def _flush(self, check_cancel: bool = True) -> None:
        self._run.phases_json = json.dumps(self._phases)
        self._session.commit()
        self._pending = 0
        self._last_commit = time.monotonic()
        if check_cancel:
            self._check_cancel()

    def _check_cancel(self) -> None:
        # Scritta da un'altra sessione (POST /api/runs/{id}/cancel): una
        # lettura diretta, mai il valore in cache sull'oggetto run.
        requested = self._session.query(RunLog.cancel_requested_at).filter_by(id=self._run.id).scalar()
        if requested is not None:
            raise RunCancelled()


class NullProgress:
    """Stessa interfaccia di RunProgress, nessun effetto: il default dei
    moduli che riportano avanzamento (risoluzione, matching, esecuzione)
    quando vengono chiamati fuori da una run (test, API)."""

    def add_total(self, n: int) -> None:
        pass

    def advance(self, n: int = 1, *, skipped: int = 0) -> None:
        pass

    def detail(self, text: str | None) -> None:
        pass

    def result(self, *, candidates: int = 0, executed: int = 0) -> None:
        pass


NULL_PROGRESS = NullProgress()
