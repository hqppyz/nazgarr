"""La modalità di ripristino: l'aggiornamento del database (o il backup
prima) non è riuscito (nazgarr/core/db_startup.py, richiesta dell'utente
2026-10-22).

Il processo resta su invece di ripartire in loop, ma niente tocca il DB:
ogni richiesta si ferma qui, prima delle route. /api/health risponde 503
(l'HEALTHCHECK del container lo vede), le altre /api/* un 503 con un codice
che il CLI e le altre istanze traducono (database_update_failed,
database_backup_failed), tutto il resto una pagina che
dice cosa è successo, dov'è il backup e come ripristinarlo. Il login non
c'è: il database può essere a metà. Per questo la pagina è senza
autenticazione e dice solo il passo, la classe dell'errore, il nome del
backup e le cartelle; il messaggio e il traceback stanno nel log e in
migration-status.json.

Una pagina sola, senza script (la CSP non ne permette di inline) né file
del frontend, in italiano o in inglese secondo Accept-Language."""

from html import escape
from pathlib import Path

from starlette.responses import HTMLResponse, JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from nazgarr.core.db_startup import BACKUP_FAILED, LOCKED, STATUS_FILENAME, UNREADABLE
from nazgarr.core.errors import coded_detail
from nazgarr.core.mounts import in_container
from nazgarr.core.version import PROJECT_URL

ERROR_CODE = "database_update_failed"
BACKUP_ERROR_CODE = "database_backup_failed"
_NO_STORE = {"Cache-Control": "no-store"}
_CONTAINER_CONFIG = "/app/config"

_TEXT = {
    "en": {
        "title": "Nazgarr: database update failed",
        "heading_failed": "The database update did not finish",
        "heading_backup": "The database was not updated",
        "failed": "Nazgarr {version} stopped while updating its database, at {step}. To keep your data safe "
                  "nothing else was started: no scans, no uploads, no changes to your files or torrent clients. "
                  "Logging in is not possible until this is solved.",
        "step": "step {number} ({name})",
        "step_unnumbered": "the step {name}",
        "error": "Error: {error}",
        "backup_failed": "Before updating its database Nazgarr {version} makes a backup of it, and this time the "
                         "backup could not be made: {reason}. The database was not touched and nothing else was "
                         "started.",
        "reason_no_space": "there is not enough free space",
        "reason_io_error": "a read or write error",
        "reason_verification_failed": "the copy did not pass its check",
        "reason_database_unreadable": "the database itself cannot be read, it may be damaged",
        "unreadable_todo": "Restore a backup of the database: {list} lists the ones taken before earlier updates, "
                           "in {folder}, and {restore} puts one back (it works while this page is up). Or put back "
                           "your own backup of {db}.",
        "heading_locked": "Nazgarr could not read its database",
        "locked": "Another program holds a lock on the database of Nazgarr {version}: a second Nazgarr using the "
                  "same data folder, or a tool that has the file open. To keep it safe Nazgarr did not update it and "
                  "started nothing else.",
        "locked_todo": "Close the program that has {db} open (only one Nazgarr may use a data folder), then restart "
                       "Nazgarr.",
        "backup_is": "The backup taken right before the update is {file}, in {folder}.",
        "retry_is": "The database had changed since the first attempt of this update ({date}), so it was also copied "
                    "before trying again: {file}. Restore that one instead only if Nazgarr was used after the first "
                    "attempt, for example with the previous version.",
        "no_backup": "No backup was taken before this attempt (nothing in the database structure was due to change, "
                     "or NAZGARR_SKIP_MIGRATION_BACKUP was set). Restore your own backup if you have one.",
        "host_path": "The paths on this page are inside the container: on the host they are in the folder you "
                     "mounted as {config}.",
        "todo": "What to do",
        "restore_cli": "Restore the backup with {command}. It works while this page is up, keeps a copy of the "
                       "current database and checks the backup first.",
        "restore_hand": "Or by hand: stop Nazgarr, replace {db} in {folder} with the backup (renamed {db}) and "
                        "delete {wal}, {shm} and {status} if they are there.",
        "start_previous": "Then start the version you were using before the update (the backup has database "
                          "version {version}), or report the issue with the log on {link}.",
        "backup_todo": "Free some space on the disk of the data folder ({folder}) or fix the error in the log, "
                       "then restart Nazgarr. If you have your own backup and want to update anyway, set {env} for "
                       "one start.",
        "details": "The details of the error are in the log ({logs}) and in {status}.",
        "report": "GitHub",
    },
    "it": {
        "title": "Nazgarr: aggiornamento del database non riuscito",
        "heading_failed": "L'aggiornamento del database non è finito",
        "heading_backup": "Il database non è stato aggiornato",
        "failed": "Nazgarr {version} si è fermato mentre aggiornava il suo database, al {step}. Per non rischiare i "
                  "tuoi dati non è partito nient'altro: nessuna scansione, nessun upload, nessuna modifica ai file "
                  "o ai client torrent. Finché non si risolve non si può entrare.",
        "step": "passo {number} ({name})",
        "step_unnumbered": "passo {name}",
        "error": "Errore: {error}",
        "backup_failed": "Prima di aggiornare il database Nazgarr {version} ne fa un backup, e stavolta il backup "
                         "non si è potuto fare: {reason}. Il database non è stato toccato e non è partito "
                         "nient'altro.",
        "reason_no_space": "manca spazio libero",
        "reason_io_error": "un errore di lettura o scrittura",
        "reason_verification_failed": "la copia non ha passato il controllo",
        "reason_database_unreadable": "il database stesso non si legge, forse è rovinato",
        "unreadable_todo": "Ripristina un backup del database: {list} elenca quelli fatti prima degli aggiornamenti "
                           "precedenti, in {folder}, e {restore} ne rimette uno (funziona anche con questa pagina "
                           "aperta). Oppure rimetti un tuo backup di {db}.",
        "heading_locked": "Nazgarr non è riuscito a leggere il suo database",
        "locked": "Un altro programma tiene bloccato il database di Nazgarr {version}: un secondo Nazgarr sulla "
                  "stessa cartella dei dati, o uno strumento che ha il file aperto. Per non rischiarlo Nazgarr non "
                  "l'ha aggiornato e non ha avviato nient'altro.",
        "locked_todo": "Chiudi il programma che ha aperto {db} (una cartella dei dati può usarla un solo Nazgarr), "
                       "poi riavvia Nazgarr.",
        "backup_is": "Il backup fatto subito prima dell'aggiornamento è {file}, in {folder}.",
        "retry_is": "Dal primo tentativo di questo aggiornamento ({date}) il database era cambiato, quindi prima di "
                    "riprovare è stato copiato di nuovo: {file}. Ripristina quello invece solo se Nazgarr è stato "
                    "usato dopo il primo tentativo, per esempio con la versione di prima.",
        "no_backup": "Prima di questo tentativo non è stato fatto nessun backup (la struttura del database non "
                     "doveva cambiare, o era impostato NAZGARR_SKIP_MIGRATION_BACKUP). Ripristina un tuo backup, se "
                     "ce l'hai.",
        "host_path": "I percorsi di questa pagina sono dentro il container: sull'host sono nella cartella che hai "
                     "montato come {config}.",
        "todo": "Cosa fare",
        "restore_cli": "Ripristina il backup con {command}. Funziona anche con questa pagina aperta, tiene una "
                       "copia del database di adesso e prima controlla il backup.",
        "restore_hand": "Oppure a mano: ferma Nazgarr, sostituisci {db} in {folder} con il backup (rinominato {db}) "
                        "e cancella {wal}, {shm} e {status} se ci sono.",
        "start_previous": "Poi avvia la versione che usavi prima dell'aggiornamento (il backup ha il database alla "
                          "versione {version}), oppure segnala il problema con il log su {link}.",
        "backup_todo": "Libera spazio sul disco della cartella dei dati ({folder}) o correggi l'errore che trovi "
                       "nel log, poi riavvia Nazgarr. Se hai un tuo backup e vuoi aggiornare lo stesso, imposta {env} "
                       "per un avvio.",
        "details": "I dettagli dell'errore sono nel log ({logs}) e in {status}.",
        "report": "GitHub",
    },
}

_STYLE = """
:root { color-scheme: light dark; --bg: #f7f7f5; --fg: #1c1c1a; --muted: #5d5d58; --card: #ffffff;
        --border: #e2e2dc; --accent: #b8860b; --code: #efefea; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #121211; --fg: #ececea; --muted: #a3a39d; --card: #1b1b19; --border: #2e2e2b;
          --accent: #d4a537; --code: #26261f; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); line-height: 1.55;
       font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 44rem; margin: 0 auto; padding: 3rem 1rem; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }
.ring { width: 2.5rem; height: 2.5rem; border-radius: 50%; border: 5px solid var(--accent); margin-bottom: 1rem; }
h1 { font-size: 1.4rem; margin: 0 0 1rem; }
h2 { font-size: 1.05rem; margin: 1.5rem 0 .5rem; }
p, li { margin: .5rem 0; }
ol { padding-left: 1.25rem; }
code { background: var(--code); border-radius: 4px; padding: .1rem .3rem; word-break: break-all;
       font: .9em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.muted { color: var(--muted); font-size: .9rem; }
a { color: var(--accent); }
"""


def _language(header: str | None) -> str:
    """it o en, la prima delle due per qualità in Accept-Language; en se non
    c'è nessuna delle due."""
    best, best_q = "en", -1.0
    for part in (header or "").split(","):
        tag, _, params = part.strip().partition(";")
        quality = 1.0
        params = params.strip()
        if params.startswith("q="):
            try:
                quality = float(params[2:])
            except ValueError:
                quality = 0.0
        primary = tag.strip().lower().split("-")[0]
        if primary in _TEXT and quality > best_q:
            best, best_q = primary, quality
    return best


def _code(value: object) -> str:
    return f"<code>{escape(str(value))}</code>"


def _error_class(status: dict) -> str:
    """Solo la classe dell'errore (prima dei due punti): il messaggio può
    contenere dati, e la pagina si vede senza login."""
    return str(status.get("error") or "").split(":", 1)[0].strip()


def _backup_paragraphs(text: dict, status: dict, folder: str, data_dir: str, db_name: str, container: bool,
                       link: str) -> tuple[list[str], list[str]]:
    """Il backup di prima dell'aggiornamento (e la copia pre-retry, se c'è)
    e come ripristinarlo."""
    paragraphs: list[str] = []
    todo: list[str] = []
    backup, retry = status.get("backup"), status.get("retry_backup")
    prefix = "docker exec -it nazgarr " if container else ""
    if backup:
        backup_name = Path(str(backup)).name
        paragraphs.append(text["backup_is"].format(file=_code(backup_name), folder=_code(folder)))
        todo.append(text["restore_cli"].format(command=_code(f"{prefix}nazgarr db restore {backup_name}")))
        todo.append(text["restore_hand"].format(db=_code(db_name), folder=_code(data_dir), wal=_code(f"{db_name}-wal"),
                                                shm=_code(f"{db_name}-shm"), status=_code(STATUS_FILENAME)))
    else:
        paragraphs.append(text["no_backup"])
    if retry:
        paragraphs.append(text["retry_is"].format(file=_code(Path(str(retry)).name),
                                                  date=escape(str(status.get("started_at") or "?"))))
    todo.append(text["start_previous"].format(version=escape(str(status.get("from_version"))), link=link))
    return paragraphs, todo


def render_page(status: dict, language: str = "en") -> str:
    text = _TEXT.get(language, _TEXT["en"])
    database = Path(str(status.get("database") or "nazgarr.db"))
    data_dir = str(database.parent)
    db_name = database.name
    folder = str(status.get("backups_dir") or Path(data_dir) / "backups")
    version = escape(str(status.get("app_version") or ""))
    container = in_container()
    host_note = ""
    if container and data_dir.startswith(_CONTAINER_CONFIG):
        host_note = f'<p class="muted">{text["host_path"].format(config=_code(_CONTAINER_CONFIG))}</p>'
    link = f'<a href="{escape(PROJECT_URL)}/issues">{text["report"]}</a>'
    prefix = "docker exec -it nazgarr " if container else ""
    paragraphs: list[str] = []
    todo: list[str] = []
    if status.get("status") == BACKUP_FAILED and status.get("reason") == LOCKED:
        heading = text["heading_locked"]
        paragraphs.append(text["locked"].format(version=version))
        todo.append(text["locked_todo"].format(db=_code(db_name)))
    elif status.get("status") == BACKUP_FAILED:
        heading = text["heading_backup"]
        reason = text.get(f"reason_{status.get('reason')}", text["reason_io_error"])
        paragraphs.append(text["backup_failed"].format(version=version, reason=escape(reason)))
        if status.get("reason") == UNREADABLE and status.get("backup"):
            # Il database lasciato da un aggiornamento interrotto: il backup è quello di prima.
            more, todo = _backup_paragraphs(text, status, folder, data_dir, db_name, container, link)
            paragraphs += more
        elif status.get("reason") == UNREADABLE:
            todo.append(text["unreadable_todo"].format(
                list=_code(f"{prefix}nazgarr db backups"), restore=_code(f"{prefix}nazgarr db restore <file>"),
                folder=_code(folder), db=_code(db_name)))
        else:
            todo.append(text["backup_todo"].format(folder=_code(data_dir),
                                                   env=_code("NAZGARR_SKIP_MIGRATION_BACKUP=1")))
    else:
        heading = text["heading_failed"]
        name = escape(str(status.get("step_name") or ""))
        step = (text["step"].format(number=escape(str(status["step"])), name=name) if status.get("step") is not None
                else text["step_unnumbered"].format(name=name))
        paragraphs.append(text["failed"].format(version=version, step=step))
        if _error_class(status):
            paragraphs.append(text["error"].format(error=_code(_error_class(status))))
        more, todo = _backup_paragraphs(text, status, folder, data_dir, db_name, container, link)
        paragraphs += more
    logs = "docker logs nazgarr" if container else str(Path(data_dir) / "logs")
    details = text["details"].format(logs=_code(logs), status=_code(Path(data_dir) / STATUS_FILENAME))
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    steps = "".join(f"<li>{item}</li>" for item in todo)
    return (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(text['title'])}</title><style>{_STYLE}</style></head>"
        f'<body><main><div class="card"><div class="ring" aria-hidden="true"></div><h1>{escape(heading)}</h1>'
        f"{body}<h2>{text['todo']}</h2><ol>{steps}</ol>"
        f'<p class="muted">{details}</p>{host_note}</div></main></body></html>'
    )


def _detail(status: dict) -> dict:
    """Il codice per il CLI e l'interfaccia (frontend/src/locales/*/errors.ts):
    uno per caso, con parametri che hanno sempre un valore."""
    if status.get("status") == BACKUP_FAILED:
        return coded_detail(BACKUP_ERROR_CODE, reason=status.get("reason"))
    backup = status.get("backup")
    return coded_detail(ERROR_CODE, step=status.get("step"), step_name=status.get("step_name"),
                        backup=Path(str(backup)).name if backup else None)


def response_for(status: dict, path: str, accept_language: str | None):
    if path == "/api/health":
        return JSONResponse({"status": _detail(status)["code"], "version": None, "commit": None}, status_code=503,
                            headers=_NO_STORE)
    if path == "/api" or path.startswith("/api/"):
        return JSONResponse({"detail": _detail(status)}, status_code=503, headers=_NO_STORE)
    return HTMLResponse(render_page(status, _language(accept_language)), status_code=503, headers=_NO_STORE)


class RecoveryMiddleware:
    """Dentro le altre (gli header di sicurezza valgono anche qui), prima
    delle route. Lo stato è app.state.recovery, che la lifespan imposta
    (nazgarr/main.py): None quando tutto va."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        status = None
        if scope["type"] == "http":
            status = getattr(getattr(scope.get("app"), "state", None), "recovery", None)
        if status is None:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        language = headers.get(b"accept-language", b"").decode("latin-1")
        await response_for(status, scope["path"], language)(scope, receive, send)
