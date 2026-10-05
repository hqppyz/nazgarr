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
- il timing del polling in _wait_for_new_hash

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
import os
import time
from collections.abc import Callable

from nazgarr.adapters.torrent_client.base import (
    CHECKING_STATES,
    CONTENT_LAYOUTS,
    ERROR_STATES,
    ClientTorrentFileInfo,
    ClientTorrentInfo,
    TorrentAddTimeoutError,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    TorrentStatus,
    seeders,
)

logger = logging.getLogger(__name__)


def _number(value, kind):
    try:
        return kind(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class QBittorrentAdapter(TorrentClientAdapter):
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
    ) -> str:
        if not force_recheck:
            raise ValueError(
                "force_recheck=False non è permesso: il recheck reale è "
                "un requisito funzionale, vedi docs/SPEC.md sezione 8."
            )

        before_hashes = {t.hash for t in self._client.torrents_info()}
        expected = expected_info_hash.lower() if expected_info_hash else None
        if expected and expected in {h.lower() for h in before_hashes}:
            raise TorrentAlreadyInClientError(
                f"Torrent {expected} is already in the client (possibly with another save path): nothing added"
            )
        # Un .torrent locale (un upload: sta nella cartella dati di Nazgarr)
        # si manda col suo contenuto: il client non vede quel percorso, e
        # con "urls" lo cercherebbe nel suo filesystem (No such file or
        # directory). Un URL (il link del tracker di un reseed) resta un URL.
        if os.path.isfile(torrent_file_or_url):
            with open(torrent_file_or_url, "rb") as f:
                source = {"torrent_files": f.read()}
        else:
            source = {"urls": torrent_file_or_url}
        self._client.torrents_add(
            **source,
            save_path=save_path,
            is_skip_checking=skip_check_verified,
            use_auto_torrent_management=False,
            content_layout=content_layout,
            # Avviato e senza condizione di arresto, qualunque cosa dicano le
            # preferenze del client ("non avviare automaticamente", "fermati
            # dopo il controllo dei file"): un reseed o un upload deve seedare.
            is_stopped=False,
            stop_condition="None",
            **({"category": category} if category else {}),
            **({"tags": ",".join(tags)} if tags else {}),
        )
        info_hash = self._wait_for_new_hash(before_hashes, expected)
        if not skip_check_verified:
            self._client.torrents_recheck(torrent_hashes=info_hash)
        self.start(info_hash)  # una versione che ignora "stopped" all'aggiunta
        return info_hash

    def start(self, info_hash: str) -> None:
        self._client.torrents_start(torrent_hashes=info_hash)

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

    def _wait_for_new_hash(self, before_hashes: set[str], expected: str | None = None) -> str:
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            current_hashes = {t.hash for t in self._client.torrents_info()}
            if expected is not None:
                found = next((h for h in current_hashes if h.lower() == expected), None)
                if found is not None:
                    return found
                time.sleep(self.poll_interval)
                continue
            new_hashes = current_hashes - before_hashes
            if new_hashes:
                if len(new_hashes) > 1:
                    logger.warning("Più torrent nuovi rilevati dopo add_torrent: %s", new_hashes)
                return next(iter(new_hashes))
            time.sleep(self.poll_interval)
        raise TorrentAddTimeoutError(
            f"Nessun nuovo torrent rilevato in qBittorrent entro {self.poll_timeout}s dall'aggiunta"
        )

    def list_categories(self) -> list[str]:
        return sorted(self._client.torrents_categories().keys(), key=str.lower)

    def recheck(self, info_hash: str) -> None:
        self._client.torrents_recheck(torrent_hashes=info_hash)

    def remove_torrent(self, info_hash: str, delete_files: bool) -> None:
        self._client.torrents_delete(delete_files=delete_files, torrent_hashes=info_hash)

    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        results = self._client.torrents_info(torrent_hashes=info_hash)
        if not results:
            raise ValueError(f"Torrent {info_hash} non trovato nel client")
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
        torrent = results[0]
        return ClientTorrentInfo(
            info_hash=torrent.hash,
            name=torrent.name,
            save_path=torrent.save_path,
            state=torrent.state,
            category=getattr(torrent, "category", "") or None,
            tracker_url=getattr(torrent, "tracker", "") or None,
            files=[
                ClientTorrentFileInfo(path_in_torrent=f.name, size_bytes=f.size)
                for f in self._client.torrents_files(torrent_hash=torrent.hash)
            ],
        )

    def list_torrents(self, on_progress: Callable[[int, int], None] | None = None) -> list[ClientTorrentInfo]:
        result = []
        torrents = list(self._client.torrents_info())
        for i, torrent in enumerate(torrents):
            files = [
                ClientTorrentFileInfo(path_in_torrent=f.name, size_bytes=f.size)
                for f in self._client.torrents_files(torrent_hash=torrent.hash)
            ]
            result.append(
                ClientTorrentInfo(
                    info_hash=torrent.hash,
                    name=torrent.name,
                    save_path=torrent.save_path,
                    state=torrent.state,
                    category=getattr(torrent, "category", "") or None,
                    tracker_url=getattr(torrent, "tracker", "") or None,
                    files=files,
                    ratio=_number(getattr(torrent, "ratio", None), float),
                    seeding_time_seconds=_number(getattr(torrent, "seeding_time", None), int),
                    added_on=_number(getattr(torrent, "added_on", None), int),
                    swarm_seeders=seeders(getattr(torrent, "num_complete", None)),
                )
            )
            if on_progress is not None:
                on_progress(i + 1, len(torrents))
        return result
