"""Come un client torrent vede le cartelle di un disco (decisione dell'utente,
2026-10-03), alla maniera delle "Remote Path Mappings" di Sonarr/Radarr.

Per ogni coppia (disco, client), in disk_torrent_client:
- torrent_client_root_path: la cartella come la vede il client;
- local_rel_path: quale cartella del disco è (relativa alla radice; vuota =
  la radice del disco, il caso di prima).

Es. Nazgarr /data/qbittorrent ↔ qBittorrent /download: local_rel_path
"qbittorrent", torrent_client_root_path "/download". Senza
torrent_client_root_path il client vede gli stessi percorsi di Nazgarr.

Due direzioni: dal client a Nazgarr (indicizzazione, percorso confrontato
solo lessicalmente: non esiste nel nostro filesystem) e da Nazgarr al
client (il save_path di un torrent aggiunto). Un percorso fuori dalla
cartella mappata il client non lo vede: errore esplicito, mai un torrent
aggiunto con un percorso che non esiste per lui.
"""

import os
from dataclasses import dataclass

from nazgarr.core.errors import CodedError


class ClientPathError(CodedError):
    pass


@dataclass
class Mapping:
    disk_root: str
    client_root: str | None = None
    local_rel: str | None = None

    @property
    def local_base(self) -> str:
        return os.path.normpath(os.path.join(self.disk_root, self.local_rel or ""))

    @property
    def mapped(self) -> bool:
        return bool(self.client_root)


def to_client(mapping: Mapping, local_path: str) -> str:
    """Il percorso locale come lo vede il client."""
    if not mapping.mapped:
        return local_path
    base = os.path.realpath(mapping.local_base)
    local = os.path.realpath(local_path)
    if local == base or local.startswith(base + os.sep):
        relative = os.path.relpath(local, base)
        return mapping.client_root if relative == "." else os.path.join(mapping.client_root, relative)
    if mapping.local_rel:
        # Il client vede solo quella sottocartella del disco.
        raise ClientPathError("client_cannot_see_path", path=local_path, folder=mapping.local_base,
                              client_root=mapping.client_root)
    return local_path  # fuori dal disco: non dovrebbe succedere, non tocchiamo nulla


def to_disk_relative(mapping: Mapping, client_path: str) -> str | None:
    """Un percorso riportato dal client → relativo alla radice del disco, o
    None se non è dentro la cartella che il client vede di questo disco."""
    candidate = os.path.normpath(client_path)
    if mapping.client_root:
        root, prefix = os.path.normpath(mapping.client_root), mapping.local_rel or ""
    else:
        root, prefix = os.path.normpath(mapping.disk_root), ""
    if candidate != root and not candidate.startswith(root.rstrip(os.sep) + os.sep):
        return None
    relative = os.path.relpath(candidate, root)
    return os.path.normpath(os.path.join(prefix, relative)) if prefix else relative
