"""Library health snapshot (docs/SPEC.md §10, Fase 5).

Metrica scelta deliberatamente più semplice del punteggio pesato multi-
fattore di Auditorr (`process_health_metrics`: pesi 70/10/10/10 configurabili
su hardlink/orphan/not-imported/duplicati, ciascuno con una propria soglia
di tolleranza) — qui `orphan_torrent`/`ignored`/pending review/falliti sono
già KPI distinti e cliccabili in dashboard (SPEC.md §10), quindi il gauge
di "salute" copre un solo segnale chiaro e spiegabile: la percentuale
(pesata per dimensione, non per conteggio file) di libreria media
effettivamente seeding. Un multi-fattore pesato si può aggiungere in futuro
se un singolo numero risulta insufficiente — non introdotto ora senza un
bisogno concreto già osservato.
"""

from sqlalchemy.orm import Session

from nazgarr.library import states as library
from nazgarr.library.duplicates import find_duplicate_media_files
from nazgarr.library.exclusions import load_exclusions
from nazgarr.reseed import review


def _duplicates(session: Session, disk_id: int | None) -> dict:
    """Copie vere (inode diversi): lo spazio sprecato è tutto tranne una
    copia per gruppo. I doppioni sullo stesso inode non sprecano spazio:
    solo contati."""
    groups = find_duplicate_media_files(session, disk_id=disk_id)
    copies = [g for g in groups if g["kind"] == "copy"]
    return {
        "duplicate_wasted_bytes": sum(g["size_bytes"] * (len(g["files"]) - 1) for g in copies),
        "duplicate_files": sum(len(g["files"]) for g in copies),
        "duplicate_hardlink_groups": sum(1 for g in groups if g["kind"] == "hardlink"),
    }


def shared_metrics(session: Session, disk_id: int | None = None, exclusions=None) -> dict:
    """Le metriche che non dipendono dal filtro per tracker: duplicati, review
    in attesa, seed falliti, file non identificati. A fine run si calcolano
    una volta per tutti i filtri (nazgarr/reseed/pipeline.py)."""
    exclusions = exclusions or load_exclusions(session)
    return {
        **_duplicates(session, disk_id),
        "pending_review": len(review.list_ready_for_review(session)),
        "failed": len(review.list_failed_seed_jobs(session)),
        "unmatched": sum(
            1 for f in library.unmatched_media_files(session, disk_id=disk_id, exclusions=exclusions)
            if not f["excluded"]
        ),
    }


def compute_snapshot(
    session: Session, disk_id: int | None = None, tracker: str | None = None,
    data: library.LibraryData | None = None, shared: dict | None = None,
) -> dict:
    """tracker: filtro per tracker (nazgarr/torrents/tracker_scope.py), gli stessi stati
    delle viste della libreria con lo stesso filtro. data e shared: dati di
    base e metriche comuni già calcolati, per più filtri di fila."""
    # Stessi file che si vedono nelle viste: gli esclusi non contano mai.
    exclusions = load_exclusions(session)
    data = data or library.LibraryData(session)
    media_states = [
        f for f in library.media_file_states(
            session, disk_id=disk_id, exclusions=exclusions, tracker=tracker, data=data)
        if not f["excluded"]
    ]
    seed_states = [
        f for f in library.seed_file_states(
            session, disk_id=disk_id, exclusions=exclusions, tracker=tracker, data=data)
        if not f["excluded"]
    ]

    total_media_size = sum(f["size_bytes"] for f in media_states)
    seeding_media_size = sum(f["size_bytes"] for f in media_states if f["state"] == "seeding")
    # Libreria vuota: nessun file non sano, trattata come 100% sana
    # piuttosto che 0/0 indefinito.
    health_pct = round((seeding_media_size / total_media_size) * 100, 1) if total_media_size else 100.0

    return {
        "health_pct": health_pct,
        "total_media_size": total_media_size,
        "seeding_media_size": seeding_media_size,
        "orphan_torrent_count": sum(1 for f in seed_states if f["state"] == "orphan_torrent"),
        "ignored_count": sum(1 for f in seed_states if f["state"] == "ignored"),
        # Dimensioni per le card della dashboard (e il loro andamento, salvato
        # a ogni scansione in run_log): quanto spazio in ciascuna situazione.
        "orphan_torrent_bytes": sum(f["size_bytes"] for f in seed_states if f["state"] == "orphan_torrent"),
        "orphan_not_in_library_bytes": sum(
            f["size_bytes"] for f in seed_states if f["state"] == "orphan_torrent" and not f["linked_paths"]
        ),
        "ignored_bytes": sum(f["size_bytes"] for f in seed_states if f["state"] == "ignored"),
        **(shared if shared is not None else shared_metrics(session, disk_id, exclusions)),
    }
