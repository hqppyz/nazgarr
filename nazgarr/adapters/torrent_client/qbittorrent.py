"""Adapter qBittorrent — prima implementazione concreta, via libreria
qbittorrent-api.

NON validato contro un'istanza qBittorrent reale (nessuna disponibile in
fase di sviluppo) — solo contro un client mockato nei test. Da verificare
prima di un uso reale, in particolare:
- la mappatura stato nativo -> RecheckStatus (CHECKING_STATES/ERROR_STATES)
- il campo `tracker` su torrents_info(): popolato solo se un tracker è
  correntemente raggiungibile/funzionante, può essere vuoto anche con
  tracker validi configurati — trattato quindi come best-effort, mai come
  fonte affidabile al 100% (qui usato solo per popolare
  client_torrent.tracker_url a scopo informativo, non per logica di match)
- il timing del polling in base.wait_for_hash

torrents_add() non garantisce di ritornare l'info_hash su ogni versione
dell'API qBittorrent: per essere version-agnostic, l'hash viene ricavato
confrontando l'elenco dei torrent prima/dopo l'aggiunta (diff), mai
fidandosi del solo valore di ritorno di torrents_add() — stesso approccio
di ratio-guardian.

"qui" (gestore multi-istanza per qBittorrent, docs/SPEC.md sezione 15) NON
usa questo adapter: espone una propria API di aggregazione (auth via
X-API-Key, percorsi sotto /api/instances/{id}/...), diversa dalla WebUI API
nativa di qBittorrent che qbittorrent-api si aspetta — confermato contro il
suo swagger/OpenAPI reale, non solo dedotto. Vedi nazgarr/adapters/torrent_client/qui.py.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from nazgarr.adapters.torrent_client.base import (
    CHECKING_STATES,
    CONTENT_LAYOUTS,
    ERROR_STATES,
    ClientTorrentFileInfo,
    ClientTorrentInfo,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    TorrentStatus,
    expected_hash,
    largest_file_only,
    local_torrent_bytes,
    number,
    require_recheck,
    seeders,
    wait_for_hash,
)
from nazgarr.core import net_guard

logger = logging.getLogger(__name__)

# Richieste dei file in parallelo durante l'indicizzazione: qBittorrent non
# ha un endpoint per i file di più torrent (torrents/files vuole un hash),
# e una dopo l'altra costavano un giro di rete ciascuna. qBittorrent
# risponde alla WebUI da un solo thread, quindi in rete locale si guadagna
# poco; si guadagna con un client remoto o dietro un proxy (audit
# 2026-10-18). Pochi, per non caricare il client.
FILE_WORKERS = 4


class QBittorrentAdapter(TorrentClientAdapter):
    can_add_stopped = True

    def __init__(
        self,
        base_url: str,
        username: str | None,
        password: str | None,
        client=None,
        poll_interval: float = 0.5,
        poll_timeout: float = 30.0,
    ):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        if client is not None:
            self._client = client
        else:
            import qbittorrentapi

            # qbittorrent-api va con requests, che net_guard non sa agganciare
            # alla connessione (gli altri adapter usano net_guard.http_client):
            # l'indirizzo si ricontrolla qui, a ogni adapter costruito (uno per
            # operazione), non solo quando si salva. Un DNS cambiato dopo il
            # salvataggio verso i metadati del cloud non passa; resta la
            # finestra fra questo controllo e la connessione di requests. Un
            # host senza schema (qbittorrent-api lo accetta) vale come http.
            net_guard.check_url(base_url if "://" in base_url else f"http://{base_url}")
            self._client = qbittorrentapi.Client(host=base_url, username=username, password=password)

    def close(self) -> None:
        """Logout: ogni login apre una sessione nel client, che resta viva
        un'ora; con un adapter per operazione si accumulavano."""
        logout = getattr(self._client, "auth_log_out", None)
        # Solo se c'è una sessione (il cookie SID): un adapter mai usato non
        # ha fatto login, e non va interrogato il client per niente.
        if callable(logout) and getattr(self._client, "_SID", None):
            try:
                logout()
            except Exception:  # client già irraggiungibile: niente da chiudere
                logger.debug("Logout da qBittorrent fallito", exc_info=True)

    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
        category: str | None = None, tags: list[str] | None = None, content_layout: str = "Original",
        stopped: bool = False,
    ) -> str:
        require_recheck(force_recheck)

        before_hashes = self._hashes()
        # Un .torrent locale (un upload, o quello che l'esecutore ha appena
        # scaricato e controllato) si manda col suo contenuto: il client non
        # vede quel percorso, e con "urls" lo cercherebbe nel suo filesystem
        # (No such file or directory). Un URL resta un URL.
        content = local_torrent_bytes(torrent_file_or_url)
        source = {"torrent_files": content} if content is not None else {"urls": torrent_file_or_url}
        # torrents_add non dice l'hash su ogni versione dell'API, e ignora in
        # silenzio un duplicato: lo si aspetta per hash (quello del chiamante
        # o dei byte mandati), e il diff prima/dopo resta solo per un URL.
        expected = expected_hash(expected_info_hash, content)
        if expected and expected in before_hashes:
            raise TorrentAlreadyInClientError(
                f"Torrent {expected} is already in the client (possibly with another save path): nothing added"
            )
        self._client.torrents_add(
            **source,
            save_path=save_path,
            is_skip_checking=skip_check_verified,
            use_auto_torrent_management=False,
            content_layout=content_layout,
            # Fermo solo se lo chiede il chiamante (un reseed, che parte dopo
            # il recheck riuscito): il recheck di un torrent fermo qBittorrent
            # lo fa lo stesso, avviandolo per il controllo e fermandolo dopo.
            # Altrimenti avviato e senza condizione di arresto, qualunque
            # cosa dicano le preferenze ("non avviare automaticamente",
            # "fermati dopo il controllo dei file"): un upload deve seedare.
            # qbittorrent-api manda sia "stopped" (WebUI API 2.11+) sia
            # "paused" (qBittorrent 4).
            is_stopped=stopped,
            stop_condition="None",
            **({"category": category} if category else {}),
            **({"tags": ",".join(tags)} if tags else {}),
        )
        info_hash = wait_for_hash(self._hashes, before_hashes, expected, self.poll_interval,
                                  self.poll_timeout, "qBittorrent")
        if not skip_check_verified:
            self._client.torrents_recheck(torrent_hashes=info_hash)
        if not stopped:
            self.start(info_hash)  # una versione che ignora "stopped" all'aggiunta
        return info_hash

    def start(self, info_hash: str) -> None:
        self._client.torrents_start(torrent_hashes=info_hash)

    def stop(self, info_hash: str) -> None:
        # qbittorrent-api usa "pause" sulle WebUI API prima della 2.11 (qBittorrent 4).
        self._client.torrents_stop(torrent_hashes=info_hash)

    def content_layout(self) -> str:
        prefs = self._client.app_preferences()
        layout = prefs.get("torrent_content_layout")
        if layout in CONTENT_LAYOUTS:
            return layout
        # Prima della 4.3.2 c'era solo "crea sottocartella" sì/no.
        subfolder = prefs.get("create_subfolder_enabled")
        if subfolder is None:
            return "Original"
        return "Original" if subfolder else "NoSubfolder"

    def _hashes(self) -> set[str]:
        return {t.hash.lower() for t in self._client.torrents_info()}

    def list_categories(self) -> list[str]:
        return sorted(self._client.torrents_categories().keys(), key=str.lower)

    def recheck(self, info_hash: str) -> None:
        self._client.torrents_recheck(torrent_hashes=info_hash)

    def remove_torrent(self, info_hash: str, delete_files: bool) -> None:
        self._client.torrents_delete(delete_files=delete_files, torrent_hashes=info_hash)

    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        results = self._client.torrents_info(torrent_hashes=info_hash)
        if not results:
            raise ValueError(f"Torrent {info_hash} not found in the client")
        torrent = results[0]
        state = torrent.state

        if state in CHECKING_STATES:
            recheck_status = "pending"
        elif state in ERROR_STATES:
            recheck_status = "failed"
        elif torrent.progress >= 1.0:
            recheck_status = "ok"
        else:
            # Dopo un recheck, dati incompleti significa che il file
            # hardlinkato non corrisponde a quanto atteso dal torrent.
            recheck_status = "failed"

        return TorrentStatus(
            info_hash=torrent.hash, state=state, recheck_status=recheck_status, progress=torrent.progress,
            incomplete=state not in ERROR_STATES and state not in CHECKING_STATES and torrent.progress < 1.0,
            amount_left=getattr(torrent, "amount_left", None),
        )

    def get_torrent_info(self, info_hash: str) -> ClientTorrentInfo | None:
        results = self._client.torrents_info(torrent_hashes=info_hash)
        if not results:
            return None
        return self._info(results[0], self._files(results[0].hash))

    def count_torrents(self) -> int:
        return len(self._client.torrents_info())

    def list_torrents(self, on_progress: Callable[[int, int], None] | None = None) -> list[ClientTorrentInfo]:
        # L'elenco nel thread chiamante (anche il login, se serve), poi i
        # file FILE_WORKERS alla volta; ordine e avanzamento restano qui.
        torrents = list(self._client.torrents_info())
        return [self._info(torrent, torrent_files)
                for torrent, torrent_files in zip(torrents, self._files_of(torrents, on_progress), strict=True)]

    def list_largest_files(self, limit: int | None = None) -> list[ClientTorrentInfo]:
        # Nessun endpoint per i file di più torrent: le richieste restano una
        # per torrent, ma solo per quelli che la verifica guarda.
        torrents = list(self._client.torrents_info())[:limit]
        return [largest_file_only(self._info(torrent, torrent_files))
                for torrent, torrent_files in zip(torrents, self._files_of(torrents), strict=True)]

    def _files_of(self, torrents, on_progress: Callable[[int, int], None] | None = None,
                  ) -> list[list[ClientTorrentFileInfo]]:
        """I file di ogni torrent, FILE_WORKERS richieste alla volta, nell'ordine dei torrent."""
        files: list[list[ClientTorrentFileInfo] | None] = [None] * len(torrents)
        pool = ThreadPoolExecutor(max_workers=FILE_WORKERS)
        try:
            futures = {pool.submit(self._files, t.hash): i for i, t in enumerate(torrents)}
            for done, future in enumerate(as_completed(futures), start=1):
                files[futures[future]] = future.result()
                if on_progress is not None:
                    on_progress(done, len(torrents))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)  # stop o errore: niente richieste rimaste in coda
        return [f or [] for f in files]

    def _files(self, info_hash: str) -> list[ClientTorrentFileInfo]:
        return [
            ClientTorrentFileInfo(path_in_torrent=f.name, size_bytes=f.size)
            for f in self._client.torrents_files(torrent_hash=info_hash)
        ]

    @staticmethod
    def _info(torrent, files: list[ClientTorrentFileInfo]) -> ClientTorrentInfo:
        return ClientTorrentInfo(
            info_hash=torrent.hash,
            name=torrent.name,
            save_path=torrent.save_path,
            state=torrent.state,
            category=getattr(torrent, "category", "") or None,
            tracker_url=getattr(torrent, "tracker", "") or None,
            files=files,
            ratio=number(getattr(torrent, "ratio", None), float),
            seeding_time_seconds=number(getattr(torrent, "seeding_time", None), int),
            added_on=number(getattr(torrent, "added_on", None), int),
            swarm_seeders=seeders(getattr(torrent, "num_complete", None)),
        )
