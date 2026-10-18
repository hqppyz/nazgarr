"""Limite ai tentativi falliti di login, del codice monouso di setup e della
password attuale nel cambio password: 5 in 15 minuti per indirizzo, poi
429 finché il più vecchio non esce dalla finestra. Un successo azzera il
conto. In memoria: un riavvio lo azzera, e va bene così. Il cambio password
ha un conto suo (prefisso "pw:"): i suoi errori non bloccano il login.

Il tentativo si prenota prima di verificare la password (reserve): prima il
controllo e la registrazione dell'errore stavano ai due lati del PBKDF2, e
decine di richieste partite insieme passavano tutte il controllo (38 su 60
misurate, invece di 5; audit 2026-10-18). La prenotazione conta come errore
finché non arriva succeeded(), o release() per un tentativo che non era un
errore di credenziali (es. una password nuova troppo corta).

Dietro un reverse proxy tutti i tentativi arrivano dall'indirizzo del proxy:
il limite diventa uno solo per tutti, e chi sbaglia apposta 5 volte blocca
anche l'amministratore. FORWARDED_ALLOW_IPS con l'indirizzo del proxy (README)
fa leggere a uvicorn il vero client da X-Forwarded-For."""

import threading
import time
from collections import OrderedDict, deque

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
# Indirizzi ricordati al massimo: oltre, si dimenticano quelli toccati meno di
# recente, e la memoria non cresce con ogni indirizzo mai visto.
MAX_KEYS = 10_000

_lock = threading.Lock()
_failures: OrderedDict[str, deque[float]] = OrderedDict()


class TooManyAttempts(Exception):
    def __init__(self, wait: int):
        super().__init__(f"retry in {wait} s")
        self.wait = wait


def _now(now: float | None) -> float:
    return now if now is not None else time.monotonic()


def _attempts(key: str, now: float) -> deque[float] | None:
    """I tentativi ancora nella finestra; una chiave rimasta vuota sparisce."""
    attempts = _failures.get(key)
    if attempts is None:
        return None
    while attempts and attempts[0] <= now - WINDOW_SECONDS:
        attempts.popleft()
    if not attempts:
        del _failures[key]
        return None
    return attempts


def _wait(attempts: deque[float], now: float) -> int:
    return max(1, int(attempts[0] + WINDOW_SECONDS - now) + 1)


def _record(key: str, now: float) -> None:
    attempts = _failures.get(key)
    if attempts is None:
        while len(_failures) >= MAX_KEYS:
            _failures.popitem(last=False)
        attempts = _failures[key] = deque()
    attempts.append(now)
    _failures.move_to_end(key)


def retry_after(key: str, now: float | None = None) -> int | None:
    """Secondi da aspettare se il limite è raggiunto, se no None."""
    now = _now(now)
    with _lock:
        attempts = _attempts(key, now)
        if attempts is None or len(attempts) < MAX_FAILURES:
            return None
        return _wait(attempts, now)


def reserve(key: str, now: float | None = None) -> float:
    """Controllo e prenotazione in un colpo solo, sotto il lock: TooManyAttempts
    se il limite è raggiunto, se no il segno della prenotazione (per release)."""
    now = _now(now)
    with _lock:
        attempts = _attempts(key, now)
        if attempts is not None and len(attempts) >= MAX_FAILURES:
            raise TooManyAttempts(_wait(attempts, now))
        _record(key, now)
        return now


def release(key: str, stamp: float) -> None:
    """Restituisce una prenotazione: quel tentativo non era un errore."""
    with _lock:
        attempts = _failures.get(key)
        if attempts is None:
            return
        try:
            attempts.remove(stamp)
        except ValueError:
            pass
        if not attempts:
            del _failures[key]


def failed(key: str, now: float | None = None) -> None:
    now = _now(now)
    with _lock:
        _attempts(key, now)
        _record(key, now)


def succeeded(key: str) -> None:
    with _lock:
        _failures.pop(key, None)


def reset() -> None:
    with _lock:
        _failures.clear()
