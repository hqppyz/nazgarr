"""Verifica dei percorsi di un client torrent (decisione dell'utente,
2026-10-05): i file che il client ha in seed si trovano davvero sui dischi
di Nazgarr, con la corrispondenza dei percorsi di adesso?

Per ogni torrent si prende il file più grande e lo si traduce come fa
l'indicizzazione (nazgarr/torrents/indexer.py, nazgarr/torrents/client_paths.py).
Poi si guarda il disco: il file c'è, con la sua dimensione, ed è dentro una
cartella dei torrent? Sola lettura: solo stat, nessun file aperto o scritto.

Quando qualcosa non torna, si cerca la corrispondenza giusta: per ogni
percorso del client si tolgono le cartelle iniziali una alla volta finché
il resto non esiste in una cartella dei torrent (o nella radice) di un
disco, con la stessa dimensione. La parte tolta è come il client vede quella
cartella. La proposta più votata per ogni disco è quella suggerita.

I torrent vengono dall'ultima indicizzazione (veloce, e la corrispondenza
si riapplica adesso); dal client stesso se non è mai stato indicizzato.
"""

import os
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.core.models import ClientTorrent, ClientTorrentFile, Disk, DiskTorrentClient, TorrentClient
from nazgarr.torrents import client_paths

MAX_SAMPLES = 5000  # torrent controllati al massimo
MAX_SEARCHED = 300  # file non trovati su cui si cerca una corrispondenza
EXAMPLES = 3  # esempi per esito

OK, OUTSIDE, MISSING, UNMAPPED = "ok", "outside_seeding", "missing", "unmapped"


@dataclass
class Sample:
    client_path: str
    size: int


@dataclass
class Example:
    status: str
    client_path: str
    local_path: str | None = None  # dove Nazgarr l'ha cercato


@dataclass
class Suggestion:
    disk_id: int
    disk_label: str
    local_rel_path: str | None  # cartella del disco, None = tutto il disco
    client_root_path: str | None  # None = stessi percorsi di Nazgarr
    matches: int  # quanti file non trovati questa corrispondenza ritrova


@dataclass
class PathCheck:
    source: str  # "index" | "live"
    checked: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {OK: 0, OUTSIDE: 0, MISSING: 0, UNMAPPED: 0})
    examples: list[Example] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.checked:
            return "empty"
        if self.counts[OK] == self.checked:
            return "ok"
        return "none" if self.counts[OK] == 0 else "partial"


def samples_from_index(session: Session, client: TorrentClient) -> list[Sample]:
    """Il file più grande di ogni torrent, dall'ultima indicizzazione."""
    biggest = (
        session.query(ClientTorrentFile.client_torrent_id, func.max(ClientTorrentFile.size_bytes).label("size"))
        .join(ClientTorrent, ClientTorrent.id == ClientTorrentFile.client_torrent_id)
        .filter(ClientTorrent.torrent_client_id == client.id)
        .group_by(ClientTorrentFile.client_torrent_id)
        .subquery()
    )
    rows = (
        session.query(ClientTorrent.id, ClientTorrent.save_path, ClientTorrentFile.path_in_torrent,
                      ClientTorrentFile.size_bytes)
        .join(ClientTorrentFile, ClientTorrentFile.client_torrent_id == ClientTorrent.id)
        .join(biggest, (biggest.c.client_torrent_id == ClientTorrent.id)
              & (biggest.c.size == ClientTorrentFile.size_bytes))
        .order_by(ClientTorrent.id)
        .all()
    )
    seen, out = set(), []
    for torrent_id, save_path, path_in_torrent, size in rows:
        if torrent_id in seen:  # due file della stessa dimensione massima: uno basta
            continue
        seen.add(torrent_id)
        out.append(Sample(os.path.join(save_path, path_in_torrent), size))
        if len(out) >= MAX_SAMPLES:
            break
    return out


def samples_from_torrents(torrents) -> list[Sample]:
    out = []
    for t in torrents[:MAX_SAMPLES]:
        if t.files:
            f = max(t.files, key=lambda f: f.size_bytes)
            out.append(Sample(os.path.join(t.save_path, f.path_in_torrent), f.size_bytes))
    return out


def _file_matches(root: str, relative: str, size: int) -> str | None:
    """Il percorso assoluto se lì c'è un file di quella dimensione."""
    try:
        path = resolve_scoped(root, relative)
    except ScopeViolation:
        return None
    try:
        return path if os.path.isfile(path) and os.path.getsize(path) == size else None
    except OSError:
        return None


def _inside(relative: str, folders: list[str]) -> bool:
    return any(relative == f or relative.startswith(f.rstrip("/") + "/") for f in folders)


def _mappings(session: Session, client: TorrentClient) -> tuple[list[Disk], dict[int, client_paths.Mapping]]:
    """Gli stessi dischi e corrispondenze dell'indicizzazione."""
    links = session.query(DiskTorrentClient).filter_by(torrent_client_id=client.id).all()
    disks = [session.get(Disk, link.disk_id) for link in links] or session.query(Disk).order_by(Disk.id).all()
    by_id = {d.id: d for d in disks}
    mappings = {
        link.disk_id: client_paths.Mapping(by_id[link.disk_id].root_path, link.torrent_client_root_path,
                                           link.local_rel_path)
        for link in links if link.disk_id in by_id
    }
    return disks, mappings


def _classify(sample: Sample, disks: list[Disk], mappings: dict[int, client_paths.Mapping]) -> Example:
    tried = None
    for disk in disks:
        relative = client_paths.to_disk_relative(mappings.get(disk.id) or client_paths.Mapping(disk.root_path),
                                                 sample.client_path)
        if relative is None:
            continue
        found = _file_matches(disk.root_path, relative, sample.size)
        if found is None:
            tried = tried or os.path.join(disk.root_path, relative)
            continue
        return Example(OK if _inside(relative, disk.seeding_folders) else OUTSIDE, sample.client_path, found)
    return Example(MISSING if tried else UNMAPPED, sample.client_path, tried)


def _search(sample: Sample, disks: list[Disk]) -> list[tuple[int, str | None, str | None]]:
    """Le corrispondenze che ritrovano questo file: (disco, cartella, radice
    del client). Per ogni cartella dei torrent (e la radice del disco) si
    prova il suffisso più lungo del percorso del client per primo."""
    parts = [p for p in os.path.normpath(sample.client_path).split("/") if p]
    votes = []
    for disk in disks:
        for folder in [*disk.seeding_folders, None]:
            base = folder or ""
            for k in range(1, len(parts)):
                if _file_matches(disk.root_path, os.path.join(base, *parts[k:]), sample.size) is None:
                    continue
                client_root = "/" + "/".join(parts[:k])
                local_base = os.path.normpath(os.path.join(disk.root_path, base))
                if client_root == local_base:
                    votes.append((disk.id, None, None))  # stessi percorsi: nessuna corrispondenza serve
                else:
                    votes.append((disk.id, folder, client_root))
                break
            else:
                continue
            break
    return votes


def check(session: Session, client: TorrentClient, samples: list[Sample], source: str) -> PathCheck:
    disks, mappings = _mappings(session, client)
    result = PathCheck(source=source)
    shown: Counter = Counter()
    failed: list[Sample] = []
    for sample in samples:
        example = _classify(sample, disks, mappings)
        result.checked += 1
        result.counts[example.status] += 1
        # Fuori dalle cartelle dei torrent il percorso è giusto: manca la cartella, non la corrispondenza.
        if example.status in (MISSING, UNMAPPED):
            failed.append(sample)
        if shown[example.status] < EXAMPLES and example.status != OK:
            shown[example.status] += 1
            result.examples.append(example)
    # La proposta si cerca su tutti i dischi, anche quelli non associati al client.
    every_disk = session.query(Disk).order_by(Disk.id).all()
    votes: Counter = Counter()
    for sample in failed[:MAX_SEARCHED]:
        for vote in _search(sample, every_disk):
            votes[vote] += 1
    best: dict[int, tuple] = {}
    for (disk_id, folder, client_root), count in votes.most_common():
        best.setdefault(disk_id, (folder, client_root, count))
    labels = {d.id: d.label for d in every_disk}
    for disk_id, (folder, client_root, count) in sorted(best.items(), key=lambda item: -item[1][2]):
        current = mappings.get(disk_id)
        unchanged = (current is not None and (current.local_rel or None) == folder
                     and (current.client_root or None) == client_root)
        if not unchanged:
            result.suggestions.append(Suggestion(disk_id, labels[disk_id], folder, client_root, count))
    return result
