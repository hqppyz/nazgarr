"""Contratto per gli adapter client torrent.

Vedi docs/SPEC.md sezione 5 e sezione 8 (ereditata da ratio-guardian per
add_torrent/get_torrent_status — il recheck forzato dopo l'aggiunta del
torrent è un requisito funzionale non negoziabile, mai un modo per
bypassarlo implicitamente, es. default a skip_checking=True).

list_torrents() è la parte nuova rispetto a ratio-guardian: enumera ogni
torrent noto al client, file per file, usata da nazgarr/torrents/indexer.py per
popolare client_torrent/client_torrent_file e quindi calcolare
orphan_torrent/ignored (sezione 3, multi-client). Sola lettura — non
aggiunge/modifica mai nulla sul client.
"""

import inspect
import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from nazgarr.torrents.metainfo import TorrentMetainfoError, compute_info_hash

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
    # errore del client): nazgarr/reseed/executor.py lo accetta se mancano soltanto i
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


def number(value, kind):
    """Un numero del client (ratio, secondi, epoch) convertito con kind
    (int, float), None se manca o non è un numero: un campo strano di un
    torrent non ferma l'indicizzazione."""
    try:
        return kind(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# Come qBittorrent: "Original" segue il .torrent, "Subfolder" mette un
# torrent a file singolo in una cartella col nome del file senza estensione,
# "NoSubfolder" toglie la cartella radice di un torrent con più file.
CONTENT_LAYOUTS = ("Original", "Subfolder", "NoSubfolder")


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
    # Se add_torrent sa aggiungere un torrent fermo (stopped=True) e start()
    # lo avvia: un reseed entra fermo e parte solo dopo un recheck riuscito
    # (decisione dell'utente, 2026-10-18). Ogni adapter incluso lo sa fare;
    # un plugin scritto prima no (default False): i suoi reseed entrano
    # avviati come prima, e un recheck fallito si ferma con stop().
    can_add_stopped: bool = False

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
        category: str | None = None, tags: list[str] | None = None, content_layout: str = "Original",
        stopped: bool = False,
    ) -> str:
        """Aggiunge il torrent puntando a save_path (il file già hardlinkato,
        o già presente per la direzione torrent->client di SPEC.md sezione 3).
        force_recheck deve essere True di default e non deve mai essere
        impostabile a False da nessun chiamante del motore di matching
        (Fase 4). Ritorna l'info_hash del torrent aggiunto.

        skip_check_verified: le sole eccezioni al recheck del client. Il
        chiamante ha appena verificato lui ogni piece di quei file: un reseed
        dopo il controllo completo al 100% (decisione dell'utente, 2026-09-29,
        opzione spenta di default, nazgarr/reseed/full_check.py), o un upload, il cui
        torrent Nazgarr ha appena creato leggendo quei file (decisione
        dell'utente, 2026-09-30, nazgarr/upload/execute.py). Il client lo
        aggiunge già completo, senza rileggerlo una seconda volta.

        category / tags: solo etichette nel client (nazgarr/torrents/client_labels.py); la
        gestione automatica resta spenta, una categoria non sposta i file.

        expected_info_hash (se noto: il .torrent è già stato scaricato e
        analizzato dal matching) rende l'attesa precisa — si aspetta proprio
        quel torrent, non "un torrent nuovo qualunque" — e trasforma un
        duplicato in TorrentAlreadyInClientError invece di un timeout.

        content_layout: dove il client mette i file rispetto a save_path
        (CONTENT_LAYOUTS). Nazgarr lo passa sempre esplicito, così la
        preferenza globale del client non sposta i file da dove li ha messi
        lui; un client senza questa preferenza segue il .torrent, cioè
        "Original", e può ignorarlo.

        stopped (solo con can_add_stopped): il torrent entra fermo, il
        recheck forzato si fa lo stesso (qBittorrent, qui e Deluge lo
        avviano per il controllo e lo rifermano dopo), e niente si scarica
        né si condivide finché qualcuno non chiama start(). Lo chiede un
        reseed (decisione dell'utente, 2026-10-18): i file a save_path sono
        hardlink dei file in libreria, e un torrent avviato con un recheck
        fallito ci scaricava dentro i piece che mancavano. Senza stopped
        (un upload) il torrent parte, qualunque cosa dicano le preferenze
        del client ("non avviare automaticamente", la condizione di arresto
        "file controllati")."""
        raise NotImplementedError

    def start(self, info_hash: str) -> None:  # noqa: B027 — niente di proposito, non astratto: vedi sotto
        """Avvia un torrent fermo: un reseed aggiunto con stopped, quando il
        suo recheck è riuscito (nazgarr/reseed/executor.py::reconcile_seed_job),
        o un torrent che le preferenze del client hanno lasciato fermo.
        Default: niente, per un plugin senza can_add_stopped, i cui torrent
        partono da soli."""

    def stop(self, info_hash: str) -> None:
        """Ferma un torrent: niente download né upload finché non si riavvia.
        Nazgarr lo chiama su un reseed il cui recheck è fallito e che non è
        fermo (audit 2026-10-18; un plugin senza can_add_stopped lo aggiunge
        avviato): un torrent incompleto lasciato avviato scarica i piece
        che mancano e li scrive nei file a save_path, che per un reseed sono
        hardlink dei file in libreria, cioè gli stessi byte. Default: non
        supportato (un plugin scritto prima di stop): il seed job dice di
        fermarlo a mano."""
        raise NotImplementedError

    def partial_file_suffix(self) -> str | None:
        """Il suffisso che il client aggiunge al nome di un file incompleto,
        se lo fa: Transmission con rename-partial-files (il suo default)
        rinomina "<nome>" in "<nome>.part" già durante il recheck, anche di
        un torrent fermo. Dopo il recheck fallito di un reseed l'hardlink
        nella cartella dei torrent (o il file dell'utente, per un torrent
        già su disco) restava con quel nome. Nazgarr lo rimette ai soli file
        che ha messo o che segue (nazgarr/torrents/partial_files.py), e la
        pagina dei client avvisa (decisione dell'utente, 2026-10-19).
        Default: None, il client non rinomina niente."""
        return None

    def content_layout(self) -> str:
        """La preferenza dell'utente per la struttura dei torrent aggiunti
        (qBittorrent: Opzioni › Download › Layout del contenuto), per
        rispettarla nei nuovi hardlink (nazgarr/reseed/executor.py): uno
        di CONTENT_LAYOUTS. Default: il client segue il .torrent."""
        return "Original"

    @abstractmethod
    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        raise NotImplementedError

    def list_categories(self) -> list[str]:
        """Le categorie che esistono nel client, per sceglierle dalla sua
        lista. Vuota se il client non ne ha o non le espone."""
        return []

    def recheck(self, info_hash: str) -> None:
        """Fa ricontrollare al client un torrent già aggiunto, senza avviarlo
        se è fermo: il ripiego di un upload aggiunto senza recheck se
        qualcosa non torna, e il retry di un reseed rimasto fermo dopo un
        recheck fallito (nazgarr/reseed/executor.py::adopt_for_retry; un
        torrent fermo il client non lo ricontrolla da solo). Come dopo
        add_torrent, get_torrent_status dice poi "pending" finché il
        controllo non ha un esito, mai l'esito di prima."""
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
        torrent, o gruppo di torrent, per l'avanzamento della run: fatti è
        il conto dei torrent fatti finora (non uno in più a ogni chiamata),
        il totale è noto appena il client restituisce l'elenco.

        Un adapter che chiede i file un torrent alla volta può accettare
        anche `known` (SDK 1.7): {info_hash: ClientTorrentInfo} dell'ultima
        indicizzazione, coi file, per riusare quelli di un torrent che non è
        cambiato (reusable_files) invece di richiederli. L'indicizzazione lo
        passa solo a chi ha il parametro (nazgarr/torrents/indexer.py)."""
        raise NotImplementedError

    def list_largest_files(self, limit: int | None = None) -> list[ClientTorrentInfo]:
        """Ogni torrent (i primi `limit`) col solo suo file più grande in
        files: quello che serve alla verifica dei percorsi di un client
        chiesta al client stesso (nazgarr/torrents/path_check.py, "Check
        paths" dal vivo). Sola lettura. Gli adapter inclusi chiedono solo
        save path e file, senza tracker né statistiche, a gruppi dove il
        client lo permette, e solo per i torrent che servono (audit
        2026-10-18: la verifica chiedeva l'elenco completo di list_torrents
        e ne usava i primi 5000, e un proxy davanti scadeva). Gli altri
        campi possono mancare (tracker_url None). Default: list_torrents()
        ridotto, per un plugin che non lo implementa."""
        return [largest_file_only(t) for t in self.list_torrents()[:limit]]

    def count_torrents(self) -> int:
        """Quanti torrent ha il client, per la prova delle credenziali (Test
        nella configurazione dei client). Gli adapter inclusi lo chiedono
        con una sola richiesta, senza i file di ogni torrent (audit
        2026-10-18: la prova scaricava l'elenco dei file di migliaia di
        torrent solo per contarli). Default: list_torrents(), per un plugin
        che non lo implementa."""
        return len(self.list_torrents())


def reusable_files(
    known: ClientTorrentInfo | None, *, name: str, save_path: str, state: str | None, total_size: int | None,
    content_path: str | None = None, complete: Callable[[str | None], bool] | None = None,
) -> list[ClientTorrentFileInfo] | None:
    """I file dell'ultima indicizzazione (known) di un torrent, se valgono
    ancora per quello che il client ne dice adesso, None se vanno richiesti
    (audit 2026-10-18, finding 35: qBittorrent ha una richiesta dei file per
    torrent, e un client di 10.000 torrent costava minuti a ogni run).
    Valgono se il torrent ha lo stesso nome e la stessa cartella, era ed è
    completo ("uploading" e gli stati "*UP" di qBittorrent: i file
    incompleti possono avere un altro nome, es. ".!qB"), la somma dei file è
    la sua dimensione totale e, se il client lo dice, il percorso del
    contenuto è lo stesso (un file o la cartella radice rinominati). Un file
    rinominato più in fondo non si vede da qui: l'indicizzazione li richiede
    comunque tutti, a turno (indexer.FILES_REFRESH_RUNS).

    complete: quando uno stato del client è di un torrent completo, per un
    plugin coi suoi nomi degli stati (es. "seeding"); di default quelli di
    qBittorrent, e con altri nomi nessun file si riusava mai (revisione
    dell'audit 2026-10-18)."""
    if known is None or not known.files or total_size is None:
        return None
    if (known.name, known.save_path) != (name, save_path):
        return None
    is_complete = complete or _complete
    if not (is_complete(known.state) and is_complete(state)):
        return None
    if sum(f.size_bytes for f in known.files) != total_size:
        return None
    if content_path:
        expected = _content_path(known)
        if expected is None or os.path.normpath(content_path) != os.path.normpath(expected):
            return None
    return known.files


def _complete(state: str | None) -> bool:
    # qBittorrent (e qui): "uploading" e gli stati "*UP" (stalledUP, stoppedUP,
    # pausedUP, queuedUP, forcedUP, checkingUP) sono di un torrent completo.
    return state == "uploading" or (state or "").endswith("UP")


def _content_path(info: ClientTorrentInfo) -> str | None:
    """Il percorso del contenuto come lo riporta qBittorrent (content_path):
    il file, per un torrent con un file solo; la cartella radice, se tutti i
    file ne hanno una; None se non si sa dire."""
    paths = [f.path_in_torrent for f in info.files]
    if len(paths) == 1:
        return os.path.join(info.save_path, paths[0])
    roots = {p.split("/", 1)[0] for p in paths if "/" in p}
    if len(roots) == 1 and all("/" in p for p in paths):
        return os.path.join(info.save_path, roots.pop())
    return None


def largest_file_only(info: ClientTorrentInfo) -> ClientTorrentInfo:
    """Lo stesso torrent col solo suo file più grande (nessuno se non ne ha)."""
    biggest = max(info.files, key=lambda f: f.size_bytes, default=None)
    return replace(info, files=[biggest] if biggest is not None else [])


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



def layout_kwargs(adapter, layout: str) -> dict:
    """content_layout per add_torrent, solo se l'adapter lo accetta: un
    plugin scritto prima di content_layout non lo conosce (e per lui vale
    comunque "Original", il default di content_layout())."""
    try:
        accepted = "content_layout" in inspect.signature(adapter.add_torrent).parameters
    except (TypeError, ValueError):
        accepted = False
    return {"content_layout": layout} if accepted else {}


def stopped_kwargs(adapter) -> dict:
    """stopped=True per add_torrent, solo se l'adapter sa aggiungere un
    torrent fermo (can_add_stopped) e il suo add_torrent lo accetta: un
    plugin che eredita da un adapter incluso e ridefinisce add_torrent senza
    il parametro non lo riceve (e il suo torrent parte come prima). Un
    add_torrent con **kwargs lo riceve: l'adapter ha detto di saperlo fare."""
    if not getattr(adapter, "can_add_stopped", False):
        return {}
    try:
        parameters = inspect.signature(adapter.add_torrent).parameters.values()
    except (TypeError, ValueError):
        return {}
    accepted = any(p.name == "stopped" or p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters)
    return {"stopped": True} if accepted else {}


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


def expected_hash(expected_info_hash: str | None, content: bytes | None) -> str | None:
    """L'info hash da aspettare dopo l'aggiunta, in minuscolo: quello dato
    dal chiamante, se no quello dei byte del .torrent locale che si stanno
    mandando (lo span grezzo di info, nazgarr/torrents/metainfo.py). Senza
    un hash atteso l'adapter prende "il primo torrent nuovo" del client: un
    torrent aggiunto nello stesso momento da un altro programma (Sonarr,
    autobrr, cross-seed) passava per il nostro, e recheck e avvio finivano
    su quello (audit 2026-10-18). None solo per un URL, o per byte che non
    sono un .torrent (il client lo rifiuterà)."""
    if expected_info_hash:
        return expected_info_hash.lower()
    if content is None:
        return None
    try:
        return compute_info_hash(content)
    except TorrentMetainfoError:
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
            # In inglese (audit 2026-10-18): finisce nel messaggio del seed
            # job e nel 409 del retry, come gli altri errori mostrati.
            raise TorrentAddTimeoutError(
                f"Torrent {expected} did not show up in {where} within {poll_timeout:g}s of adding it"
                if expected is not None else
                f"No new torrent showed up in {where} within {poll_timeout:g}s of adding it"
            )
        time.sleep(poll_interval)


def require_recheck(force_recheck: bool) -> None:
    if not force_recheck:
        raise ValueError(
            "force_recheck=False is not allowed: a real recheck is a functional requirement, "
            "see docs/SPEC.md section 8."
        )
