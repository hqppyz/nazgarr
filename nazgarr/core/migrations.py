"""Aggiornamento del database all'avvio, con una versione (PRAGMA user_version).

Due tipi di passi:
- quelli che girano a ogni avvio, perché descrivono lo stato voluto e sono
  economici: lo schema di docs/schema.sql (CREATE ... IF NOT EXISTS), le
  colonne nuove dei modelli (db.migrate_schema) e la cifratura dei segreti
  rimasti in chiaro, una rete di sicurezza;
- quelli una tantum, numerati in MIGRATIONS: girano solo se la versione del
  DB è più bassa, e la versione sale quando tutti quelli in sospeso sono
  riusciti. Devono essere idempotenti: un avvio interrotto a metà li ripete.
  Un DB creato prima di questo modulo ha versione 0 e li ripete una volta,
  senza danni.

Per un cambiamento che apply_schema e migrate_schema non sanno fare
(rinominare o togliere una colonna, cambiare un vincolo, spostare dati):
una funzione idempotente in nazgarr/core/db.py e una riga nuova in fondo a
MIGRATIONS, col numero successivo. Mai rinumerare quelle già rilasciate.
Un passo che rifà una tabella lavora dentro db.rebuilding_tables (foreign
key spente fuori dalla transazione, tutto in una transazione, riaccese dopo
il commit) e fa prima DROP TABLE IF EXISTS della sua tabella temporanea:
così un avvio interrotto a metà si ripete senza danni. Per cambiare solo
le foreign key (un ON DELETE, una FK che manca) basta
db.rebuild_tables_from_schema, che rifà la tabella com'è in schema.sql
(passo 10).

Un passo che fallisce esce da upgrade come MigrationFailed, col numero e
il nome del passo (None per quelli di ogni avvio): l'avvio lo mostra
all'utente e resta in modalità di ripristino invece di ripartire in loop,
col backup fatto prima (nazgarr/core/db_startup.py, richiesta dell'utente
2026-10-22).
"""

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from nazgarr.core import db

logger = logging.getLogger(__name__)


def clean_stale_candidates(engine: Engine) -> dict[str, int]:
    """Una tantum (audit 2026-10-18): ogni ricerca riscriveva tutti i suoi
    risultati come candidate nuovi, e niente li toglieva. Per ogni torrent
    valutato per lo stesso contenuto, tracker e direzione resta la riga più
    recente; le altre vanno, coi loro candidate_file, solo se nessuna review
    e nessun seed_job le usa (seed_job.candidate_id è in cascata: si
    perderebbe la storia delle esecuzioni). Toglie anche la chiave dei link
    di download UNIT3D salvati in chiaro (nazgarr/reseed/download_links.py).
    Idempotente. Se ha tolto molto, compatta il file (VACUUM), se si può."""
    from nazgarr.reseed.download_links import strip_key

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS temp.stale_candidate")
        conn.exec_driver_sql("""
            CREATE TEMP TABLE stale_candidate AS
            SELECT id FROM (
                SELECT c.id, ROW_NUMBER() OVER (
                    PARTITION BY c.media_item_id, c.tracker_id, c.torrent_id_remote, c.direction
                    ORDER BY c.id DESC) AS position
                FROM candidate c
                WHERE NOT EXISTS (SELECT 1 FROM match_review r WHERE r.candidate_id = c.id)
                  AND NOT EXISTS (SELECT 1 FROM seed_job s WHERE s.candidate_id = c.id)
            ) WHERE position > 1
        """)
        conn.exec_driver_sql("DELETE FROM candidate_file WHERE candidate_id IN (SELECT id FROM temp.stale_candidate)")
        removed = conn.exec_driver_sql(
            "DELETE FROM candidate WHERE id IN (SELECT id FROM temp.stale_candidate)").rowcount or 0
        conn.exec_driver_sql("DROP TABLE temp.stale_candidate")
        remaining = conn.exec_driver_sql("SELECT count(*) FROM candidate").scalar() or 0
        keyed = conn.execute(text(
            "SELECT c.id, c.download_link FROM candidate c JOIN tracker t ON t.id = c.tracker_id "
            "WHERE t.adapter_type = 'unit3d' AND c.download_link LIKE '%/torrent/download/%'"
        )).all()
        stripped = 0
        for candidate_id, link in keyed:
            clean = strip_key(link)
            if clean != link:
                conn.execute(text("UPDATE candidate SET download_link = :link WHERE id = :id"),
                             {"link": clean, "id": candidate_id})
                stripped += 1
    if removed:
        logger.info("Database: %d candidati doppi tolti, %d restano", removed, remaining)
    if stripped:
        logger.info("Database: chiave tolta da %d link di download", stripped)
    if removed >= 10_000 and removed >= remaining:
        _vacuum(engine)
    return {"removed": removed, "stripped": stripped}


def strip_dupe_download_keys(engine: Engine) -> dict[str, int]:
    """Una tantum (audit 2026-10-18): il dupe check degli upload salvava in
    upload_target.dupes_json il link di download di ogni torrent trovato sul
    tracker con la chiave personale (rsskey) in chiaro. Ora si salva senza,
    e la chiave torna solo quando il full hash check o il reseed scaricano
    il .torrent (nazgarr/upload/verify.py dupe_torrent); qui si toglie dalle
    righe già salvate. Solo i tracker UNIT3D, come per i candidati (passo
    11): un plugin che non sa rimettere la chiave tiene il link com'è.
    Idempotente; una riga che non si legge resta com'è."""
    from nazgarr.reseed.download_links import strip_key

    stripped = 0
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT u.id, u.dupes_json FROM upload_target u JOIN tracker t ON t.id = u.tracker_id "
            "WHERE t.adapter_type = 'unit3d' AND u.dupes_json LIKE '%/torrent/download/%'"
        )).all()
        for target_id, raw in rows:
            try:
                dupes = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(dupes, list):
                continue
            changed = False
            for dupe in dupes:
                link = dupe.get("download_link") if isinstance(dupe, dict) else None
                if isinstance(link, str) and strip_key(link) != link:
                    dupe["download_link"] = strip_key(link)
                    changed = True
            if changed:
                conn.execute(text("UPDATE upload_target SET dupes_json = :dupes WHERE id = :id"),
                             {"dupes": json.dumps(dupes), "id": target_id})
                stripped += 1
    if stripped:
        logger.info("Database: chiave tolta dai link dei dupe di %d upload", stripped)
    return {"stripped": stripped}


# Gli stessi limiti dell'API (nazgarr/api/trackers.py, RATE_LIMIT_MAX): qui
# a mano, perché un passo già rilasciato non deve cambiare se cambia l'API.
_RATE_LIMIT_DEFAULT, _RATE_LIMIT_MAX = 30, 600


def normalize_tracker_rate_limits(engine: Engine) -> dict[str, int]:
    """Una tantum (audit 2026-10-18): prima dei limiti dell'API un tracker
    poteva salvare un rate_limit_per_min negativo, 0 con una PATCH, o
    enorme. Il limitatore ora tratta tutto sotto 1 come 1 (una richiesta al
    minuto, non quello che si voleva), e l'interfaccia mostrava e rimandava
    il valore salvato, che l'API rifiuta con 422 a ogni modifica del
    tracker. Sotto 1 diventa il default (30, come 0 alla creazione e nella
    PATCH), sopra il massimo il massimo. NULL resta: vale già 30.
    Idempotente."""
    with engine.begin() as conn:
        low = conn.execute(text(
            "UPDATE tracker SET rate_limit_per_min = :default WHERE rate_limit_per_min < 1"),
            {"default": _RATE_LIMIT_DEFAULT}).rowcount or 0
        high = conn.execute(text(
            "UPDATE tracker SET rate_limit_per_min = :max WHERE rate_limit_per_min > :max"),
            {"max": _RATE_LIMIT_MAX}).rowcount or 0
    if low or high:
        logger.info("Database: limite di richieste corretto per %d tracker", low + high)
    return {"defaulted": low, "capped": high}


def _vacuum(engine: Engine) -> None:
    """Restituisce al disco lo spazio delle righe tolte. Un di più: serve
    spazio libero quanto il database, e se manca l'avvio continua."""
    raw = engine.raw_connection()
    try:
        raw.cursor().execute("VACUUM")
        logger.info("Database compattato")
    except Exception as exc:  # qualunque errore: mai fermare l'avvio per questo
        logger.warning("Database non compattato (VACUUM): %s", exc)
    finally:
        raw.close()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    run: Callable[[Engine], object]
    # Prima dello schema: tabelle vecchie da rifare prima che apply_schema le
    # trovi già esistenti (non le toccherebbe). Dopo: dati da spostare in
    # tabelle o colonne che lo schema ha appena creato.
    before_schema: bool


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "media_file senza media_path_id", db.migrate_legacy_media_path_id, before_schema=True),
    Migration(2, "riparazione delle FK verso media_file_legacy", db.repair_dangling_media_file_legacy_fk,
              before_schema=True),
    Migration(3, "vincolo delle fasi di run_log", db.migrate_legacy_run_log_phase_check, before_schema=True),
    Migration(4, "upload_job della prima versione", db.migrate_legacy_upload_job, before_schema=True),
    Migration(5, "cartelle dei dischi in disk_folder", db.migrate_disk_folders, before_schema=False),
    Migration(6, "servizi di notifica come istanze", db.migrate_notification_services, before_schema=False),
    Migration(7, "host di immagini come plugin incluso", db.migrate_image_hosts_to_plugins, before_schema=False),
    Migration(8, "host di immagini spenti come plugin spenti", db.migrate_image_hosts_disabled_to_plugins,
              before_schema=False),
    Migration(9, "preset di esclusione nuovi attivi di default", db.migrate_new_default_exclusion_presets,
              before_schema=False),
    Migration(10, "azioni ON DELETE di candidate e seed_job, FK di upload_job.split_from_id",
              db.migrate_foreign_key_actions, before_schema=True),
    Migration(11, "candidati doppi tolti, link di download senza chiave", clean_stale_candidates,
              before_schema=False),
    Migration(12, "link dei dupe degli upload senza chiave", strip_dupe_download_keys, before_schema=False),
    Migration(13, "limite di richieste dei tracker entro i limiti dell'API", normalize_tracker_rate_limits,
              before_schema=False),
)

LATEST = MIGRATIONS[-1].version
assert [m.version for m in MIGRATIONS] == list(range(1, LATEST + 1)), "versioni in fila, senza buchi"


class MigrationFailed(RuntimeError):
    """Un passo dell'aggiornamento non è riuscito. step è il suo numero in
    MIGRATIONS, None per quelli che girano a ogni avvio (name è allora la
    funzione: migrate_schema, apply_schema...); start la versione da cui si
    partiva (None se non si è nemmeno letta). L'errore vero è __cause__."""

    def __init__(self, step: int | None, name: str, start: int | None):
        super().__init__(f"passo {step} ({name})" if step is not None else name)
        self.step, self.name, self.start = step, name, start


@contextmanager
def _step(step: int | None, name: str, start: int | None) -> Iterator[None]:
    try:
        yield
    except Exception as exc:  # qualunque errore del passo: lo si dice all'utente con il suo nome
        raise MigrationFailed(step, name, start) from exc


def current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA user_version")).scalar() or 0


def _set_version(engine: Engine, version: int) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {int(version)}"))


def _run(engine: Engine, migrations: list[Migration], start: int) -> None:
    for migration in migrations:
        logger.info("Database: migrazione %d (%s)", migration.version, migration.name)
        with _step(migration.version, migration.name, start):
            migration.run(engine)


def upgrade(engine: Engine) -> int:
    """Porta il DB all'ultima versione; restituisce la versione di partenza.
    Un passo che fallisce solleva MigrationFailed."""
    with _step(None, "user_version", None):
        start = current_version(engine)
    if start > LATEST:
        # Un DB di una versione più nuova di Nazgarr (un downgrade): lo schema
        # va comunque bene da leggere, ma nessun passo si riesegue.
        logger.warning("Database alla versione %d, più nuova di questo Nazgarr (%d)", start, LATEST)
    pending = [m for m in MIGRATIONS if m.version > start]
    _run(engine, [m for m in pending if m.before_schema], start)
    # Le colonne nuove prima dello schema: un indice di schema.sql può usare
    # una colonna che un DB più vecchio riceve solo da migrate_schema (per
    # esempio upload_job.split_from_id), e la sua CREATE INDEX fallirebbe.
    # Le tabelle che mancano le crea poi apply_schema, già complete.
    with _step(None, "migrate_schema", start):
        db.migrate_schema(engine)
    with _step(None, "apply_schema", start):
        db.apply_schema(engine)
    after = [m for m in pending if not m.before_schema]
    _run(engine, after, start)
    if after:
        with _step(None, "apply_schema", start):
            db.apply_schema(engine)  # una tabella rifatta perde i suoi indici: schema.sql li rimette
    with _step(None, "encrypt_plaintext_secrets", start):
        db.encrypt_plaintext_secrets(engine)
    if start < LATEST:
        with _step(None, "user_version", start):
            _set_version(engine, LATEST)
    db.refresh_planner_statistics(engine)  # solo con SQLite prima della 3.46
    # L'app parte con connessioni nuove, configurate da db._configure_sqlite
    # (foreign key accese), non con quelle passate per le migrazioni.
    engine.dispose()
    return start
