"""A che punto è la configurazione, per la checklist "Getting started" e il
tour del primo accesso (frontend/src/onboarding). Ogni passo si ricava dalla
configurazione reale, mai da quello che l'utente ha cliccato: un disco
aggiunto a mano vale come un disco aggiunto dal tour.

Sola lettura, nessuna chiamata di rete: dice cosa è configurato, non se
risponde (per quello ci sono i "Test connection")."""

from sqlalchemy.orm import Session

from nazgarr import adapter_factory, settings_repo
from nazgarr.models import (
    Disk,
    DiskTorrentClient,
    RadarrInstance,
    RunLog,
    SonarrInstance,
    TorrentClient,
    Tracker,
    TrackerUploadProfile,
)

# I passi che dipendono dalla configurazione. Esclusioni e soglie del
# reseeding hanno già dei default sensati: "fatti" quando il tour li ha
# mostrati (stato del tour, lato frontend), non da qui.
REQUIRED = ("storage", "clients", "metadata", "trackers", "first_scan")
OPTIONAL = ("arr", "upload")


def setup_status(session: Session) -> dict:
    disks = session.query(Disk).all()
    # La cartella media è facoltativa: si può usare Nazgarr solo per i torrent
    # e gli upload (decisione dell'utente, 2026-10-02).
    storage_ready = any(d.seeding_folders for d in disks)
    enabled_clients = {c.id for c in session.query(TorrentClient).filter(TorrentClient.enabled.is_(True))}
    # Collegare un client a dei dischi è facoltativo: senza, vale per tutti i
    # dischi confrontando i percorsi (nazgarr/torrent_indexer.py).
    linked = {row.torrent_client_id for row in session.query(DiskTorrentClient)} & enabled_clients
    trackers = session.query(Tracker).filter(Tracker.enabled.is_(True)).all()
    arr = sum(session.query(model).filter_by(enabled=True).count() for model in (RadarrInstance, SonarrInstance))
    profiles = {p.tracker_id for p in session.query(TrackerUploadProfile)}
    upload_trackers = [t for t in trackers if t.id in profiles and t.announce_url]
    image_hosts = adapter_factory.image_host_status(session)["usable"]
    scanned = session.query(RunLog.id).filter(RunLog.finished_at.isnot(None)).first() is not None

    steps = {
        "storage": {"done": storage_ready, "count": len(disks)},
        "clients": {"done": bool(enabled_clients), "count": len(enabled_clients), "linked": len(linked)},
        "metadata": {"done": bool(settings_repo.get_setting(session, "tmdb_api_key")) or arr > 0},
        "arr": {"done": arr > 0, "count": arr},
        "trackers": {"done": bool(trackers), "count": len(trackers)},
        "upload": {"done": bool(upload_trackers) and bool(image_hosts), "trackers": len(upload_trackers),
                   "image_hosts": len(image_hosts)},
        "first_scan": {"done": scanned},
    }
    return {
        "steps": steps,
        "required": list(REQUIRED),
        "optional": list(OPTIONAL),
        "complete": all(steps[key]["done"] for key in REQUIRED),
    }
