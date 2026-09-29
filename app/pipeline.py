"""Orchestrazione di una run: scan filesystem (app/scanner.py), poi
risoluzione TMDB (app/media_resolution.py), poi indicizzazione client
torrent (app/torrent_indexer.py), poi matching (app/matching.py) ed
esecuzione automatica delle review sopra soglia (app/review.py), infine
reconcile dei seed_job ancora in corso.

Ordine vincolante:
- scan prima di indicizzazione: l'indexer collega client_torrent_file ai
  seed_file appena scritti dallo scan (§4) — invertito, ogni file
  risulterebbe erroneamente orphan_torrent invece che seeding/ignored.
- indicizzazione prima di matching: orphan_media_files/
  orphan_seed_files_with_identity (§3) dipendono dallo stato client
  aggiornato per classificare correttamente cosa è davvero orfano.
- risoluzione TMDB non ha dipendenze rispetto a indicizzazione/matching
  sull'ordine relativo, ma deve comunque precedere il matching (serve
  media_item_id risolto per cercare sul tracker).

Import massivo e run schedulato (Fase 5) condivideranno questo stesso
motore — la differenza è solo nel trigger, non nella pipeline.

Ogni fase committa run.current_phase PRIMA di eseguirsi (non solo a
inizio/fine run, come faceva la prima versione) così un poller su
GET /api/runs vede un avanzamento vero, non "scanning" per l'intera
durata. Ogni eccezione di fase fa, via _record_failure: log completo
(logger.exception, finisce nel log file letto dalla tab Logs),
session.rollback() — senza, un'eccezione DB a metà transazione lascia
la sessione inutilizzabile per tutto il resto della run, incluso il
commit finale che salva errors/finished_at: la run resta agganciata per
sempre come "in corso", senza mai un errore visibile né una fine (bug
diagnosticato proprio su questa funzione, sintomo: "ha chiamato il
client torrent e poi più nulla") — poi un commit dedicato di
errors/last_error, così un fallimento successivo non perde anche
questo. Un try/except esterno a tutte le fasi resta comunque come rete
di sicurezza per qualunque cosa sfugga ai blocchi già protetti (es. una
query() di per sé fallita, non solo il lavoro di una singola fase)."""

import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import (
    adapter_factory,
    arr,
    file_changes,
    health,
    matching,
    media_resolution,
    not_imported,
    review,
    scanner,
    settings_repo,
    torrent_indexer,
)
from app.adapter_factory import TmdbApiKeyMissingError
from app.models import Disk, RunLog, SeedFile, TorrentClient, Tracker
from app.run_progress import RunCancelled, RunProgress
from app.tmdb_client import TMDBClient

logger = logging.getLogger(__name__)


def close_interrupted_runs(session: Session) -> int:
    """All'avvio nessuna run può essere davvero in corso (girano nel
    processo, in background): una run senza finished_at è stata interrotta
    da un riavvio o da un crash del container. Chiusa esplicitamente con un
    errore visibile, altrimenti resterebbe "in corso" per sempre nel popup
    di stato e in Reseeding. Il lavoro già fatto resta (match_attempt,
    candidati): la run successiva riparte da dove serve."""
    now = datetime.now(UTC)
    interrupted = session.query(RunLog).filter(RunLog.finished_at.is_(None)).all()
    for run in interrupted:
        phase = run.current_phase or "start"
        run.finished_at = now
        run.current_phase = None
        run.phase_total = run.phase_done = None
        run.phase_detail = None
        run.errors = (run.errors or 0) + 1
        _note_error(run, f"Interrupted by a restart during '{phase}': the next scan picks up from there")
        logger.warning("Run #%s interrotta da un riavvio durante '%s', chiusa", run.id, phase)
    if interrupted:
        session.commit()
    return len(interrupted)


def start_run(session: Session, run_type: str) -> RunLog:
    run = RunLog(run_type=run_type, started_at=datetime.now(UTC), current_phase="scanning")
    session.add(run)
    session.commit()
    return run


MAX_RUN_ERRORS_KEPT = 50


def _note_error(run: RunLog, message: str) -> None:
    """last_error resta l'ultimo; errors_json li tiene tutti (fino a
    MAX_RUN_ERRORS_KEPT), per mostrarli nella cronologia delle scansioni."""
    run.last_error = message
    try:
        kept = json.loads(run.errors_json) if run.errors_json else []
    except ValueError:
        kept = []
    run.errors_json = json.dumps((kept + [message])[-MAX_RUN_ERRORS_KEPT:])


def _record_failure(session: Session, run: RunLog, errors: int, label: str, exc: Exception) -> int:
    logger.exception("Run #%s: %s fallito", run.id, label)
    session.rollback()
    run.errors = errors + 1
    _note_error(run, f"{label}: {exc}")
    session.commit()
    return errors + 1


def _remember_rss_key(session: Session, tracker_row: Tracker, tracker_adapter) -> None:
    """Salva la chiave dei link di download appresa dall'API durante il
    matching: la prossima run riscrive subito i link della history senza
    dover prima sbagliare un download."""
    learned = getattr(tracker_adapter, "rss_key", None)
    if learned and learned != tracker_row.rss_key:
        tracker_row.rss_key = learned
        session.commit()
        logger.info("Tracker %r: chiave dei link di download aggiornata dall'API", tracker_row.label)


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def run_bulk_import(session: Session, run: RunLog, data_dir: str) -> RunLog:
    """Import massivo: scansiona tutti i dischi configurati, risolve i
    media_file non ancora identificati via TMDB, poi indicizza tutti i
    client torrent abilitati (docs/SPEC.md sezione 11).

    Riceve `run` già creata (invece di crearla qui) perché l'API che lo
    innesca (app/api/runs.py) deve poter rispondere subito con l'id della
    run mentre il lavoro vero, potenzialmente lungo, prosegue in
    background con una sessione propria — se questa funzione creasse una
    seconda RunLog al posto di riusare quella, l'endpoint e la run
    finirebbero per riferirsi a due righe diverse."""
    totals = {
        "media_files_scanned": 0, "seed_files_scanned": 0,
        "torrents_indexed": 0, "files_indexed": 0,
        "resolved": 0, "unresolved": 0,
        "candidates_found": 0, "auto_executed": 0,
    }
    errors = 0
    progress = RunProgress(session, run)

    def phase(name: str, total: int | None = None, detail: str | None = None) -> None:
        progress.start_phase(name, total, detail)
        logger.info("Run #%s: fase '%s'", run.id, name)

    try:
        phase("scanning", detail="Listing files…")
        disks = session.query(Disk).all()
        logger.info("Run #%s: %d %s da scansionare", run.id, len(disks), _plural(len(disks), "disco", "dischi"))
        # Prima l'elenco dei file di tutti i dischi (veloce, solo nomi), così
        # il totale è noto prima della parte lenta (stat + hash).
        scan_failed = False
        listed: list[tuple[Disk, scanner.DiskFiles]] = []
        for disk in disks:
            progress.detail(f"Listing files on {disk.label}…")
            try:
                files = scanner.list_disk_files(disk)
            except Exception as exc:
                errors = _record_failure(session, run, errors, f"scan of disk {disk.label!r}", exc)
                scan_failed = True
                continue
            listed.append((disk, files))
            progress.add_total(len(files))
        for i, (disk, files) in enumerate(listed, start=1):
            logger.debug("Run #%s: scansione disco %r (%s)", run.id, disk.label, disk.root_path)
            progress.detail(f"{disk.label} ({i}/{len(listed)})")
            try:
                counts = scanner.scan_disk(session, disk, run, files=files, on_progress=progress.advance)
            except Exception as exc:
                errors = _record_failure(session, run, errors, f"scan of disk {disk.label!r}", exc)
                scan_failed = True
                continue
            logger.info(
                "Run #%s: disco %r scansionato — %d media file, %d seed file",
                run.id, disk.label, counts["media_files_scanned"], counts["seed_files_scanned"],
            )
            totals["media_files_scanned"] += counts["media_files_scanned"]
            totals["seed_files_scanned"] += counts["seed_files_scanned"]
            run.items_scanned = totals["media_files_scanned"] + totals["seed_files_scanned"]

        phase("resolving", detail="Reading Radarr/Sonarr library and history…")
        # Radarr/Sonarr (opzionali) indicizzati una sola volta per run:
        # servono sia alla risoluzione (identità senza TMDB) sia al matching
        # (torrent d'origine dalla history, senza ricerca sul tracker).
        arr_index = None
        try:
            arr_index = arr.build_arr_index(session)
            if len(arr_index):
                logger.info(
                    "Run #%s: Radarr/Sonarr — %d file identificati, %d con torrent d'origine nella history",
                    run.id, arr_index.counts["identities"], arr_index.counts["grabs"],
                )
        except Exception as exc:
            errors = _record_failure(session, run, errors, "Radarr/Sonarr indexing", exc)
        try:
            resolver = adapter_factory.build_media_resolver(session, arr_index)
        except TmdbApiKeyMissingError:
            # Non ancora configurata: la risoluzione è opzionale a questo punto
            # del progetto (Fase 3), mai un errore bloccante — vedi docs/SPEC.md
            # sezione 6, "mai assunto presente".
            logger.info("Run #%s: TMDB non configurata, salto la risoluzione", run.id)
            resolver = None
        if resolver is not None:
            progress.detail("Radarr / Sonarr / TMDB" if arr_index is not None and len(arr_index) else "TMDB")
            try:
                posters_dir = os.path.join(data_dir, "posters")
                counts = media_resolution.resolve_unmatched_media_files(
                    session, resolver, posters_dir, progress=progress, arr_index=arr_index
                )
                totals["resolved"] = counts["resolved"]
                totals["unresolved"] = counts["unresolved"]
                logger.info(
                    "Run #%s: risoluzione TMDB — %d risolti, %d non risolti, %d identità corrette",
                    run.id, counts["resolved"], counts["unresolved"], counts["corrected"],
                )
            except Exception as exc:
                errors = _record_failure(session, run, errors, "TMDB resolution", exc)
        else:
            progress.detail("TMDB not configured: skipped")
        # Titoli e poster mancanti (voci create prima che si salvassero, o
        # poster mai scaricati): una richiesta per contenuto, non per file.
        try:
            tmdb_key = settings_repo.get_setting(session, "tmdb_api_key")
            details = TMDBClient(api_key=tmdb_key).details if tmdb_key else None
            progress.detail("Completing titles and posters")
            filled = media_resolution.complete_media_items(
                session, os.path.join(data_dir, "posters"), arr_index, details, progress=progress
            )
            if filled["completed"] or filled["failed"]:
                logger.info(
                    "Run #%s: titoli/poster completati per %d contenuti (%d falliti)",
                    run.id, filled["completed"], filled["failed"],
                )
        except Exception as exc:
            errors = _record_failure(session, run, errors, "completing titles and posters", exc)

        phase("indexing", total=0)
        indexing_failed = False
        torrent_clients = session.query(TorrentClient).filter_by(enabled=True).all()
        logger.info(
            "Run #%s: %d client torrent abilitat%s da indicizzare",
            run.id, len(torrent_clients), _plural(len(torrent_clients), "o", "i"),
        )
        for i, torrent_client in enumerate(torrent_clients, start=1):
            logger.debug(
                "Run #%s: indicizzazione client %r (%s, %s)",
                run.id, torrent_client.label, torrent_client.adapter_type, torrent_client.base_url,
            )
            progress.detail(f"{torrent_client.label} ({i}/{len(torrent_clients)}): listing torrents…")
            client_total = {"known": False}

            def on_torrent(done: int, total: int, _label=torrent_client.label, _i=i) -> None:
                if not client_total["known"]:
                    client_total["known"] = True
                    progress.add_total(total)
                    progress.detail(f"{_label} ({_i}/{len(torrent_clients)})")
                progress.advance()

            try:
                adapter = adapter_factory.build_torrent_client_adapter(torrent_client)
                counts = torrent_indexer.index_torrent_client(
                    session, torrent_client, adapter, run, on_progress=on_torrent
                )
            except Exception as exc:
                errors = _record_failure(session, run, errors, f"torrent client {torrent_client.label!r}", exc)
                indexing_failed = True
                continue
            logger.info(
                "Run #%s: client %r indicizzato — %d torrent, %d file",
                run.id, torrent_client.label, counts["torrents_indexed"], counts["files_indexed"],
            )
            totals["torrents_indexed"] += counts["torrents_indexed"]
            totals["files_indexed"] += counts["files_indexed"]
            totals["files_linked"] = totals.get("files_linked", 0) + counts.get("files_linked", 0)

        # Il matching torrent -> client cerca sul tracker ogni file lato
        # torrent che nessun client traccia. Se l'indicizzazione non è
        # affidabile (un client fallito, o nessun file collegato a un file su
        # disco: disco non associato o percorsi diversi) OGNI file lato
        # torrent risulta orfano, e cercarli tutti costerebbe ore di tracker
        # per candidati di file che in realtà sono già in seed.
        t2c_problem = None
        skip_t2c = not torrent_clients  # nessun client: niente a cui aggiungere un torrent, non un errore
        if skip_t2c:
            logger.info("Run #%s: nessun client torrent abilitato, matching torrent -> client saltato", run.id)
        elif session.query(SeedFile).count():
            if indexing_failed:
                t2c_problem = "a torrent client could not be indexed"
            elif not totals.get("files_linked"):
                t2c_problem = (
                    "no file of the torrent clients is linked to a file on disk: the client probably sees "
                    "them under a different path, set its root path on the disk (Configuration > Mapping > "
                    "Torrent clients)"
                )
        if t2c_problem:
            logger.warning("Run #%s: matching torrent -> client saltato: %s", run.id, t2c_problem)
            errors += 1
            run.errors = errors
            _note_error(run, f"Torrent → client matching skipped: {t2c_problem}")
            session.commit()

        try:
            review.close_resolved_reviews(session)
        except Exception as exc:
            errors = _record_failure(session, run, errors, "review queue cleanup", exc)

        phase("matching", total=0)
        trackers = session.query(Tracker).filter_by(enabled=True).all()
        logger.info(
            "Run #%s: %d tracker abilitat%s per il matching",
            run.id, len(trackers), _plural(len(trackers), "o", "i"),
        )
        for i, tracker_row in enumerate(trackers, start=1):
            logger.debug("Run #%s: matching contro tracker %r", run.id, tracker_row.label)
            where = f"{tracker_row.label} ({i}/{len(trackers)})"
            current = {"detail": f"{where} · library → torrent"}
            progress.detail(current["detail"])

            def on_wait(seconds: float | None, _label=tracker_row.label) -> None:
                progress.detail(
                    f"{_label}: rate limited (429), retrying in {seconds:.0f}s" if seconds is not None
                    else current["detail"]
                )

            try:
                tracker_adapter = adapter_factory.build_tracker_adapter(tracker_row)
                if hasattr(tracker_adapter, "on_rate_limit_wait"):
                    tracker_adapter.on_rate_limit_wait = on_wait
                m2t = matching.run_media_to_torrent_matching(
                    session, tracker_row, tracker_adapter, arr_index, progress=progress
                )
                # Già in rate limit: la seconda direzione peggiorerebbe solo il blocco.
                t2c = None
                if not m2t["rate_limited"] and not t2c_problem and not skip_t2c:
                    current["detail"] = f"{where} · torrent → client"
                    progress.detail(current["detail"])
                    t2c = matching.run_torrent_to_client_matching(
                        session, tracker_row, tracker_adapter, arr_index, progress=progress
                    )
            except Exception as exc:
                errors = _record_failure(session, run, errors, f"tracker {tracker_row.label!r}", exc)
                continue
            _remember_rss_key(session, tracker_row, tracker_adapter)
            parts = [m2t] + ([t2c] if t2c else [])
            candidates = sum(p["candidates"] for p in parts)
            searched = sum(p["files"] for p in parts)
            skipped = sum(p["skipped_fresh"] for p in parts)
            from_history = sum(p["from_history"] for p in parts)
            failed = sum(p["failed"] for p in parts)
            rate_limited = any(p["rate_limited"] for p in parts)
            logger.info(
                "Run #%s: tracker %r — %d file cercati (%d via history Radarr/Sonarr), "
                "%d già cercati di recente saltati, %d falliti, %d candidati trovati",
                run.id, tracker_row.label, searched, from_history, skipped, failed, candidates,
            )
            totals["candidates_found"] += candidates
            if rate_limited or failed:
                problem = (
                    "persistent rate limit (429), matching stopped: the remaining files are searched next time"
                    if rate_limited
                    else f"{failed} files not searched because of an error (details in the logs)"
                )
                errors += 1
                run.errors = errors
                _note_error(run, f"tracker {tracker_row.label!r}: {problem}")
                session.commit()

        phase("executing", total=0)
        try:
            exec_counts = review.execute_auto_approved(session, progress=progress)
            totals["auto_executed"] = exec_counts["executed"]
            if exec_counts.get("waiting"):
                logger.info(
                    "Run #%s: esecuzione automatica disattivata, %d review consigliate in attesa di approvazione",
                    run.id, exec_counts["waiting"],
                )
            else:
                logger.info("Run #%s: %d review eseguite automaticamente", run.id, exec_counts["executed"])
        except Exception as exc:
            errors = _record_failure(session, run, errors, "automatic execution of reviews", exc)

        phase("reconciling", total=0)
        try:
            review.reconcile_pending_seed_jobs(session, progress=progress)
            logger.info("Run #%s: reconcile dei seed_job in corso completato", run.id)
        except Exception as exc:
            errors = _record_failure(session, run, errors, "checking pending rechecks", exc)

        # Cambiamenti per file rispetto alla scansione precedente: solo con
        # dati affidabili (vedi app/file_changes.py).
        if scan_failed or indexing_failed:
            logger.info("Run #%s: scansione o indicizzazione incompleta, nessun confronto dei file", run.id)
            not_imported.mark_skipped(
                session, "a disk could not be scanned" if scan_failed else "a torrent client could not be indexed"
            )
        else:
            try:
                file_changes.record_changes(session, run)
            except Exception as exc:
                errors = _record_failure(session, run, errors, "changes since the last scan", exc)
            # Torrent in seed senza hardlink in libreria, e perché (vista Not imported).
            try:
                not_imported.classify_not_imported(session, arr_index, run)
            except Exception as exc:
                errors = _record_failure(session, run, errors, "not imported torrents", exc)
    except RunCancelled:
        # Stop richiesto dall'utente: non un errore. Il lavoro già salvato
        # resta (file scansionati, identità, match_attempt, candidati): la
        # run successiva riparte da lì.
        session.rollback()
        stopped_in = run.current_phase or "start"
        logger.info("Run #%s fermata dall'utente durante '%s'", run.id, stopped_in)
        run.last_error = f"Stopped by the user during '{stopped_in}'"
    except Exception as exc:
        # Rete di sicurezza: qualunque cosa sfugga ai blocchi già protetti
        # sopra (es. una query() o un commit() di per sé fallito, non solo
        # il lavoro di una singola fase) non deve comunque lasciare la run
        # agganciata per sempre — vedi la nota in cima al modulo.
        logger.exception("Run #%s: errore inatteso durante l'esecuzione", run.id)
        session.rollback()
        errors += 1
        _note_error(run, f"unexpected error: {exc}")

    progress.finish()
    run.finished_at = datetime.now(UTC)
    run.items_scanned = totals["media_files_scanned"] + totals["seed_files_scanned"]
    run.matches_found = totals["candidates_found"]
    run.auto_executed = totals["auto_executed"]
    try:
        snapshot = health.compute_snapshot(session)
        run.pending_review = snapshot["pending_review"]
        run.orphan_torrent_count = snapshot["orphan_torrent_count"]
        run.ignored_count = snapshot["ignored_count"]
        run.health_snapshot = snapshot["health_pct"]
        run.orphan_torrent_bytes = snapshot["orphan_torrent_bytes"]
        run.ignored_bytes = snapshot["ignored_bytes"]
        run.duplicate_wasted_bytes = snapshot["duplicate_wasted_bytes"]
    except Exception as exc:
        errors = _record_failure(session, run, errors, "library health snapshot", exc)
        run.pending_review = len(review.list_ready_for_review(session))
    run.errors = errors
    session.commit()
    logger.info(
        "Run #%s completata: %d item scansionati, %d match, %d auto-eseguiti, %d errori",
        run.id, run.items_scanned, run.matches_found, run.auto_executed, errors,
    )
    return run
