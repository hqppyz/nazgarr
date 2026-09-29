"""Contratto per gli adapter client torrent.

Vedi docs/SPEC.md sezione 5 e sezione 8 (ereditata da ratio-guardian per
add_torrent/get_torrent_status — il recheck forzato dopo l'aggiunta del
torrent è un requisito funzionale non negoziabile, mai un modo per
bypassarlo implicitamente, es. default a skip_checking=True).

list_torrents() è la parte nuova rispetto a ratio-guardian: enumera ogni
torrent noto al client, file per file, usata da app/torrent_indexer.py per
popolare client_torrent/client_torrent_file e quindi calcolare
orphan_torrent/ignored (sezione 3, multi-client). Sola lettura — non
aggiunge/modifica mai nulla sul client.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

RecheckStatus = Literal["pending", "ok", "failed"]

# Stati nativi qBittorrent che indicano un controllo hash in corso.
CHECKING_STATES = {"checkingUP", "checkingDL", "checkingResumeData"}
# Stati nativi che indicano un fallimento esplicito (dati mancanti/corrotti).
ERROR_STATES = {"error", "missingFiles"}


@dataclass
class TorrentStatus:
    info_hash: str
    state: str  # stato nativo del client, non normalizzato
    recheck_status: RecheckStatus
    progress: float  # 0.0-1.0
    # recheck_status "failed" solo perché mancano dati (nessuno stato di
    # errore del client): app/executor.py lo accetta se mancano soltanto i
    # file extra che si sapeva di non avere (seed_job.expected_missing_bytes).
    incomplete: bool = False
    amount_left: int | None = None  # byte ancora da scaricare, se il client lo espone


@dataclass
class ClientTorrentFileInfo:
    path_in_torrent: str  # relativo alla save_path del torrent
    size_bytes: int


@dataclass
class ClientTorrentInfo:
    info_hash: str
    name: str
    save_path: str
    state: str  # stato nativo del client, non normalizzato
    category: str | None = None
    tracker_url: str | None = None
    files: list[ClientTorrentFileInfo] = field(default_factory=list)
    # Per la vista Not imported: se un vecchio torrent serve ancora (ratio,
    # tempo in seed, H&R del tracker). None se il client non li riporta.
    ratio: float | None = None
    seeding_time_seconds: int | None = None
    added_on: int | None = None  # epoch in secondi


class TorrentAddTimeoutError(Exception):
    """Il torrent non è comparso nel client entro il timeout dopo l'aggiunta."""


class TorrentAlreadyInClientError(Exception):
    """Il torrent (stesso infohash) è già nel client: qBittorrent ignora in
    silenzio un duplicato, senza questo controllo sembrerebbe un timeout."""


class TorrentClientAdapter(ABC):
    @abstractmethod
    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
    ) -> str:
        """Aggiunge il torrent puntando a save_path (il file già hardlinkato,
        o già presente per la direzione torrent->client di SPEC.md sezione 3).
        force_recheck deve essere True di default e non deve mai essere
        impostabile a False da nessun chiamante del motore di matching
        (Fase 4). Ritorna l'info_hash del torrent aggiunto.

        skip_check_verified: l'unica eccezione al recheck del client (decisione
        dell'utente, 2026-09-29, opzione spenta di default). Il chiamante l'ha
        appena verificato lui al 100% (app/full_check.py), senza extra
        mancanti e con lo stesso info hash: il client lo aggiunge già
        completo, senza rileggerlo una seconda volta.

        expected_info_hash (se noto: il .torrent è già stato scaricato e
        analizzato dal matching) rende l'attesa precisa — si aspetta proprio
        quel torrent, non "un torrent nuovo qualunque" — e trasforma un
        duplicato in TorrentAlreadyInClientError invece di un timeout."""
        raise NotImplementedError

    @abstractmethod
    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        raise NotImplementedError

    def get_torrent_info(self, info_hash: str) -> "ClientTorrentInfo | None":
        """Un solo torrent coi suoi file (None se il client non lo conosce):
        per aggiornare subito un torrent appena messo in seed senza
        reindicizzare l'intero client. Default: non supportato."""
        return None

    @abstractmethod
    def list_torrents(self, on_progress: Callable[[int, int], None] | None = None) -> list[ClientTorrentInfo]:
        """Ogni torrent noto al client, coi suoi file. Usata per popolare
        client_torrent/client_torrent_file (Fase 2) — mai per aggiungere o
        modificare nulla sul client. `on_progress(fatti, totale)` dopo ogni
        torrent, per l'avanzamento della run: il totale è noto appena il
        client restituisce l'elenco, i file arrivano poi uno a uno."""
        raise NotImplementedError


def is_stopped_state(state: str | None) -> bool:
    """Torrent fermato nel client (qBittorrent 4 "paused*", 5 "stopped*";
    qui riporta gli stessi stati): il file resta tracciato, quindi "seeding"
    nel modello a stati (docs/SPEC.md §3), ma in quel momento non condivide."""
    return (state or "").lower().startswith(("paused", "stopped"))

