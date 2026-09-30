"""Stato unificato per file (docs/SPEC.md sezione 3).

Fase 2: con client_torrent_file disponibile, si può finalmente distinguere
`orphan_torrent` (nessun client traccia il file) da `ignored` (un client lo
traccia ma non è collegato alla libreria media) — in Fase 1 erano
indistinguibili, un solo stato grezzo "nessun media_file collegato".

Definizione usata qui (coerente con la tabella di SPEC.md sezione 3):
- seeding: hardlink valido (seed_file.media_file_id impostato) E tracciato
  da almeno un client (>=1 client_torrent_file collegato)
- ignored: tracciato da un client, ma NESSUN hardlink verso la libreria
- orphan_torrent: NON tracciato da alcun client, indipendentemente
  dall'hardlink — un file già hardlinkato ma perso dal client rientra
  comunque qui, perché l'azione utile resta la stessa (aggiungerlo di
  nuovo al client, mai ricreare un hardlink che esiste già, sezione 3)
- orphan_media: media_file senza alcun seed_file sibling "seeding" (vedi sopra)
"""

from sqlalchemy.orm import Session

from app.adapters.torrent_client.base import is_stopped_state
from app.duplicates import find_duplicate_media_files
from app.exclusions import CompiledExclusions
from app.file_types import is_video
from app.hardlinks import media_links
from app.models import ClientTorrent, ClientTorrentFile, MatchReview, MediaFile, MediaItem, SeedFile, SeedJob
from app.scan_state import is_current, latest_scan_by_disk
from app.tracker_scope import enabled_torrent_ids, scoped_torrent_ids

_NO_EXCLUSIONS = CompiledExclusions(patterns=[])


def _media_file_to_seed_paths(session: Session) -> dict[int, list[str]]:
    """media_file_id -> relative_path di ogni seed_file hardlinkato ad esso
    (spesso più di uno, cross-seed) — la stessa relazione che il motore di
    matching stabilisce già (seed_file.media_file_id), qui solo riletta al
    contrario per l'hover "hardlink" della UI (Fase 9)."""
    return {mf_id: [path for _sf_id, path in links] for mf_id, links in media_links(session).items()}


def _identity_by_media_file(session: Session) -> dict[int, tuple[str, int]]:
    """media_file.id -> (content_type, tmdb_id) del suo contenuto: con questo
    le viste ad albero aprono la stessa scheda di dettaglio della vista
    poster al clic su un file."""
    return {
        mf_id: (content_type, tmdb_id)
        for mf_id, content_type, tmdb_id in session.query(MediaFile.id, MediaItem.content_type, MediaItem.tmdb_id)
        .join(MediaItem, MediaItem.id == MediaFile.media_item_id)
        .all()
    }


def _tracking(session: Session, torrent_ids: set[int] | None = None) -> tuple[set[int], set[int]]:
    """(seed_file tracciati da un client, seed_file tracciati da almeno un
    torrent non fermo): un file in più torrent (cross-seed) è "stopped" solo
    se lo sono tutti. torrent_ids: solo questi torrent (filtro per tracker,
    app/tracker_scope.py); None = tutti."""
    tracked: set[int] = set()
    active: set[int] = set()
    for torrent_id, seed_file_id, state in (
        session.query(ClientTorrentFile.client_torrent_id, ClientTorrentFile.seed_file_id, ClientTorrent.state)
        .join(ClientTorrent, ClientTorrent.id == ClientTorrentFile.client_torrent_id)
        .filter(ClientTorrentFile.seed_file_id.isnot(None))
        .all()
    ):
        if torrent_ids is not None and torrent_id not in torrent_ids:
            continue
        tracked.add(seed_file_id)
        if not is_stopped_state(state):
            active.add(seed_file_id)
    return tracked, active


def media_file_states(
    session: Session, disk_id: int | None = None, exclusions: CompiledExclusions = _NO_EXCLUSIONS,
    tracker: str | None = None,
) -> list[dict]:
    """tracker: filtro per tracker (app/tracker_scope.py). Con un filtro un
    file è "seeding" solo se è in un torrent di quel tracker."""
    query = session.query(MediaFile)
    if disk_id is not None:
        query = query.filter_by(disk_id=disk_id)

    tracked_seed_file_ids, active_seed_file_ids = _tracking(session, scoped_torrent_ids(session, tracker))
    links = media_links(session)  # per inode: anche il secondo percorso di un import doppio
    seeding_media_file_ids = {mf_id for mf_id, sfs in links.items() if any(i in tracked_seed_file_ids for i, _ in sfs)}
    active_media_file_ids = {mf_id for mf_id, sfs in links.items() if any(i in active_seed_file_ids for i, _ in sfs)}
    linked_paths = {mf_id: [path for _i, path in sfs] for mf_id, sfs in links.items()}
    latest = latest_scan_by_disk(session, MediaFile)
    identity = _identity_by_media_file(session)

    return [
        {
            "id": mf.id,
            "disk_id": mf.disk_id,
            "relative_path": mf.relative_path,
            "size_bytes": mf.size_bytes,
            "state": "seeding" if mf.id in seeding_media_file_ids else "orphan_media",
            "stopped": mf.id in seeding_media_file_ids and mf.id not in active_media_file_ids,
            "excluded": exclusions.is_excluded(mf.relative_path),
            "linked_paths": linked_paths.get(mf.id, []),
            "content_type": identity.get(mf.id, (None, None))[0],
            "tmdb_id": identity.get(mf.id, (None, None))[1],
        }
        for mf in query.order_by(MediaFile.relative_path).all()
        if is_current(mf, latest)  # file spariti dal disco: mai mostrati né contati
    ]


def seed_file_states(
    session: Session, disk_id: int | None = None, exclusions: CompiledExclusions = _NO_EXCLUSIONS,
    tracker: str | None = None,
) -> list[dict]:
    """tracker: con un filtro, solo i file dei torrent di quel tracker, più
    quelli che non sono in nessun torrent (orfani per qualunque tracker):
    un file in seed solo per altri tracker non compare."""
    query = session.query(SeedFile)
    if disk_id is not None:
        query = query.filter_by(disk_id=disk_id)

    scope_ids = scoped_torrent_ids(session, tracker)
    tracked_seed_file_ids, active_seed_file_ids = _tracking(session, scope_ids)
    # Con un filtro, un file in torrent solo di client disattivati è orfano come
    # uno in nessun torrent (app/tracker_scope.py): i client spenti non contano.
    tracked_anywhere = (
        tracked_seed_file_ids if scope_ids is None else _tracking(session, enabled_torrent_ids(session))[0]
    )
    media_paths_by_id = {
        row[0]: row[1] for row in session.query(MediaFile.id, MediaFile.relative_path).all()
    }

    latest_seed = latest_scan_by_disk(session, SeedFile)
    identity = _identity_by_media_file(session)
    rows = [sf for sf in query.order_by(SeedFile.relative_path).all() if is_current(sf, latest_seed)]

    # Un file lato torrent orfano può essere un'altra copia (hardlink, stesso
    # inode) di un file che è in seed da un altro percorso, es. il torrent
    # rimosso dal client dopo un cross-seed: lo stato resta orfano (quel
    # percorso nessun client lo usa), ma la vista dice da dove è in seed.
    by_inode: dict[tuple[int, int, int], list[SeedFile]] = {}
    for sf in rows:
        by_inode.setdefault((sf.disk_id, sf.st_dev, sf.inode), []).append(sf)

    def _seeding_copies(sf: SeedFile) -> list[str]:
        if sf.id in tracked_seed_file_ids:
            return []
        return [
            other.relative_path for other in by_inode.get((sf.disk_id, sf.st_dev, sf.inode), [])
            if other.id != sf.id and other.id in tracked_seed_file_ids
        ]

    def _state(sf: SeedFile) -> str:
        if sf.id not in tracked_seed_file_ids:
            return "orphan_torrent"
        return "seeding" if sf.media_file_id is not None else "ignored"

    return [
        {
            "id": sf.id,
            "disk_id": sf.disk_id,
            "relative_path": sf.relative_path,
            "size_bytes": sf.size_bytes,
            "media_file_id": sf.media_file_id,
            "state": _state(sf),
            "stopped": sf.id in tracked_seed_file_ids and sf.id not in active_seed_file_ids,
            "excluded": exclusions.is_excluded(sf.relative_path),
            "linked_paths": [media_paths_by_id[sf.media_file_id]] if sf.media_file_id in media_paths_by_id else [],
            "seeding_copies": _seeding_copies(sf),
            "content_type": identity.get(sf.media_file_id, (None, None))[0],
            "tmdb_id": identity.get(sf.media_file_id, (None, None))[1],
        }
        for sf in rows
        if sf.id in tracked_seed_file_ids or sf.id not in tracked_anywhere
    ]


def media_items_overview(
    session: Session, disk_id: int | None = None, exclusions: CompiledExclusions = _NO_EXCLUSIONS,
    tracker: str | None = None,
) -> list[dict]:
    """Vista Libreria (sezione 7): un media_item per riga, con tutti i suoi
    media_file fisici raggruppati sotto e lo stato di ciascuno. Stessa
    risorsa per la vista poster e ad albero — differiscono solo nel
    rendering lato frontend."""
    file_states = media_file_states(session, disk_id=disk_id, exclusions=exclusions, tracker=tracker)
    states_by_id = {s["id"]: s["state"] for s in file_states}
    stopped_by_id = {s["id"]: s["stopped"] for s in file_states}
    excluded_by_id = {s["id"]: s["excluded"] for s in file_states}
    linked_by_id = {s["id"]: s["linked_paths"] for s in file_states}

    query = session.query(MediaFile).filter(MediaFile.media_item_id.isnot(None))
    if disk_id is not None:
        query = query.filter_by(disk_id=disk_id)

    # Stati per la vista poster (pallini): duplicati (stesso contenuto su
    # inode diversi, app/duplicates.py) e file con un match in attesa di
    # approvazione in Reseeding.
    duplicate_ids = {
        f["media_file_id"] for group in find_duplicate_media_files(session, disk_id=disk_id) for f in group["files"]
    }
    in_review_ids = {
        row[0]
        for row in session.query(MatchReview.media_file_id)
        .outerjoin(SeedJob, SeedJob.candidate_id == MatchReview.candidate_id)
        .filter(
            MatchReview.media_file_id.isnot(None),
            MatchReview.status.in_(("pending", "auto_approved")),
            SeedJob.id.is_(None),
        )
        .all()
    }

    files_by_item: dict[int, list[MediaFile]] = {}
    for mf in query.all():
        if mf.id not in states_by_id:
            continue  # sparito dal disco (ultimo scan riuscito non l'ha visto): mai "orphan"
        files_by_item.setdefault(mf.media_item_id, []).append(mf)

    if not files_by_item:
        return []

    items = (
        session.query(MediaItem)
        .filter(MediaItem.id.in_(files_by_item.keys()))
        .order_by(MediaItem.tmdb_id)
        .all()
    )
    return [
        {
            "id": item.id,
            "content_type": item.content_type,
            "tmdb_id": item.tmdb_id,
            "season_number": item.season_number,
            "episode_number": item.episode_number,
            "has_poster": item.tmdb_poster_path is not None,
            "title": item.title,
            "year": item.year,
            "files": [
                {
                    "media_file_id": mf.id,
                    "disk_id": mf.disk_id,
                    "relative_path": mf.relative_path,
                    "size_bytes": mf.size_bytes,
                    "state": states_by_id.get(mf.id, "orphan_media"),
                    "stopped": stopped_by_id.get(mf.id, False),
                    "excluded": excluded_by_id.get(mf.id, False),
                    "linked_paths": linked_by_id.get(mf.id, []),
                    "duplicate": mf.id in duplicate_ids,
                    "in_review": mf.id in in_review_ids,
                }
                for mf in files_by_item[item.id]
            ],
        }
        for item in items
    ]


def unmatched_media_files(
    session: Session, disk_id: int | None = None, exclusions: CompiledExclusions = _NO_EXCLUSIONS
) -> list[dict]:
    """media_file video senza alcuna identità risolta ("unmatched", sezione
    3) — mai in media_items_overview, che parte sempre da un media_item. I
    file non video non hanno mai un'identità, quindi non sono "unmatched"."""
    query = session.query(MediaFile).filter(MediaFile.media_item_id.is_(None))
    if disk_id is not None:
        query = query.filter_by(disk_id=disk_id)
    return [
        {
            "id": mf.id, "disk_id": mf.disk_id, "relative_path": mf.relative_path,
            "size_bytes": mf.size_bytes, "state": "unmatched",
            "excluded": exclusions.is_excluded(mf.relative_path), "linked_paths": [],
        }
        for mf in query.order_by(MediaFile.relative_path).all()
        if is_video(mf.relative_path)
    ]
