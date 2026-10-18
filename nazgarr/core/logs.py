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
from urllib.parse import urlsplit

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Credenziali che finiscono dentro gli URL e da lì nei log (httpx logga ogni
# richiesta, i traceback riportano l'URL): chiave nei link di download
# UNIT3D (/torrent/download/<id>.<rsskey>), passkey negli announce, token e
# api key nei parametri. I log si leggono dalla UI e si incollano in giro:
# mai una credenziale in chiaro, né su stdout né nel file.
# Anche nel percorso (audit 2026-10-18): il token del bot di Telegram
# (/bot<id>:<token>/sendMessage), quello di un webhook di Discord
# (/api/webhooks/<id>/<token>) e le credenziali dentro l'URL
# (https://utente:password@host, o un token da solo come in
# git+https://<PAT>@github.com/... nella lista dei plugin). Quello senza
# password viene dopo quello con: "utente:<redacted>" non lo ritocca.
_REDACTIONS = [
    (re.compile(r"(/torrent/download/\d+\.)[A-Za-z0-9]+"), r"\1<redacted>"),
    (re.compile(r"(/announce/)[A-Za-z0-9]{16,}"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(api_?token|api_?key|apikey|passkey|rsskey|torrent_pass|token)=[^&\s\"']+"), r"\1=<redacted>"),
    (re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+"), r"\1<redacted>"),
    (re.compile(r"(/webhooks/\d+/)[A-Za-z0-9_-]+"), r"\1<redacted>"),
    (re.compile(r"(://[^/@\s:\"']+:)[^@/\s\"']+@"), r"\1<redacted>@"),
    (re.compile(r"(://)[^/@\s:\"']+@"), r"\1<redacted>@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def safe_error(value) -> str:
    """Il testo di un errore da mostrare o salvare: le eccezioni di httpx
    contengono l'URL completo, con chiavi e passkey dentro."""
    return redact(str(value))


# Righe di librerie utili solo per capire un problema, non da leggere ogni
# giorno: da INFO passano a DEBUG ("Verbose" nella tab Logs). Il battito del
# pianificatore (due righe ogni 15 secondi per i webhook) si scarta del tutto,
# a meno che LOG_LEVEL non sia DEBUG.
_VERBOSE_LOGGERS = ("apscheduler", "httpx")


class VerbosityFilter(logging.Filter):
    def __init__(self, keep_heartbeat: bool = False):
        super().__init__()
        self.keep_heartbeat = keep_heartbeat

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO or not record.name.startswith(_VERBOSE_LOGGERS):
            return True
        if record.name == "apscheduler.executors.default" and not self.keep_heartbeat:
            message = record.getMessage()
            if message.startswith(("Running job", "Job ")) or "executed successfully" in message:
                return False
        record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        return True


class HttpxRequestFilter(logging.Filter):
    """La riga che httpx scrive per ogni richiesta ('HTTP Request: METODO
    URL "HTTP/1.1 200 OK"') con solo schema, host e porta dell'URL: percorso
    e parametri portano i segreti (il token di Telegram, di un webhook di
    Discord, quelli di un plugin), e per capire un problema bastano metodo,
    host e stato (audit 2026-10-18). Sul logger "httpx", prima di ogni
    handler: anche uno aggiunto dopo non vede l'URL intero."""

    def filter(self, record: logging.LogRecord) -> bool:
        if (isinstance(record.msg, str) and record.msg.startswith("HTTP Request:")
                and isinstance(record.args, tuple) and len(record.args) >= 2):
            args = list(record.args)
            args[1] = _origin(args[1])
            record.args = tuple(args)
        return True


def _origin(url) -> str:
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<url>"
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}{port}"


def _verbosity() -> VerbosityFilter:
    return VerbosityFilter(keep_heartbeat=logging.getLogger().level <= logging.DEBUG)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactingFilter(logging.Filter):
    """Per i logger di uvicorn, che non passano dagli handler di root: il log
    degli accessi ha il suo handler su stdout e propagate=False, e scriveva in
    chiaro un ?token= nell'URL (la password dei webhook di Radarr/Sonarr,
    audit 2026-10-18). Ripulisce messaggio e argomenti prima di ogni
    formatter; gli argomenti restano una tupla, perché l'AccessFormatter di
    uvicorn li spacchetta."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) if isinstance(arg, str) else arg for arg in record.args)
        return True


# Configurati da uvicorn (dictConfig) prima di importare l'app: un filtro sul
# logger resta anche se uvicorn ne rifà gli handler.
_UVICORN_LOGGERS = ("uvicorn.access", "uvicorn.error")


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(LOG_FORMAT, LOG_DATEFMT))
    handler.addFilter(_verbosity())
    root.handlers = [handler]
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactingFilter) for existing in logger.filters):
            logger.addFilter(RedactingFilter())

    # httpx/httpcore a DEBUG loggerebbero ogni singola richiesta/risposta
    # HTTP per esteso (comprese le chiamate a TMDB/tracker): mai più
    # verbosi di INFO anche se l'utente alza il livello generale a DEBUG.
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(max(level, logging.INFO))
    if not any(isinstance(existing, HttpxRequestFilter) for existing in httpx_logger.filters):
        httpx_logger.addFilter(HttpxRequestFilter())
    logging.getLogger("httpcore").setLevel(max(level, logging.WARNING))


def add_file_handler(log_dir: Path) -> None:
    """Aggiunge (accanto a quello stdout, non lo sostituisce) un handler su
    file rotante — serve solo a dare alla tab Logs della UI (Configuration >
    Logs, nazgarr/api/system.py) qualcosa da leggere senza bisogno del socket
    Docker. Chiamata dalla lifespan di nazgarr/main.py, dopo load_settings():
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
    handler = RotatingFileHandler(log_dir / "nazgarr.log", maxBytes=5_000_000, backupCount=3)
    handler.setFormatter(RedactingFormatter(LOG_FORMAT, LOG_DATEFMT))
    handler.addFilter(_verbosity())
    handler._nazgarr_file_handler = True
    root.addHandler(handler)
