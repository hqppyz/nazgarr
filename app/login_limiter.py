"""Limite ai tentativi falliti di login, del codice monouso di setup e della
password attuale nel cambio password: 5 in 15 minuti per indirizzo, poi
429 finché il più vecchio non esce dalla finestra. Un successo azzera il
conto. In memoria: un riavvio lo azzera, e va bene così.

Dietro un reverse proxy tutti i tentativi arrivano dallo stesso indirizzo:
il limite diventa uno solo per tutti, che resta una protezione (e un login
lento per tutti, finché qualcuno sbaglia apposta)."""

import threading
import time
from collections import defaultdict, deque

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_failures: dict[str, deque[float]] = defaultdict(deque)


def _prune(attempts: deque[float], now: float) -> None:
    while attempts and attempts[0] <= now - WINDOW_SECONDS:
        attempts.popleft()


def retry_after(key: str, now: float | None = None) -> int | None:
    """Secondi da aspettare se il limite è raggiunto, se no None."""
    now = now if now is not None else time.monotonic()
    with _lock:
        attempts = _failures.get(key)
        if not attempts:
            return None
        _prune(attempts, now)
        if len(attempts) < MAX_FAILURES:
            return None
        return max(1, int(attempts[0] + WINDOW_SECONDS - now) + 1)


def failed(key: str, now: float | None = None) -> None:
    now = now if now is not None else time.monotonic()
    with _lock:
        attempts = _failures[key]
        _prune(attempts, now)
        attempts.append(now)


def succeeded(key: str) -> None:
    with _lock:
        _failures.pop(key, None)


def reset() -> None:
    with _lock:
        _failures.clear()
