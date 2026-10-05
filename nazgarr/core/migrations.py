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
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from nazgarr.core import db

logger = logging.getLogger(__name__)


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
)

LATEST = MIGRATIONS[-1].version
assert [m.version for m in MIGRATIONS] == list(range(1, LATEST + 1)), "versioni in fila, senza buchi"


def current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA user_version")).scalar() or 0


def _set_version(engine: Engine, version: int) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {int(version)}"))


def _run(engine: Engine, migrations: list[Migration]) -> None:
    for migration in migrations:
        logger.info("Database: migrazione %d (%s)", migration.version, migration.name)
        migration.run(engine)


def upgrade(engine: Engine) -> int:
    """Porta il DB all'ultima versione; restituisce la versione di partenza."""
    start = current_version(engine)
    if start > LATEST:
        # Un DB di una versione più nuova di Nazgarr (un downgrade): lo schema
        # va comunque bene da leggere, ma nessun passo si riesegue.
        logger.warning("Database alla versione %d, più nuova di questo Nazgarr (%d)", start, LATEST)
    pending = [m for m in MIGRATIONS if m.version > start]
    _run(engine, [m for m in pending if m.before_schema])
    db.apply_schema(engine)
    db.migrate_schema(engine)
    _run(engine, [m for m in pending if not m.before_schema])
    db.encrypt_plaintext_secrets(engine)
    if start < LATEST:
        _set_version(engine, LATEST)
    return start
