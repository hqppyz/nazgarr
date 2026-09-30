"""Configurazione del logging.

Senza init esplicito, Python mostra di default solo WARNING+ (via
"handler of last resort") — ogni logger.info() sparso nel codice viene
scartato in silenzio, anche se la libreria è configurata correttamente.
Qui impostiamo un handler su stdout (Dozzle/`docker logs` lo leggono da
lì) con soglia configurabile via env LOG_LEVEL (default INFO)."""

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Credenziali che finiscono dentro gli URL e da lì nei log (httpx logga ogni
# richiesta, i traceback riportano l'URL): chiave nei link di download
# UNIT3D (/torrent/download/<id>.<rsskey>), passkey negli announce, token e
# api key nei parametri. I log si leggono dalla UI e si incollano in giro:
# mai una credenziale in chiaro, né su stdout né nel file.
_REDACTIONS = [
    (re.compile(r"(/torrent/download/\d+\.)[A-Za-z0-9]+"), r"\1<redacted>"),
    (re.compile(r"(/announce/)[A-Za-z0-9]{16,}"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(api_?token|api_?key|apikey|passkey|rsskey|torrent_pass|token)=[^&\s\"']+"), r"\1=<redacted>"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def safe_error(value) -> str:
    """Il testo di un errore da mostrare o salvare: le eccezioni di httpx
    contengono l'URL completo, con chiavi e passkey dentro."""
    return redact(str(value))


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(LOG_FORMAT, LOG_DATEFMT))
    root.handlers = [handler]

    # httpx/httpcore a DEBUG loggerebbero ogni singola richiesta/risposta
    # HTTP per esteso (comprese le chiamate a TMDB/tracker): mai più
    # verbosi di INFO anche se l'utente alza il livello generale a DEBUG.
    logging.getLogger("httpx").setLevel(max(level, logging.INFO))
    logging.getLogger("httpcore").setLevel(max(level, logging.WARNING))


def add_file_handler(log_dir: Path) -> None:
    """Aggiunge (accanto a quello stdout, non lo sostituisce) un handler su
    file rotante — serve solo a dare alla tab Logs della UI (Configuration >
    Logs, app/api/system.py) qualcosa da leggere senza bisogno del socket
    Docker. Chiamata dalla lifespan di app/main.py, dopo load_settings():
    data_dir non è ancora noto quando configure_logging() gira (import-time,
    prima della lifespan).

    Rimuove sempre prima l'eventuale handler aggiunto da una chiamata
    precedente: ogni riavvio della lifespan (uvicorn --reload, o la
    TestClient dei test che rientra nella lifespan a ogni fixture) altrimenti
    accumulerebbe un RotatingFileHandler aperto in più a ogni giro."""
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_nazgarr_file_handler", False):
            root.removeHandler(existing)
            existing.close()

    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=5_000_000, backupCount=3)
    handler.setFormatter(RedactingFormatter(LOG_FORMAT, LOG_DATEFMT))
    handler._nazgarr_file_handler = True
    root.addHandler(handler)
