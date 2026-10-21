"""Adapter Deluge, sull'API JSON-RPC della sua Web UI (docs/SPEC.md sezione 5).

Perché la Web UI e httpx, non il demone con deluge-client: base_url è sempre
un URL http(s) (nazgarr/api/types.py), e la Web UI è quello che un utente
espone e conosce (http://deluge:8112, la sua password). Il demone (porta
58846, rencode su TLS, utenti in un file auth a parte) vorrebbe un'altra
configurazione e una libreria in più. L'API JSON della Web UI è un POST
`{"method", "params", "id"}` su `/json`, col cookie di `auth.login`, e
inoltra ogni metodo `core.*` del demone: bastano httpx e una ventina di righe.

Utente: non usato (la Web UI di Deluge ha solo la password).

Verificato contro un'istanza reale (lscr.io/linuxserver/deluge, Deluge
2.2.0): tests/integration/test_real_clients.py.

- La Web UI può non essere collegata a un demone (al primo avvio non lo
  è): se `web.connected` è falso ci si collega al primo demone del suo
  elenco (`web.get_hosts`), quello locale nelle installazioni comuni.
- Un .torrent locale va col suo contenuto (`core.add_torrent_file`, base64),
  mai col percorso: il client non vede la cartella dati di Nazgarr. Un URL
  resta un URL (`core.add_torrent_url`, o `core.add_torrent_magnet`).
- L'opzione `download_location` è la save path, passata così com'è.
- Recheck: `core.force_recheck`. skip_check_verified usa `seed_mode` di
  libtorrent (Deluge 2): il torrent entra già completo, senza recheck.
- stopped (un reseed): `add_paused`; force_recheck lo avvia per il
  controllo e lo rimette in pausa dopo, `core.resume_torrent` lo avvia.
  Subito dopo force_recheck lo `state` di Deluge resta "Paused" finché il
  demone non elabora l'avvio del controllo: add_torrent e recheck aspettano
  (al più CHECK_START_TIMEOUT) che la lettura non sia più quella di un
  recheck fallito, "Paused" sotto il 100% (audit 2026-10-18).
- Etichette: categoria = label del plugin Label, solo se il plugin è acceso
  (Nazgarr non accende plugin del client). Le label di Deluge sono in
  minuscolo ([a-z0-9_-]); una label che non c'è si crea. Deluge non ha tag:
  si ignorano. list_categories() sono le label (vuota senza il plugin).
- Stato nativo: lo `state` di Deluge ("Checking", "Seeding", "Paused",
  "Queued", "Error"...). Il progresso di Deluge va da 0 a 100. Lo `state` è
  quello che Deluge tiene in memoria e aggiorna a ogni evento di
  libtorrent, `paused` è il flag di libtorrent letto adesso. Non hanno
  ancora un esito: "Queued" (Deluge lo calcola da paused e auto-managed di
  libtorrent: in coda per il controllo o per un posto), un torrent in pausa
  con un altro stato (subito dopo force_recheck Deluge lo mostra per un
  attimo "Seeding" o "Queued" al 0%, visto sull'istanza reale) e uno
  "Paused" che in libtorrent non lo è più (force_recheck l'ha avviato per
  il controllo, e Deluge non l'ha ancora visto). "Paused" sotto il 100%,
  col flag, è un recheck fallito: force_recheck rimette in pausa dopo il
  controllo un torrent che lo era. Mai `is_auto_managed`: è l'opzione
  salvata di Deluge, vera anche per un torrent in pausa (audit 2026-10-18:
  un reseed fallito restava "pending" per sempre).
"""

import base64
import logging
import os
import time
from collections.abc import Callable

from nazgarr.adapters.torrent_client.base import (
    ClientTorrentFileInfo,
    ClientTorrentInfo,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    TorrentStatus,
    largest_file_only,
    local_torrent_bytes,
    number,
    require_recheck,
    seeders,
    wait_for_hash,
)
from nazgarr.core import net_guard

logger = logging.getLogger(__name__)

CHECKING = {"Checking", "Allocating"}
ERROR = {"Error"}
STATUS_KEYS = ["hash", "state", "progress", "total_wanted", "total_done", "paused"]
# Quanto si aspetta, dopo force_recheck su un torrent in pausa, che Deluge
# mostri il controllo partito (_wait_for_check). Basta poco: il flag di
# libtorrent cambia subito, lo stato all'evento dopo. Solo un controllo
# fallito già finito prima della prima lettura (un torrent piccolo) lo
# aspetta tutto, ed è comunque l'esito giusto.
CHECK_START_TIMEOUT = 5.0
INFO_KEYS = [
    "hash", "name", "save_path", "state", "label", "trackers", "files", "ratio", "seeding_time", "time_added",
    "total_seeds",
]
# La verifica dei percorsi (list_largest_files): solo save path e file.
LARGEST_KEYS = ["hash", "name", "save_path", "state", "files"]
NOT_AUTHENTICATED = 1  # codice d'errore della Web UI senza sessione


class DelugeError(Exception):
    pass


class DelugeAdapter(TorrentClientAdapter):
    can_add_stopped = True

    def __init__(
        self,
        base_url: str,
        password: str | None,
        http_client=None,
        poll_interval: float = 0.5,
        poll_timeout: float = 30.0,
        connect_timeout: float = 10.0,
    ):
        self.url = base_url.rstrip("/") + "/json"
        self.password = password or ""
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.connect_timeout = connect_timeout
        self._id = 0
        self._ready = False
        # net_guard.http_client: connesso solo all'indirizzo controllato nel
        # momento della connessione, come ogni URL scritto da un utente. La
        # LAN resta raggiungibile: lì vivono i client.
        self._client = http_client if http_client is not None else net_guard.http_client(timeout=60.0)

    # --- trasporto -------------------------------------------------------------

    def _raw_call(self, method: str, *params):
        self._id += 1
        response = self._client.post(self.url, json={"method": method, "params": list(params), "id": self._id})
        response.raise_for_status()
        data = response.json()
        return data.get("result"), data.get("error")

    def _call(self, method: str, *params):
        if not self._ready:
            self._connect()
        result, error = self._raw_call(method, *params)
        if error and error.get("code") == NOT_AUTHENTICATED:  # sessione scaduta: di nuovo il login
            self._ready = False
            self._connect()
            result, error = self._raw_call(method, *params)
        if error:
            raise DelugeError(f"Deluge {method}: {error.get('message')}")
        return result

    def _connect(self) -> None:
        ok, error = self._raw_call("auth.login", self.password)
        if error or not ok:
            raise DelugeError("Deluge: login failed (check the Web UI password)")
        connected, _ = self._raw_call("web.connected")
        if not connected:
            hosts, error = self._raw_call("web.get_hosts")
            if error or not hosts:
                raise DelugeError("Deluge: the Web UI is not connected to a daemon and lists none")
            self._raw_call("web.connect", hosts[0][0])
            deadline = time.monotonic() + self.connect_timeout
            while not self._raw_call("web.connected")[0]:
                if time.monotonic() >= deadline:
                    raise DelugeError("Deluge: the Web UI could not connect to its daemon")
                time.sleep(self.poll_interval)
        self._ready = True

    # --- contratto ---------------------------------------------------------------

    def _hashes(self) -> set[str]:
        return set((self._call("core.get_torrents_status", {}, ["hash"]) or {}).keys())

    def count_torrents(self) -> int:
        return len(self._hashes())  # solo gli hash, senza i file

    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
        category: str | None = None, tags: list[str] | None = None, content_layout: str = "Original",
        stopped: bool = False,
    ) -> str:
        require_recheck(force_recheck)
        before = self._hashes()
        expected = expected_info_hash.lower() if expected_info_hash else None
        if expected and expected in {h.lower() for h in before}:
            raise TorrentAlreadyInClientError(
                f"Torrent {expected} is already in the client (possibly with another save path): nothing added"
            )
        # Fermo per un reseed: force_recheck di Deluge avvia il torrent per il
        # controllo e lo rimette in pausa dopo, se lo era (core.resume_torrent
        # lo fa partire al recheck riuscito).
        options = {"download_location": save_path, "add_paused": bool(stopped),
                   "seed_mode": bool(skip_check_verified)}
        content = local_torrent_bytes(torrent_file_or_url)
        try:
            if content is not None:
                added = self._call(
                    "core.add_torrent_file", os.path.basename(torrent_file_or_url),
                    base64.b64encode(content).decode("ascii"), options,
                )
            elif torrent_file_or_url.startswith("magnet:"):
                added = self._call("core.add_torrent_magnet", torrent_file_or_url, options)
            else:
                added = self._call("core.add_torrent_url", torrent_file_or_url, options)
        except DelugeError as exc:
            if "already in session" in str(exc).lower():
                raise TorrentAlreadyInClientError(
                    f"Torrent {expected or ''} is already in the client (possibly with another save path): "
                    "nothing added"
                ) from exc
            raise
        info_hash = wait_for_hash(
            self._hashes, before, expected or (added.lower() if isinstance(added, str) and added else None),
            self.poll_interval, self.poll_timeout, "Deluge",
        )
        if category:
            self._set_label(info_hash, category)
        if tags:
            logger.debug("Deluge non ha tag: ignorati %s", tags)
        if not skip_check_verified:
            self._call("core.force_recheck", [info_hash])
            if stopped:
                self._wait_for_check(info_hash)
        return info_hash

    def _wait_for_check(self, info_hash: str) -> None:
        """Dopo force_recheck su un torrent in pausa (un reseed, o il suo
        retry): finché Deluge non vede il controllo partito, la sua lettura
        può essere "Paused" sotto il 100%, cioè quella di un recheck fallito,
        e un reconcile in quel momento lo darebbe per fallito. Si aspetta, al
        più CHECK_START_TIMEOUT, che la lettura cambi: controllo in corso,
        flag di pausa tolto, o completo. Il torrent intanto non scarica
        niente (lo si controlla soltanto). Un torrent avviato non aspetta.
        Un errore qui non annulla il recheck, già chiesto: lo si lascia."""
        deadline = time.monotonic() + min(CHECK_START_TIMEOUT, self.poll_timeout)
        while True:
            try:
                torrent = self._call("core.get_torrent_status", info_hash.lower(), STATUS_KEYS) or {}
            except DelugeError:
                logger.debug("Deluge: stato di %s non letto dopo force_recheck", info_hash, exc_info=True)
                return
            looks_failed = torrent.get("state") == "Paused" and _status(torrent) == "failed"
            if not looks_failed or time.monotonic() >= deadline:
                return
            time.sleep(self.poll_interval)

    def _label_plugin(self) -> bool:
        return "Label" in (self._call("core.get_enabled_plugins") or [])

    def _set_label(self, info_hash: str, category: str) -> None:
        if not self._label_plugin():
            logger.warning("Deluge: plugin Label spento, categoria %r non applicata", category)
            return
        label = category.strip().lower()
        try:
            if label not in (self._call("label.get_labels") or []):
                self._call("label.add", label)
            self._call("label.set_torrent", info_hash, label)
        except DelugeError:
            # Il torrent è già aggiunto: una label non valida non lo annulla.
            logger.warning("Deluge: label %r non applicata a %s", label, info_hash, exc_info=True)

    def list_categories(self) -> list[str]:
        if not self._label_plugin():
            return []
        return sorted(self._call("label.get_labels") or [], key=str.lower)

    def recheck(self, info_hash: str) -> None:
        self._call("core.force_recheck", [info_hash.lower()])
        # Un torrent in pausa (il retry di un reseed fallito): come all'aggiunta.
        self._wait_for_check(info_hash)

    def start(self, info_hash: str) -> None:
        # Una lista, come stop: Deluge 1.3 vuole una lista, il 2 accetta entrambi.
        self._call("core.resume_torrent", [info_hash.lower()])

    def stop(self, info_hash: str) -> None:
        # Una lista, come force_recheck: Deluge 1.3 vuole una lista, il 2 accetta entrambi.
        self._call("core.pause_torrent", [info_hash.lower()])

    def remove_torrent(self, info_hash: str, delete_files: bool) -> None:
        self._call("core.remove_torrent", info_hash.lower(), delete_files)

    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        torrent = self._call("core.get_torrent_status", info_hash.lower(), STATUS_KEYS) or {}
        if not torrent:
            raise ValueError(f"Torrent {info_hash} non trovato nel client")
        state = torrent.get("state") or ""
        progress = float(torrent.get("progress") or 0.0) / 100.0
        recheck_status = _status(torrent)
        wanted, done = torrent.get("total_wanted"), torrent.get("total_done")
        return TorrentStatus(
            info_hash=torrent.get("hash") or info_hash.lower(), state=state, recheck_status=recheck_status,
            progress=progress,
            incomplete=recheck_status == "failed" and state not in ERROR,
            amount_left=max(int(wanted) - int(done), 0) if wanted is not None and done is not None else None,
        )

    def get_torrent_info(self, info_hash: str) -> ClientTorrentInfo | None:
        torrent = self._call("core.get_torrent_status", info_hash.lower(), INFO_KEYS) or {}
        return self._info(info_hash.lower(), torrent) if torrent else None

    def list_torrents(self, on_progress: Callable[[int, int], None] | None = None) -> list[ClientTorrentInfo]:
        torrents = self._call("core.get_torrents_status", {}, INFO_KEYS) or {}
        result = []
        for i, (torrent_id, torrent) in enumerate(torrents.items()):
            result.append(self._info(torrent_id, torrent))
            if on_progress is not None:
                on_progress(i + 1, len(torrents))
        return result

    def list_largest_files(self, limit: int | None = None) -> list[ClientTorrentInfo]:
        torrents = self._call("core.get_torrents_status", {}, LARGEST_KEYS) or {}
        return [largest_file_only(self._info(torrent_id, torrent))
                for torrent_id, torrent in list(torrents.items())[:limit]]

    @staticmethod
    def _info(torrent_id: str, torrent: dict) -> ClientTorrentInfo:
        return ClientTorrentInfo(
            info_hash=torrent.get("hash") or torrent_id,
            name=torrent.get("name") or "",
            save_path=(torrent.get("save_path") or "").rstrip("/") or "/",
            state=torrent.get("state") or "",
            category=torrent.get("label") or None,  # presente solo col plugin Label
            tracker_url=next((t.get("url") for t in torrent.get("trackers") or [] if t.get("url")), None),
            files=[
                ClientTorrentFileInfo(path_in_torrent=f.get("path", ""), size_bytes=int(f.get("size") or 0))
                for f in torrent.get("files") or []
            ],
            ratio=number(torrent.get("ratio"), float) if (torrent.get("ratio") or 0) >= 0 else None,
            seeding_time_seconds=number(torrent.get("seeding_time"), int),
            added_on=number(torrent.get("time_added"), int),
            swarm_seeders=seeders(torrent.get("total_seeds")),
        )


def _status(torrent: dict) -> str:
    """L'esito del recheck da una lettura di Deluge (la docstring del modulo):
    "pending", "ok" o "failed"."""
    state = torrent.get("state") or ""
    paused = torrent.get("paused")
    if state in CHECKING:
        return "pending"
    if state in ERROR:
        return "failed"
    if float(torrent.get("progress") or 0.0) >= 100.0:
        return "ok"
    if state == "Queued" or (paused is True and state != "Paused") or (paused is False and state == "Paused"):
        # In coda in libtorrent, o uno stato che Deluge non ha ancora
        # aggiornato dopo force_recheck: il recheck non ha ancora detto niente.
        return "pending"
    # "Paused" in pausa davvero (force_recheck l'ha rimesso in pausa dopo il
    # controllo), o avviato e incompleto: dati che non corrispondono.
    return "failed"
