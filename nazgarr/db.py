"""Engine SQLAlchemy + applicazione dello schema.

Convenzione del progetto (docs/ROADMAP.md, Fase 0): docs/schema.sql è la
fonte di verità per la DDL. Non usiamo Base.metadata.create_all() per non
duplicare/divergere dallo schema: allo startup eseguiamo schema.sql
direttamente (le CREATE TABLE sono idempotenti, IF NOT EXISTS) — comprese
le tabelle non ancora usate dall'app in questa fase (matching/upload
arrivano rispettivamente in Fase 4 e Fase 6, ma le loro tabelle esistono
già da subito, vuote, senza bisogno di un secondo schema). I modelli in
nazgarr/models.py mappano via ORM solo le tabelle già rilevanti per la fase
corrente, e crescono di pari passo con le fasi successive.

CREATE TABLE IF NOT EXISTS crea le tabelle mancanti ma non tocca quelle
già esistenti: una colonna additiva aggiunta a un modello dopo che un
utente ha già un DB reale non comparirebbe mai sul suo DB solo con
apply_schema(). migrate_schema() colma questo gap confrontando le colonne
attese (dai modelli SQLAlchemy) con quelle realmente presenti e
aggiungendo quelle mancanti via ALTER TABLE — va chiamata sempre, ad ogni
avvio, dopo apply_schema(). Stesso pattern di ratio-guardian/app/db.py.

migrate_legacy_media_path_id() copre l'unico caso finora in cui questo
schema è cambiato in un modo che apply_schema()/migrate_schema() non
sanno gestire: il commit 5fd42fc ha eliminato la tabella media_path e la
sua FK NOT NULL media_file.media_path_id, sostituendole con
disk.media_rel_path. Un DB creato PRIMA di quel commit conserva ancora
la vecchia forma (la CREATE TABLE IF NOT EXISTS di apply_schema non
tocca una tabella già esistente, e migrate_schema sa solo aggiungere
colonne, mai rimuoverle) — ogni scan da allora falliva silenziosamente
al primo INSERT in media_file, perché il codice attuale non valorizza
più quella colonna (bug riportato dall'utente sulla sua istanza Unraid
reale, con dati che NON si possono semplicemente ricreare da zero come
si è sempre fatto finora per un'istanza di sviluppo).

ATTENZIONE per chiunque tocchi ancora questa funzione: la prima versione
faceva ALTER TABLE media_file RENAME TO media_file_legacy prima di
ricrearla. Verificato con un test diretto (dopo un secondo report
dell'utente, "no such table: media_file_legacy" stavolta su un INSERT in
seed_file): SQLite riscrive le REFERENCES di OGNI altra tabella verso
quella rinominata IN OGNI CASO, non solo con le foreign key attive — la
PRAGMA foreign_keys=OFF non previene affatto questo comportamento, solo
la sua enforcement sulle scritture. Dopo il DROP TABLE finale della
tabella rinominata, ogni tabella con una FK verso media_file(id)
(seed_file/match_review/seed_job/upload_job) restava agganciata per
sempre a un nome ormai inesistente. La versione qui sotto non rinomina
MAI la tabella già referenziata: crea la forma corretta sotto un nome
temporaneo, copia i dati, fa DROP (non RENAME) dell'originale, e solo
allora rinomina il nome temporaneo in quello finale — un RENAME verso un
nome che nessuno referenzia ancora non fa scattare alcuna riscrittura.
repair_dangling_media_file_legacy_fk() ripara chi ha già subito il danno
della prima versione."""

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# Nel repository (sviluppo, Docker) docs/schema.sql; nel pacchetto Python
# installato con pipx (scripts/build_package.sh) la sua copia in nazgarr/_assets.
_REPO_SCHEMA = Path(__file__).resolve().parent.parent / "docs" / "schema.sql"
SCHEMA_PATH = _REPO_SCHEMA if _REPO_SCHEMA.exists() else Path(__file__).resolve().parent / "_assets" / "schema.sql"


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL invece del rollback journal di default: i lettori (es. il
    # polling dello stato live di una run, a partire dalla Fase 5) non
    # vengono bloccati da uno scrittore concorrente (lo scan in corso).
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def migrate_legacy_db_filename(data_dir: str) -> str | None:
    """Rename del progetto (Gauntletarr -> Nazgarr): il database si chiamava
    gauntletarr.db. Se c'è solo quello, viene rinominato (con i file -wal/
    -shm di SQLite, se presenti) prima di aprire qualunque connessione: senza,
    l'app partirebbe con un database vuoto e sembrerebbe aver perso tutto.
    Se esistono entrambi non si tocca niente e vale quello nuovo (un rename
    già fatto, o un database nuovo creato apposta): solo un avviso nei log.
    Restituisce il percorso rinominato, None se non c'era niente da fare."""
    from nazgarr.config import DB_FILENAME, LEGACY_DB_FILENAME

    legacy = Path(data_dir) / LEGACY_DB_FILENAME
    current = Path(data_dir) / DB_FILENAME
    if not legacy.exists():
        return None
    if current.exists():
        logger.warning("Trovati sia %s sia %s: uso %s, il vecchio resta com'è", legacy, current, current)
        return None
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{legacy}{suffix}")
        if sidecar.exists():
            os.replace(sidecar, f"{current}{suffix}")
    os.replace(legacy, current)
    logger.info("Database rinominato: %s -> %s", legacy, current)
    return str(current)


def make_engine(db_path: str) -> Engine:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})


def migrate_legacy_media_path_id(engine: Engine) -> None:
    """Ricostruisce media_file senza la colonna legacy media_path_id, se
    presente — vedi la nota in cima al file. Va chiamata PRIMA di
    apply_schema(): quest'ultima non ricrea mai una tabella già esistente,
    quindi deve trovare media_file già nella forma corretta (o assente) per
    poterla lasciare stare.

    Mai un RENAME sulla media_file originale (vedi il warning in cima al
    file sul perché) — si crea invece media_file__rebuild già nella forma
    giusta, si copiano i dati (stessi id delle righe originali: le FK di
    seed_file/match_review/seed_job/upload_job restano valide), si fa DROP
    (non RENAME) dell'originale, e solo allora si rinomina
    media_file__rebuild in media_file."""
    inspector = inspect(engine)
    if not inspector.has_table("media_file"):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("media_file")}
    if "media_path_id" not in existing_columns:
        return

    logger.warning(
        "Migrazione legacy: media_file.media_path_id (pre-5fd42fc) rimosso, "
        "dati preservati con gli stessi id"
    )
    raw_conn = engine.raw_connection()
    try:
        raw_conn.executescript("""
            PRAGMA foreign_keys=OFF;
            CREATE TABLE media_file__rebuild (
                id                      INTEGER PRIMARY KEY,
                disk_id                 INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
                relative_path           TEXT NOT NULL,
                size_bytes              INTEGER NOT NULL,
                st_dev                  INTEGER NOT NULL,
                inode                   INTEGER NOT NULL,
                nlink                   INTEGER,
                content_hash            TEXT,
                media_item_id           INTEGER REFERENCES media_item(id) ON DELETE SET NULL,
                resolver_source         TEXT,
                mediainfo_unique_id     TEXT,
                last_scan_id            INTEGER NOT NULL REFERENCES run_log(id),
                last_seen_at            TIMESTAMP NOT NULL,
                UNIQUE(disk_id, relative_path)
            );
            INSERT INTO media_file__rebuild (
                id, disk_id, relative_path, size_bytes, st_dev, inode, nlink,
                content_hash, media_item_id, resolver_source, mediainfo_unique_id,
                last_scan_id, last_seen_at
            )
            SELECT
                id, disk_id, relative_path, size_bytes, st_dev, inode, nlink,
                content_hash, media_item_id, resolver_source, mediainfo_unique_id,
                last_scan_id, last_seen_at
            FROM media_file;
            DROP TABLE media_file;
            ALTER TABLE media_file__rebuild RENAME TO media_file;
            DROP TABLE IF EXISTS media_path;
            CREATE INDEX IF NOT EXISTS idx_media_file_media_item_id ON media_file(media_item_id);
            CREATE INDEX IF NOT EXISTS idx_media_file_hardlink ON media_file(disk_id, st_dev, inode);
            PRAGMA foreign_keys=ON;
        """)
        raw_conn.commit()
    finally:
        raw_conn.close()


# Le uniche 4 tabelle con una FK diretta verso media_file(id) — vedi
# `grep -n "REFERENCES media_file(id)" docs/schema.sql`. Se schema.sql
# cambia queste tabelle, va tenuta manualmente in sync anche questa (stessa
# convenzione di nazgarr/models.py rispetto a schema.sql).
_LEGACY_MEDIA_FILE_FK_REBUILD: dict[str, tuple[str, list[str]]] = {
    "seed_file": (
        """
        CREATE TABLE seed_file__rebuild (
            id              INTEGER PRIMARY KEY,
            disk_id         INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
            relative_path   TEXT NOT NULL,
            size_bytes      INTEGER NOT NULL,
            st_dev          INTEGER NOT NULL,
            inode           INTEGER NOT NULL,
            media_file_id   INTEGER REFERENCES media_file(id) ON DELETE SET NULL,
            last_scan_id    INTEGER NOT NULL REFERENCES run_log(id),
            last_seen_at    TIMESTAMP NOT NULL,
            UNIQUE(disk_id, relative_path)
        )
        """,
        [
            "CREATE INDEX IF NOT EXISTS idx_seed_file_media_file_id ON seed_file(media_file_id)",
            "CREATE INDEX IF NOT EXISTS idx_seed_file_hardlink ON seed_file(disk_id, st_dev, inode)",
        ],
    ),
    "match_review": (
        """
        CREATE TABLE match_review__rebuild (
            id              INTEGER PRIMARY KEY,
            candidate_id    INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
            media_file_id   INTEGER REFERENCES media_file(id) ON DELETE CASCADE,
            seed_file_id    INTEGER REFERENCES seed_file(id) ON DELETE CASCADE,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','approved','rejected','auto_approved')),
            decided_by      TEXT,
            decided_at      TIMESTAMP
        )
        """,
        [
            "CREATE INDEX IF NOT EXISTS idx_match_review_candidate_id ON match_review(candidate_id)",
            "CREATE INDEX IF NOT EXISTS idx_match_review_media_file_id ON match_review(media_file_id)",
            "CREATE INDEX IF NOT EXISTS idx_match_review_seed_file_id ON match_review(seed_file_id)",
        ],
    ),
    "seed_job": (
        """
        CREATE TABLE seed_job__rebuild (
            id                          INTEGER PRIMARY KEY,
            candidate_id                INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
            source_media_file_id        INTEGER REFERENCES media_file(id),
            source_seed_file_id         INTEGER REFERENCES seed_file(id),
            result_seed_file_id         INTEGER REFERENCES seed_file(id),
            result_client_torrent_id    INTEGER REFERENCES client_torrent(id),
            info_hash                   TEXT,
            hardlink_created_at         TIMESTAMP,
            torrent_added_at            TIMESTAMP,
            recheck_status               TEXT CHECK (recheck_status IN ('pending','ok','failed')),
            final_status                 TEXT NOT NULL DEFAULT 'in_progress'
                                         CHECK (final_status IN ('in_progress','seeding','failed','rolled_back')),
            error_message                TEXT
        )
        """,
        [
            "CREATE INDEX IF NOT EXISTS idx_seed_job_candidate_id ON seed_job(candidate_id)",
            "CREATE INDEX IF NOT EXISTS idx_seed_job_source_media_file_id ON seed_job(source_media_file_id)",
            "CREATE INDEX IF NOT EXISTS idx_seed_job_source_seed_file_id ON seed_job(source_seed_file_id)",
        ],
    ),
    "upload_job": (
        """
        CREATE TABLE upload_job__rebuild (
            id                      INTEGER PRIMARY KEY,
            media_file_id           INTEGER REFERENCES media_file(id),
            source_path             TEXT NOT NULL,
            tracker_id              INTEGER NOT NULL REFERENCES tracker(id),
            status                  TEXT NOT NULL DEFAULT 'draft'
                                    CHECK (status IN ('draft','ready','uploading','uploaded','failed')),
            torrent_path            TEXT,
            info_hash               TEXT,
            mediainfo_text           TEXT,
            screenshot_urls_json      TEXT,
            description_rendered      TEXT,
            tmdb_id                  INTEGER,
            imdb_id                  TEXT,
            category_id               INTEGER,
            type_id                   INTEGER,
            resolution_id              INTEGER,
            torrent_id_remote          TEXT,
            error_message               TEXT,
            created_at                   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        [
            "CREATE INDEX IF NOT EXISTS idx_upload_job_tracker_id ON upload_job(tracker_id)",
        ],
    ),
}


def repair_dangling_media_file_legacy_fk(engine: Engine) -> None:
    """Ripara il danno lasciato da una versione precedente e sbagliata di
    migrate_legacy_media_path_id() — vedi il warning in cima al file.
    Rileva ogni tabella la cui definizione (sqlite_master.sql) contiene
    ancora il testo "media_file_legacy" e la ricostruisce puntando di
    nuovo a "media_file", con la stessa tecnica sicura (mai un RENAME
    sulla tabella già referenziata da qualcun altro — crea la forma
    corretta sotto un nome temporaneo, copia i dati, DROP dell'originale,
    poi rinomina). Va chiamata subito dopo migrate_legacy_media_path_id(),
    prima di apply_schema(). No-op se non c'è nulla da riparare
    (installazioni mai toccate dal bug precedente, o già riparate)."""
    if not inspect(engine).has_table("media_file"):
        return

    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        found = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%media_file_legacy%'"
            ).fetchall()
        }
        broken_tables = [name for name in _LEGACY_MEDIA_FILE_FK_REBUILD if name in found]
        unexpected = found - set(broken_tables)
        if unexpected:
            logger.warning(
                "Riferimenti a media_file_legacy trovati in tabelle non previste, ignorate: %s",
                sorted(unexpected),
            )
        if not broken_tables:
            return

        logger.warning(
            "Riparo %d tabell%s con una FK ancora agganciata a media_file_legacy: %s",
            len(broken_tables), "a" if len(broken_tables) == 1 else "e", broken_tables,
        )
        cursor.execute("PRAGMA foreign_keys=OFF")
        for table in broken_tables:
            create_sql, index_sqls = _LEGACY_MEDIA_FILE_FK_REBUILD[table]
            columns = [col[1] for col in cursor.execute(f'PRAGMA table_info("{table}")').fetchall()]
            column_list = ", ".join(f'"{c}"' for c in columns)
            cursor.execute(create_sql)
            cursor.execute(f'INSERT INTO "{table}__rebuild" ({column_list}) SELECT {column_list} FROM "{table}"')
            cursor.execute(f'DROP TABLE "{table}"')
            cursor.execute(f'ALTER TABLE "{table}__rebuild" RENAME TO "{table}"')
            for index_sql in index_sqls:
                cursor.execute(index_sql)
        cursor.execute("PRAGMA foreign_keys=ON")
        raw_conn.commit()
    finally:
        raw_conn.close()


def migrate_legacy_run_log_phase_check(engine: Engine) -> None:
    """Stesso problema di migrate_legacy_media_path_id(), stavolta sul CHECK
    di run_log.current_phase: il commit 1149b94 (fase corrente in questa
    sessione) ha esteso i valori ammessi da ('scanning','matching',
    'executing') a includere anche 'resolving'/'indexing'/'reconciling",
    per riflettere le fasi reali della pipeline (nazgarr/pipeline.py). Un DB
    creato prima di quel commit (come quello pre-5fd42fc dell'utente)
    conserva il vecchio CHECK più stretto — apply_schema()/migrate_schema()
    non lo toccano per lo stesso motivo di sempre (CREATE TABLE IF NOT
    EXISTS non tocca una tabella già esistente, e un ALTER TABLE non può
    modificare un CHECK in SQLite). Scoperto verificando dal vivo la
    migrazione precedente: con media_file/seed_file finalmente
    funzionanti, la primissima transizione di fase successiva a
    "scanning" (_set_phase(session, run, "resolving")) avrebbe fatto
    fallire di nuovo la run, stavolta con
    "CHECK constraint failed: current_phase IN (...)" — mai arrivato a
    riprodursi sull'istanza reale dell'utente solo perché lo scan falliva
    prima ancora di arrivarci.

    Stessa tecnica sicura delle altre due migrazioni sopra: mai un RENAME
    sulla run_log originale (referenziata da media_file/seed_file/
    client_torrent_file.last_scan_id) — si crea la forma corretta sotto un
    nome temporaneo, si copiano i dati con gli id originali, si fa DROP
    (non RENAME) dell'originale, poi si rinomina."""
    inspector = inspect(engine)
    if not inspector.has_table("run_log"):
        return
    with engine.connect() as conn:
        current_sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='run_log'")
        ).scalar()
    if current_sql is None or "reconciling" in current_sql:
        return  # già nella forma corrente

    logger.warning(
        "Migrazione legacy: run_log.current_phase esteso a 'resolving'/'indexing'/'reconciling' "
        "(pre-1149b94), dati preservati con gli stessi id"
    )
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        source_columns = [row[1] for row in cursor.execute("PRAGMA table_info(run_log)").fetchall()]
        cursor.execute("""
            CREATE TABLE run_log__rebuild (
                id                  INTEGER PRIMARY KEY,
                run_type            TEXT NOT NULL CHECK (run_type IN ('scheduled','manual','bulk_import')),
                started_at          TIMESTAMP NOT NULL,
                finished_at         TIMESTAMP,
                current_phase       TEXT CHECK (current_phase IN
                                        ('scanning','resolving','indexing','matching','executing','reconciling')),
                phase_total         INTEGER,
                phase_done          INTEGER,
                items_total         INTEGER,
                items_scanned       INTEGER DEFAULT 0,
                matches_found        INTEGER DEFAULT 0,
                auto_executed         INTEGER DEFAULT 0,
                pending_review       INTEGER DEFAULT 0,
                orphan_torrent_count  INTEGER DEFAULT 0,
                ignored_count         INTEGER DEFAULT 0,
                health_snapshot       REAL,
                errors                INTEGER DEFAULT 0,
                last_error            TEXT
            )
        """)
        column_list = ", ".join(f'"{c}"' for c in source_columns)
        cursor.execute(f'INSERT INTO run_log__rebuild ({column_list}) SELECT {column_list} FROM run_log')
        cursor.execute("DROP TABLE run_log")
        cursor.execute("ALTER TABLE run_log__rebuild RENAME TO run_log")
        cursor.execute("PRAGMA foreign_keys=ON")
        raw_conn.commit()
    finally:
        raw_conn.close()


def migrate_legacy_upload_job(engine: Engine) -> None:
    """Flusso di upload v2 (docs/SPEC.md §9): upload_job non è più "un file
    verso un tracker" ma la sorgente di N upload_target. La tabella della
    Fase 6 (riconoscibile dalla colonna tracker_id) viene eliminata, senza
    copiare niente: decisione dell'utente, nessun upload reale da tenere.
    Nessun'altra tabella la referenzia, quindi un DROP basta; va chiamata
    prima di apply_schema(), che poi crea la forma nuova."""
    inspector = inspect(engine)
    if not inspector.has_table("upload_job"):
        return
    if "tracker_id" not in {col["name"] for col in inspector.get_columns("upload_job")}:
        return
    logger.warning("Migrazione: upload_job della Fase 6 eliminata, sostituita dal flusso di upload v2")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE upload_job"))


def apply_schema(engine: Engine, schema_path: Path = SCHEMA_PATH) -> None:
    schema_sql = schema_path.read_text()
    raw_conn = engine.raw_connection()
    try:
        raw_conn.executescript(schema_sql)
        raw_conn.commit()
    finally:
        raw_conn.close()


def migrate_schema(engine: Engine) -> None:
    """Aggiunge alle tabelle già esistenti le colonne presenti nei modelli
    ma non ancora nel DB reale (vedi nota in cima al file). Gestisce solo
    aggiunte additive di colonne nullable senza server_default — l'unico
    tipo di modifica che questo progetto si è finora impegnato a fare."""
    from nazgarr.models import Base  # import qui: evita un ciclo db<->models

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # tabella nuova: apply_schema l'ha già creata per intero
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=conn.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def migrate_disk_folders(engine: Engine) -> int:
    """La cartella media e quella di seeding di un disco (disk.media_rel_path,
    disk.torrents_rel_path) diventano righe di disk_folder, che ne ammette
    più di una (decisione dell'utente, 2026-10-03), e le colonne vecchie
    vengono azzerate: così togliere tutte le cartelle dalla UI non le fa
    ricomparire al riavvio. Idempotente. Restituisce le cartelle spostate."""
    moved = 0
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, media_rel_path, torrents_rel_path FROM disk "
            "WHERE media_rel_path IS NOT NULL OR torrents_rel_path IS NOT NULL"
        )).all()
        for disk_id, media, seeding in rows:
            for kind, path in (("media", media), ("seeding", seeding)):
                if not path:
                    continue
                conn.execute(text(
                    "INSERT OR IGNORE INTO disk_folder (disk_id, kind, relative_path) VALUES (:d, :k, :p)"
                ), {"d": disk_id, "k": kind, "p": path})
                moved += 1
            conn.execute(text("UPDATE disk SET media_rel_path = NULL, torrents_rel_path = NULL WHERE id = :d"),
                         {"d": disk_id})
    return moved


# Colonne diventate cifrate (EncryptedString) dopo che c'erano già dati.
_NOW_ENCRYPTED = (("tracker", "announce_url"), ("tracker", "history_session_cookie"))


def encrypt_plaintext_secrets(engine: Engine) -> int:
    """All'avvio, una volta: cifra i segreti che erano in chiaro nel DB (la
    passkey negli announce, il cookie dello storico, le chiavi API nelle
    impostazioni) e toglie la passkey dagli announce dei torrent dei client,
    di cui serve solo l'host. Idempotente: un valore già cifrato non si tocca.
    Restituisce quanti valori ha cambiato."""
    from nazgarr import crypto, settings_repo
    from nazgarr.torrent_indexer import announce_origin

    changed = 0
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column in _NOW_ENCRYPTED:
            if not inspector.has_table(table):
                continue
            query = text(f'SELECT id, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL')
            for row_id, value in conn.execute(query):
                try:
                    crypto.decrypt(value)
                    continue  # già cifrato
                except ValueError:
                    pass
                conn.execute(text(f'UPDATE "{table}" SET "{column}" = :v WHERE id = :id'),
                             {"v": crypto.encrypt(value), "id": row_id})
                changed += 1
        if inspector.has_table("app_settings"):
            for key, value in conn.execute(text("SELECT key, value FROM app_settings")):
                stored = settings_repo.encode(key, value)
                if stored != value:
                    conn.execute(text("UPDATE app_settings SET value = :v WHERE key = :k"), {"v": stored, "k": key})
                    changed += 1
        if inspector.has_table("client_torrent"):
            query = text("SELECT id, tracker_url FROM client_torrent WHERE tracker_url IS NOT NULL")
            for row_id, url in conn.execute(query):
                origin = announce_origin(url)
                if origin != url:
                    conn.execute(text("UPDATE client_torrent SET tracker_url = :v WHERE id = :id"),
                                 {"v": origin, "id": row_id})
                    changed += 1
    return changed


def make_session_factory(engine: Engine) -> sessionmaker:
    from nazgarr import (  # noqa: F401  (hook di eventi e redazione: nazgarr/events.py, nazgarr/redaction.py)
        events,
        redaction,
    )

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
