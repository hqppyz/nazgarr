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

import inspect
import logging
import os
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from nazgarr.adapters.torrent_client.base import ClientTorrentFileInfo, ClientTorrentInfo, TorrentClientAdapter
from nazgarr.core.db_utils import as_utc, bulk_upsert
from nazgarr.core.models import (
    ClientTorrent,
    ClientTorrentFile,
    Disk,
    DiskTorrentClient,
    RunLog,
    SeedFile,
    SeedJob,
    TorrentClient,
)
from nazgarr.torrents import client_paths

logger = logging.getLogger(__name__)


def announce_origin(url: str | None) -> str | None:
    """Dell'announce di un torrent serve solo l'host (a quale tracker
    appartiene: nazgarr/torrents/tracker_scope.py): schema e host, senza percorso, che
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
    mapping_by_disk_id: dict[int, client_paths.Mapping],
    seed_lookup_by_disk: dict[int, dict[str, int]],
) -> tuple[int | None, bool]:
    """Il seed_file del percorso del client, e se il percorso è almeno
    finito su un disco (tradotto, ma senza un file lì: una corrispondenza o
    una cartella sbagliata, non un torrent di un disco che Nazgarr non ha)."""
    mapped = False
    for disk in disks:
        mapping = mapping_by_disk_id.get(disk.id) or client_paths.Mapping(disk.root_path)
        rel_path = client_paths.to_disk_relative(mapping, client_abs_path)
        if rel_path is None:
            continue
        mapped = True
        seed_file_id = seed_lookup_by_disk.get(disk.id, {}).get(rel_path)
        if seed_file_id is not None:
            return seed_file_id, True
    return None, mapped


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
    options: dict = {"on_progress": on_progress} if on_progress is not None else {}
    if _accepts_known(adapter):
        options["known"] = known_torrents(session, torrent_client, run.id)
    listed_at = datetime.now(UTC)
    torrents: list[ClientTorrentInfo] = adapter.list_torrents(**options)
    logger.debug("Client %r: adapter.list_torrents() ha restituito %d torrent", torrent_client.label, len(torrents))

    counts = store_client_torrents(session, torrent_client, torrents, run.id)
    counts["torrents_removed"] = prune_missing_torrents(session, torrent_client, torrents, run.id, listed_at)
    return counts


# Un torrent non cambiato riusa i file dell'ultima indicizzazione (known,
# base.reusable_files), ma un file rinominato dentro una cartella non cambia
# niente di quello che il client dice del torrent: a ogni indicizzazione se
# ne richiedono comunque i file di un ottavo, a turno per info hash, così
# ognuno si rilegge almeno ogni FILES_REFRESH_RUNS indicizzazioni.
FILES_REFRESH_RUNS = 8


def _accepts_known(adapter: TorrentClientAdapter) -> bool:
    """list_torrents dell'adapter ha il parametro known (gli adapter inclusi
    che chiedono i file un torrent alla volta; un plugin che lo dichiara)."""
    try:
        return "known" in inspect.signature(adapter.list_torrents).parameters
    except (TypeError, ValueError):
        return False


def _refresh_now(info_hash: str, run_id: int) -> bool:
    return zlib.crc32(info_hash.lower().encode()) % FILES_REFRESH_RUNS == run_id % FILES_REFRESH_RUNS


def known_torrents(session: Session, torrent_client: TorrentClient, run_id: int) -> dict[str, ClientTorrentInfo]:
    """I torrent di questo client all'ultima indicizzazione, coi loro file
    (client_torrent_file, che la potatura tiene uguali all'ultimo elenco),
    tranne quelli il cui turno di rilettura è questa run (_refresh_now)."""
    rows = (
        session.query(ClientTorrent.info_hash, ClientTorrent.name, ClientTorrent.save_path, ClientTorrent.state,
                      ClientTorrentFile.path_in_torrent, ClientTorrentFile.size_bytes)
        .join(ClientTorrentFile, ClientTorrentFile.client_torrent_id == ClientTorrent.id)
        .filter(ClientTorrent.torrent_client_id == torrent_client.id)
    )
    known: dict[str, ClientTorrentInfo] = {}
    for info_hash, name, save_path, state, path, size in rows:
        entry = known.get(info_hash)
        if entry is None:
            if _refresh_now(info_hash, run_id):
                continue
            entry = known[info_hash] = ClientTorrentInfo(info_hash=info_hash, name=name, save_path=save_path,
                                                         state=state)
        entry.files.append(ClientTorrentFileInfo(path_in_torrent=path, size_bytes=size))
    return known


def prune_missing_torrents(
    session: Session, torrent_client: TorrentClient, torrents: list[ClientTorrentInfo], run_id: int,
    listed_at: datetime | None = None,
) -> int:
    """Dopo un'indicizzazione COMPLETA e riuscita del client (list_torrents
    solleva su qualunque errore, mai una lista parziale): i torrent che il
    client non ha più, e i file non più nei torrent rimasti, escono dal DB.
    Senza questo un torrent rimosso dal client restava "tracciato" per
    sempre: il suo file risultava in seeding e non tornava mai orfano, quindi
    mai più cercato né proposto in review. Mai chiamata dall'aggiornamento
    mirato di un solo torrent (store_client_torrents da seed_refresh).

    listed_at: quando è partita la richiesta dell'elenco al client. Un
    torrent assente dall'elenco ma registrato dopo (last_polled_at più
    recente: un upload, un reseed o un import di Radarr/Sonarr appena
    aggiunti, nazgarr/library/seed_refresh.py) resta, coi suoi file:
    l'elenco era già partito quando il client lo ha ricevuto (audit
    2026-10-18). Prima la potatura lo toglieva, e il file appena messo in
    seed tornava "orphan" fino alla run dopo, che lo cercava sui tracker.
    Se il client non lo ha davvero più, lo toglie l'indicizzazione dopo."""
    present = {t.info_hash for t in torrents}
    stale_ids, registered_since = [], []
    for ct_id, info_hash, polled_at in (
        session.query(ClientTorrent.id, ClientTorrent.info_hash, ClientTorrent.last_polled_at)
        .filter_by(torrent_client_id=torrent_client.id)
        .all()
    ):
        if info_hash in present:
            continue
        if listed_at is not None and polled_at is not None and as_utc(polled_at) > listed_at:
            registered_since.append(ct_id)
        else:
            stale_ids.append(ct_id)
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
    if registered_since:  # i loro file non sono in questo elenco: non si potano
        kept_ids = kept_ids.filter(ClientTorrent.id.notin_(registered_since))
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
    if registered_since:
        logger.info("Client %r: %d torrent registrati durante l'elenco del client restano fino alla prossima "
                    "indicizzazione", torrent_client.label, len(registered_since))
    return len(stale_ids)


def client_disks(session: Session, torrent_client: TorrentClient) -> tuple[list[Disk], dict[int, client_paths.Mapping]]:
    """I dischi di questo client (disk_torrent_client), o tutti se non ne ha
    nessuno associato, con la traduzione dei percorsi per quelli che ce l'hanno."""
    links = session.query(DiskTorrentClient).filter_by(torrent_client_id=torrent_client.id).all()
    disks = [session.get(Disk, link.disk_id) for link in links]
    if not disks:
        # Nessuna associazione esplicita: il caso comune (TRaSH Guides) è che
        # client e Nazgarr vedano gli stessi percorsi, quindi i file del
        # client si cercano su tutti i dischi per path esatto. L'associazione
        # serve solo a limitare i dischi o a dare una radice diversa.
        disks = session.query(Disk).all()
        logger.debug("Client %r: nessun disco associato, confronto con tutti i dischi", torrent_client.label)
    disk_by_id = {disk.id: disk for disk in disks}
    mappings = {
        link.disk_id: client_paths.Mapping(disk_by_id[link.disk_id].root_path, link.torrent_client_root_path,
                                           link.local_rel_path)
        for link in links if link.disk_id in disk_by_id
    }
    return disks, mappings


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
            "swarm_seeders": t.swarm_seeders,
            "added_at": datetime.fromtimestamp(t.added_on, UTC) if t.added_on else None,
        }
        for t in torrents
    ]
    bulk_upsert(
        session, ClientTorrent.__table__, torrent_rows,
        conflict_cols=["torrent_client_id", "info_hash"],
        update_cols=[
            "name", "save_path", "category", "tracker_url", "state", "last_polled_at",
            "ratio", "seeding_time_seconds", "added_at", "swarm_seeders",
        ],
    )
    session.commit()
    logger.debug("Client %r: %d righe client_torrent scritte", torrent_client.label, len(torrent_rows))

    hash_to_id: dict[str, int] = dict(
        session.query(ClientTorrent.info_hash, ClientTorrent.id).filter_by(torrent_client_id=torrent_client.id).all()
    )

    disks, mapping_by_disk_id = client_disks(session, torrent_client)
    seed_lookup_by_disk: dict[int, dict[str, int]] = {
        disk.id: dict(session.query(SeedFile.relative_path, SeedFile.id).filter_by(disk_id=disk.id).all())
        for disk in disks
    }

    file_rows = []
    mapped_unlinked = 0
    for t in torrents:
        client_torrent_id = hash_to_id[t.info_hash]
        for f in t.files:
            client_abs_path = os.path.join(t.save_path, f.path_in_torrent)
            seed_file_id, mapped = _resolve_seed_file_id(client_abs_path, disks, mapping_by_disk_id,
                                                         seed_lookup_by_disk)
            if seed_file_id is None and mapped:
                mapped_unlinked += 1
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
            [(mapping_by_disk_id[d.id].client_root if d.id in mapping_by_disk_id else None) or d.root_path
             for d in disks],
        )
    return {"torrents_indexed": len(torrent_rows), "files_indexed": len(file_rows), "files_linked": linked,
            "files_mapped_unlinked": mapped_unlinked}
