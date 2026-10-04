"""Contratto per gli adapter client torrent.

Vedi docs/SPEC.md sezione 5 e sezione 8 (ereditata da ratio-guardian per
add_torrent/get_torrent_status — il recheck forzato dopo l'aggiunta del
torrent è un requisito funzionale non negoziabile, mai un modo per
bypassarlo implicitamente, es. default a skip_checking=True).

list_torrents() è la parte nuova rispetto a ratio-guardian: enumera ogni
torrent noto al client, file per file, usata da nazgarr/torrent_indexer.py per
popolare client_torrent/client_torrent_file e quindi calcolare
orphan_torrent/ignored (sezione 3, multi-client). Sola lettura — non
aggiunge/modifica mai nulla sul client.
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

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
    # errore del client): nazgarr/executor.py lo accetta se mancano soltanto i
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
    # I seeder dello sciame secondo il tracker (scrape), noi compresi: 1 vuol
    # dire che siamo l'ultimo. None se il client non lo sa.
    swarm_seeders: int | None = None


def seeders(value) -> int | None:
    """Un conteggio di seeder del client: solo da 1 in su (0 o -1 vogliono
    dire "non noto" quasi ovunque, mai "nessuno": noi stessi seediamo)."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 1 else None


class TorrentAddTimeoutError(Exception):
    """Il torrent non è comparso nel client entro il timeout dopo l'aggiunta."""


class TorrentAlreadyInClientError(Exception):
    """Il torrent (stesso infohash) è già nel client: qBittorrent ignora in
    silenzio un duplicato, senza questo controllo sembrerebbe un timeout."""


class TorrentClientAdapter(ABC):
    # Se il client sa aggiungere un torrent già completo, senza ricontrollarlo
    # (skip_check_verified). Transmission e rTorrent non lo sanno fare: lì il
    # recheck c'è sempre, e i chiamanti non registrano un recheck "saltato".
    can_skip_recheck: bool = True

    def close(self) -> None:
        """Chiude le connessioni dell'adapter. Chi lo costruisce lo chiude
        dopo l'uso (`with adapter_factory.build_...(...) as adapter:`): ogni
        operazione ha il suo adapter, e senza le connessioni restavano aperte
        fino al garbage collector."""
        close = getattr(getattr(self, "_client", None), "close", None)
        if callable(close):
            close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @abstractmethod
    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
        category: str | None = None, tags: list[str] | None = None,
    ) -> str:
        """Aggiunge il torrent puntando a save_path (il file già hardlinkato,
        o già presente per la direzione torrent->client di SPEC.md sezione 3).
        force_recheck deve essere True di default e non deve mai essere
        impostabile a False da nessun chiamante del motore di matching
        (Fase 4). Ritorna l'info_hash del torrent aggiunto.

        skip_check_verified: le sole eccezioni al recheck del client. Il
        chiamante ha appena verificato lui ogni piece di quei file: un reseed
        dopo il controllo completo al 100% (decisione dell'utente, 2026-09-29,
        opzione spenta di default, nazgarr/full_check.py), o un upload, il cui
        torrent Nazgarr ha appena creato leggendo quei file (decisione
        dell'utente, 2026-09-30, nazgarr/upload_execute.py). Il client lo
        aggiunge già completo, senza rileggerlo una seconda volta.

        category / tags: solo etichette nel client (nazgarr/client_labels.py); la
        gestione automatica resta spenta, una categoria non sposta i file.

        expected_info_hash (se noto: il .torrent è già stato scaricato e
        analizzato dal matching) rende l'attesa precisa — si aspetta proprio
        quel torrent, non "un torrent nuovo qualunque" — e trasforma un
        duplicato in TorrentAlreadyInClientError invece di un timeout."""
        raise NotImplementedError

    @abstractmethod
    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        raise NotImplementedError

    def list_categories(self) -> list[str]:
        """Le categorie che esistono nel client, per sceglierle dalla sua
        lista. Vuota se il client non ne ha o non le espone."""
        return []

    def recheck(self, info_hash: str) -> None:
        """Fa ricontrollare al client un torrent già aggiunto: il ripiego di
        un upload aggiunto senza recheck se qualcosa non torna."""
        raise NotImplementedError

    def remove_torrent(self, info_hash: str, delete_files: bool) -> None:
        """Toglie il torrent dal client; con delete_files il client cancella
        anche i suoi file (solo quelli del torrent, come fa la sua UI). Solo
        su richiesta esplicita dell'utente. Default: non supportato."""
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
    qui riporta gli stessi stati; Deluge "Paused", Transmission e rTorrent
    "stopped", rTorrent "paused"): il file resta tracciato, quindi "seeding"
    nel modello a stati (docs/SPEC.md §3), ma in quel momento non condivide."""
    return (state or "").lower().startswith(("paused", "stopped"))


StateKind = Literal["checking", "error", "stopped", "downloading", "other"]

# Gli stati nativi di ogni adapter incluso, in minuscolo, raggruppati per
# quello che contano per chi li legge (per esempio gli avvisi prima di
# rimuovere un torrent). qBittorrent/qui: checkingUP, missingFiles, *DL;
# Deluge: Checking, Error, Downloading, Allocating; Transmission: checking,
# check_pending, download_pending; rTorrent: checking, downloading. Un
# plugin che usa gli stessi nomi generici viene classificato uguale.
_CHECKING_KIND = {"checkingup", "checkingdl", "checkingresumedata", "checking", "check_pending"}
_ERROR_KIND = {"error", "missingfiles"}
_DOWNLOADING_KIND = {"downloading", "download_pending", "allocating"}


def state_kind(state: str | None) -> StateKind:
    """Lo stato nativo di un qualunque client, ridotto a una categoria: chi
    deve decidere (avvisi, blocchi) usa questa, mai i nomi di un client."""
    native = (state or "").lower()
    if native in _CHECKING_KIND:
        return "checking"
    if native in _ERROR_KIND:
        return "error"
    if is_stopped_state(native):
        return "stopped"
    if native in _DOWNLOADING_KIND or native.endswith("dl"):  # qBittorrent: stalledDL, queuedDL, forcedDL, metaDL
        return "downloading"
    return "other"



def local_torrent_bytes(torrent_file_or_url: str) -> bytes | None:
    """Il contenuto del .torrent se torrent_file_or_url è un file locale (un
    upload: sta nella cartella dati di Nazgarr, che il client non vede),
    None se è un URL (http/https/magnet: il link del tracker di un reseed),
    che si passa al client così com'è. Un percorso locale non va mai al
    client come URL: lo cercherebbe nel suo filesystem (No such file or
    directory)."""
    if os.path.isfile(torrent_file_or_url):
        with open(torrent_file_or_url, "rb") as f:
            return f.read()
    return None


def wait_for_hash(
    list_hashes: Callable[[], set[str]], before_hashes: set[str], expected: str | None,
    poll_interval: float, poll_timeout: float, where: str,
) -> str:
    """L'info hash del torrent appena aggiunto: quello atteso (expected, in
    minuscolo) appena compare, altrimenti il primo nuovo rispetto a
    before_hashes (diff prima/dopo, come qbittorrent.py). Gli hash si
    confrontano in minuscolo e si ritornano in minuscolo."""
    before = {h.lower() for h in before_hashes}
    deadline = time.monotonic() + poll_timeout
    while True:
        current = {h.lower() for h in list_hashes()}
        if expected is not None:
            if expected in current:
                return expected
        else:
            new_hashes = current - before
            if new_hashes:
                if len(new_hashes) > 1:
                    logger.warning("Più torrent nuovi rilevati dopo add_torrent: %s", new_hashes)
                return next(iter(new_hashes))
        if time.monotonic() >= deadline:
            raise TorrentAddTimeoutError(
                f"Nessun nuovo torrent rilevato in {where} entro {poll_timeout}s dall'aggiunta"
            )
        time.sleep(poll_interval)


def require_recheck(force_recheck: bool) -> None:
    if not force_recheck:
        raise ValueError(
            "force_recheck=False non è permesso: il recheck reale è "
            "un requisito funzionale, vedi docs/SPEC.md sezione 8."
        )
