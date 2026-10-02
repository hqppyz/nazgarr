"""Indicizzazione dei torrent noti a un client (docs/SPEC.md sezione 5).

Per ogni TorrentClient abilitato, associato a uno o più Disk (tabella
ponte disk_torrent_client): interroga l'adapter (sola lettura,
list_torrents()) e popola client_torrent/client_torrent_file, risolvendo
client_torrent_file.seed_file_id per PATH contro seed_file.relative_path
del disco giusto — collegamento per path, non per inode (docs/SPEC.md
sezione 4: più stabile, comunque riverificato a ogni poll).

Un client senza dischi associati viene confrontato con tutti i dischi per
path esatto: è il caso comune in cui client e Nazgarr montano gli
stessi percorsi, e non deve richiedere nessuna configurazione.

Un client può vedere il filesystem da una radice diversa dalla nostra
(container/mount diversi per lo stesso disco fisico): se impostato,
disk_torrent_client.torrent_client_root_path (per questo specifico client,
non un campo del disco: client diversi sullo stesso disco possono avere
path diversi) sostituisce disk.root_path SOLO per interpretare i path che
arrivano dal client. Il confronto resta sempre puramente lessicale
(os.path.normpath/relpath) — MAI os.path.realpath sui path riportati dal
client: potrebbero non esistere affatto in questo filesystem/namespace (è
esattamente il motivo per cui questo override esiste), quindi risolverli
come se fossero percorsi nostri produrrebbe risultati arbitrari, non un
errore esplicito.
"""

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from nazgarr.adapters.torrent_client.base import ClientTorrentInfo, TorrentClientAdapter
from nazgarr.db_utils import bulk_upsert
from nazgarr.models import (
    ClientTorrent,
    ClientTorrentFile,
    Disk,
    DiskTorrentClient,
    RunLog,
    SeedFile,
    SeedJob,
    TorrentClient,
)

logger = logging.getLogger(__name__)


def announce_origin(url: str | None) -> str | None:
    """Dell'announce di un torrent serve solo l'host (a quale tracker
    appartiene: nazgarr/tracker_scope.py): schema e host, senza percorso, che
    contiene la passkey (/announce/<passkey>, ?passkey=...)."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.hostname}{port}"


def _resolve_seed_file_id(
    client_abs_path: str,
    disks: list[Disk],
    root_path_by_disk_id: dict[int, str | None],
    seed_lookup_by_disk: dict[int, dict[str, int]],
) -> int | None:
    candidate = os.path.normpath(client_abs_path)
    for disk in disks:
        client_root = os.path.normpath(root_path_by_disk_id.get(disk.id) or disk.root_path)
        if candidate == client_root or candidate.startswith(client_root + os.sep):
            rel_path = os.path.relpath(candidate, client_root)
            seed_file_id = seed_lookup_by_disk.get(disk.id, {}).get(rel_path)
            if seed_file_id is not None:
                return seed_file_id
    return None


def index_torrent_client(
    session: Session,
    torrent_client: TorrentClient,
    adapter: TorrentClientAdapter,
    run: RunLog,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Interroga l'adapter e popola client_torrent/client_torrent_file per
    QUESTO client, collegandoli ai seed_file dei dischi ad esso associati
    (disk_torrent_client), o di tutti i dischi se non ne ha nessuno
    associato (stessi percorsi fra client e Nazgarr)."""
    logger.debug("Client %r: chiamata adapter.list_torrents()...", torrent_client.label)
    torrents: list[ClientTorrentInfo] = (
        adapter.list_torrents(on_progress=on_progress) if on_progress is not None else adapter.list_torrents()
    )
    logger.debug("Client %r: adapter.list_torrents() ha restituito %d torrent", torrent_client.label, len(torrents))

    counts = store_client_torrents(session, torrent_client, torrents, run.id)
    counts["torrents_removed"] = prune_missing_torrents(session, torrent_client, torrents, run.id)
    return counts


def prune_missing_torrents(
    session: Session, torrent_client: TorrentClient, torrents: list[ClientTorrentInfo], run_id: int
) -> int:
    """Dopo un'indicizzazione COMPLETA e riuscita del client (list_torrents
    solleva su qualunque errore, mai una lista parziale): i torrent che il
    client non ha più, e i file non più nei torrent rimasti, escono dal DB.
    Senza questo un torrent rimosso dal client restava "tracciato" per
    sempre: il suo file risultava in seeding e non tornava mai orfano, quindi
    mai più cercato né proposto in review. Mai chiamata dall'aggiornamento
    mirato di un solo torrent (store_client_torrents da seed_refresh)."""
    present = {t.info_hash for t in torrents}
    stale_ids = [
        ct_id
        for ct_id, info_hash in session.query(ClientTorrent.id, ClientTorrent.info_hash)
        .filter_by(torrent_client_id=torrent_client.id)
        .all()
        if info_hash not in present
    ]
    for chunk_start in range(0, len(stale_ids), 500):
        chunk = stale_ids[chunk_start:chunk_start + 500]
        session.query(SeedJob).filter(SeedJob.result_client_torrent_id.in_(chunk)).update(
            {SeedJob.result_client_torrent_id: None}, synchronize_session=False
        )
        session.query(ClientTorrentFile).filter(ClientTorrentFile.client_torrent_id.in_(chunk)).delete(
            synchronize_session=False
        )
        session.query(ClientTorrent).filter(ClientTorrent.id.in_(chunk)).delete(synchronize_session=False)
    kept_ids = session.query(ClientTorrent.id).filter_by(torrent_client_id=torrent_client.id)
    removed_files = (
        session.query(ClientTorrentFile)
        .filter(ClientTorrentFile.client_torrent_id.in_(kept_ids), ClientTorrentFile.last_scan_id != run_id)
        .delete(synchronize_session=False)
    )
    session.commit()
    if stale_ids or removed_files:
        logger.info(
            "Client %r: %d torrent non più presenti nel client rimossi (%d file di torrent rimasti non più presenti)",
            torrent_client.label, len(stale_ids), removed_files,
        )
    return len(stale_ids)


def store_client_torrents(
    session: Session, torrent_client: TorrentClient, torrents: list[ClientTorrentInfo], run_id: int
) -> dict[str, int]:
    """Scrive client_torrent/client_torrent_file per questi torrent di QUESTO
    client e collega ogni file a un seed_file per path. Usata sia
    dall'indicizzazione completa sia dall'aggiornamento mirato di un solo
    torrent appena messo in seed (refresh_seeded_torrent)."""
    now = datetime.now(UTC)
    torrent_rows = [
        {
            "torrent_client_id": torrent_client.id,
            "info_hash": t.info_hash,
            "name": t.name,
            "save_path": t.save_path,
            "category": t.category,
            "tracker_url": announce_origin(t.tracker_url),
            "state": t.state,
            "last_polled_at": now,
            "ratio": t.ratio,
            "seeding_time_seconds": t.seeding_time_seconds,
            "added_at": datetime.fromtimestamp(t.added_on, UTC) if t.added_on else None,
        }
        for t in torrents
    ]
    bulk_upsert(
        session, ClientTorrent.__table__, torrent_rows,
        conflict_cols=["torrent_client_id", "info_hash"],
        update_cols=[
            "name", "save_path", "category", "tracker_url", "state", "last_polled_at",
            "ratio", "seeding_time_seconds", "added_at",
        ],
    )
    session.commit()
    logger.debug("Client %r: %d righe client_torrent scritte", torrent_client.label, len(torrent_rows))

    hash_to_id: dict[str, int] = dict(
        session.query(ClientTorrent.info_hash, ClientTorrent.id).filter_by(torrent_client_id=torrent_client.id).all()
    )

    links = session.query(DiskTorrentClient).filter_by(torrent_client_id=torrent_client.id).all()
    disks = [session.get(Disk, link.disk_id) for link in links]
    if not disks:
        # Nessuna associazione esplicita: il caso comune (TRaSH Guides) è che
        # client e Nazgarr vedano gli stessi percorsi, quindi i file del
        # client si cercano su tutti i dischi per path esatto. L'associazione
        # serve solo a limitare i dischi o a dare una radice diversa.
        disks = session.query(Disk).all()
        logger.debug("Client %r: nessun disco associato, confronto con tutti i dischi", torrent_client.label)
    root_path_by_disk_id = {link.disk_id: link.torrent_client_root_path for link in links}
    seed_lookup_by_disk: dict[int, dict[str, int]] = {
        disk.id: dict(session.query(SeedFile.relative_path, SeedFile.id).filter_by(disk_id=disk.id).all())
        for disk in disks
    }

    file_rows = []
    for t in torrents:
        client_torrent_id = hash_to_id[t.info_hash]
        for f in t.files:
            client_abs_path = os.path.join(t.save_path, f.path_in_torrent)
            seed_file_id = _resolve_seed_file_id(client_abs_path, disks, root_path_by_disk_id, seed_lookup_by_disk)
            file_rows.append({
                "client_torrent_id": client_torrent_id,
                "path_in_torrent": f.path_in_torrent,
                "size_bytes": f.size_bytes,
                "seed_file_id": seed_file_id,
                "last_scan_id": run_id,
            })

    bulk_upsert(
        session, ClientTorrentFile.__table__, file_rows,
        conflict_cols=["client_torrent_id", "path_in_torrent"],
        update_cols=["size_bytes", "seed_file_id", "last_scan_id"],
    )
    session.commit()

    linked = sum(1 for row in file_rows if row["seed_file_id"] is not None)
    if disks and file_rows and not linked:
        sample = next((t for t in torrents if t.files), None)
        logger.warning(
            "Client %r: %d file indicizzati, nessuno collegato a un file su disco — il client li vede sotto "
            "percorsi diversi (es. %r, radici dei dischi %r): associa il disco al client con l'override della "
            "radice (Configuration > Clients)",
            torrent_client.label, len(file_rows),
            os.path.join(sample.save_path, sample.files[0].path_in_torrent) if sample else None,
            [root_path_by_disk_id.get(d.id) or d.root_path for d in disks],
        )
    return {"torrents_indexed": len(torrent_rows), "files_indexed": len(file_rows), "files_linked": linked}
