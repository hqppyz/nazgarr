"""Adapter rTorrent / ruTorrent, sull'XML-RPC di rTorrent (docs/SPEC.md
sezione 5, adapter_type "rutorrent").

Perché XML-RPC con xmlrpc.client della libreria standard sopra httpx, e non
una libreria dedicata: rTorrent parla solo XML-RPC, e la libreria standard
sa già serializzarlo e leggerlo (`dumps`/`loads`); httpx porta la richiesta
(autenticazione Basic, timeout, un client sostituibile nei test). Nessuna
dipendenza in più.

base_url, uno dei due endpoint XML-RPC:
- quello di rTorrent esposto dal web server (di solito `/RPC2`, SCGI);
- il plugin httprpc di ruTorrent, `.../plugins/httprpc/action.php`, che
  inoltra a rTorrent le richieste XML-RPC.
Un base_url che non finisce in `.php` né contiene `RPC` è la radice di
ruTorrent: si aggiunge `/plugins/httprpc/action.php`. Utente e password:
l'autenticazione HTTP Basic del web server, se c'è.

Verificato contro un'istanza reale (crazymax/rtorrent-rutorrent, ruTorrent
5.3 con rTorrent 0.16), su entrambi gli endpoint:
tests/integration/test_real_clients.py. Il proxy di ruTorrent 5.3 (modo
"sanitize") tratta da "untrusted" ogni chiamata che non sa ricostruire, e
rTorrent 0.16.10+ rifiuta lì i comandi che scrivono (es. d.directory.set da
solo, execute.*). Quindi:
- la save path e la label viaggiano come comandi del load stesso
  (`d.directory.set="..."`, `d.custom1.set="..."`), che il proxy accetta;
- remove_torrent con delete_files, via ruTorrent, passa dalla sua azione
  `removewithdata` (il plugin erasedata, lo stesso "Rimuovi e cancella i
  dati" della sua UI), che cancella i file pochi secondi dopo. ruTorrent
  prepara i suoi plugin la prima volta che se ne apre la UI: prima, quella
  azione risponde false e l'adapter lo segnala.

- Un .torrent locale va col suo contenuto (`load.raw`, i byte del file),
  mai col percorso: il client non vede la cartella dati di Nazgarr. Un URL
  (http/https/magnet) resta un URL (`load.normal`), lo scarica rTorrent.
- Il torrent entra fermo, poi il recheck (`d.check_hash`) e `d.start`. La
  save path è passata così com'è: per un torrent multi-file rTorrent ci
  aggiunge la cartella del torrent, come qBittorrent.
- L'hash si trova nell'elenco (`download_list`), atteso o per differenza,
  come negli altri adapter. rTorrent usa hash maiuscoli: l'adapter li
  restituisce in minuscolo e li rimette maiuscoli nelle chiamate.
- rTorrent non sa aggiungere un torrent già completo senza ricontrollarlo
  (servirebbe scrivere dati di fast-resume nel .torrent):
  can_skip_recheck = False, il recheck c'è sempre.
- Etichette: categoria = label di ruTorrent (`d.custom1`, che ruTorrent
  salva URL-encoded). rTorrent non ha tag: si ignorano. list_categories()
  sono le label già usate dai torrent del client (ruTorrent non ne tiene un
  elenco a parte).
- remove_torrent: `d.erase`. rTorrent non cancella mai i dati; con
  delete_files, sull'endpoint diretto si cancellano i soli file del torrent
  (`f.frozen_path`) e le sue cartelle rimaste vuote, con `execute.throw`
  dentro il client (rm/rmdir nel suo filesystem, che Nazgarr non vede).
- Stato nativo, composto: "checking" (hash in corso), "stopped" (d.state 0),
  "paused" (avviato ma inattivo, come lo chiama ruTorrent), "seeding",
  "downloading".
"""

import logging
import os
import time
import xmlrpc.client
from collections.abc import Callable
from urllib.parse import quote, unquote, urlsplit

from nazgarr.adapters.torrent_client.base import (
    ClientTorrentFileInfo,
    ClientTorrentInfo,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    TorrentStatus,
    local_torrent_bytes,
    require_recheck,
    wait_for_hash,
)
from nazgarr.torrents.metainfo import compute_info_hash

logger = logging.getLogger(__name__)

HTTPRPC = "/plugins/httprpc/action.php"
# Campi letti per ogni torrent, nell'ordine di _rows().
FIELDS = (
    "d.hash=", "d.name=", "d.directory=", "d.is_multi_file=", "d.state=", "d.is_active=", "d.complete=",
    "d.hashing=", "d.is_hash_checking=", "d.custom1=", "d.ratio=", "d.load_date=", "d.timestamp.finished=",
    "d.size_bytes=", "d.completed_bytes=", "d.left_bytes=",
)
KEYS = [f[2:-1].replace("timestamp.", "").replace(".", "_") for f in FIELDS]
CHECKING = "checking"


def _rpc_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    path = urlsplit(base).path
    if path.endswith(".php") or "RPC" in path.upper():
        return base
    return base + HTTPRPC


def _quoted(value: str) -> str:
    """Un argomento di un comando rTorrent fra virgolette: virgole e spazi
    restano dentro, virgolette e backslash si escapano."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _state(row: dict) -> str:
    if row["hashing"] or row["is_hash_checking"]:
        return CHECKING
    if not row["state"]:
        return "stopped"
    if not row["is_active"]:
        return "paused"
    return "seeding" if row["complete"] else "downloading"


class RTorrentAdapter(TorrentClientAdapter):
    can_skip_recheck = False

    def __init__(
        self,
        base_url: str,
        username: str | None,
        password: str | None,
        http_client=None,
        poll_interval: float = 0.5,
        poll_timeout: float = 30.0,
    ):
        self.url = _rpc_url(base_url)
        self.via_rutorrent = urlsplit(self.url).path.endswith(".php")
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        if http_client is not None:
            self._client = http_client
        else:
            import httpx

            auth = (username, password or "") if username else None
            self._client = httpx.Client(auth=auth, timeout=60.0)

    def _call(self, method: str, *params):
        body = xmlrpc.client.dumps(params, method)
        response = self._client.post(self.url, content=body.encode("utf-8"), headers={"Content-Type": "text/xml"})
        response.raise_for_status()
        result, _ = xmlrpc.client.loads(response.content, use_builtin_types=True)  # un Fault si solleva qui
        return result[0] if result else None

    def _hashes(self) -> set[str]:
        return set(self._call("download_list", "", "main") or [])

    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
        category: str | None = None, tags: list[str] | None = None, content_layout: str = "Original",
    ) -> str:
        require_recheck(force_recheck)
        before = {h.lower() for h in self._hashes()}
        expected = expected_info_hash.lower() if expected_info_hash else None
        if expected and expected in before:
            raise TorrentAlreadyInClientError(
                f"Torrent {expected} is already in the client (possibly with another save path): nothing added"
            )
        # La save path e la label viaggiano come comandi del load: così
        # passano anche dal proxy di ruTorrent (vedi il docstring del modulo).
        commands = [f"d.directory.set={_quoted(save_path)}"]
        if category:
            commands.append(f"d.custom1.set={_quoted(quote(category, safe=''))}")
        if tags:
            logger.debug("rTorrent non ha tag: ignorati %s", tags)
        content = local_torrent_bytes(torrent_file_or_url)
        if content is not None:
            # load.raw ignora in silenzio un duplicato: lo si riconosce dall'hash.
            own = compute_info_hash(content)
            if own in before:
                raise TorrentAlreadyInClientError(
                    f"Torrent {own} is already in the client (possibly with another save path): nothing added"
                )
            expected = expected or own
            self._call("load.raw", "", xmlrpc.client.Binary(content), *commands)
        else:
            self._call("load.normal", "", torrent_file_or_url, *commands)
        info_hash = wait_for_hash(self._hashes, before, expected, self.poll_interval, self.poll_timeout, "rTorrent")
        target = info_hash.upper()
        # Sempre, anche con skip_check_verified: rTorrent non sa saltarlo.
        self._call("d.check_hash", target)
        self._call("d.start", target)
        return info_hash

    def recheck(self, info_hash: str) -> None:
        self._call("d.check_hash", info_hash.upper())

    def remove_torrent(self, info_hash: str, delete_files: bool) -> None:
        target = info_hash.upper()
        if delete_files and self.via_rutorrent:
            # Dal proxy di ruTorrent execute.* è sempre rifiutato: i file li
            # cancella il suo plugin erasedata, solo quelli del torrent (v=1).
            response = self._client.post(
                self.url, content=f"mode=removewithdata&hash={target}&v=1".encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            if response.text.strip() in ("", "false"):
                raise RuntimeError(
                    f"ruTorrent could not remove {info_hash} with its data: is its erasedata plugin enabled? "
                    "ruTorrent sets it up the first time its web UI is opened"
                )
            return
        paths: list[str] = []
        base = ""
        if delete_files:
            paths = [row[0] for row in self._call("f.multicall", target, "", "f.frozen_path=") or [] if row[0]]
            if self._call("d.is_multi_file", target):
                base = (self._call("d.directory", target) or "").rstrip("/")
        self._call("d.erase", target)
        for path in paths:
            self._call("execute.throw", "", "rm", "-f", "--", path)
        if base:
            # Le cartelle del torrent rimaste vuote, dalla più profonda; una
            # cartella con altri file resta (rmdir fallisce, nothrow).
            dirs = {base}
            for path in paths:
                parent = os.path.dirname(path)
                while parent.startswith(base + "/"):
                    dirs.add(parent)
                    parent = os.path.dirname(parent)
            for path in sorted(dirs, key=lambda d: d.count("/"), reverse=True):
                self._call("execute.nothrow", "", "rmdir", "--", path)

    def list_categories(self) -> list[str]:
        labels = self._call("d.multicall2", "", "main", "d.custom1=") or []
        return sorted({unquote(row[0]) for row in labels if row and row[0]}, key=str.lower)

    def _rows(self, target: str | None = None) -> list[dict]:
        if target is None:
            raw = self._call("d.multicall2", "", "main", *FIELDS) or []
        else:
            # Un solo torrent: gli stessi campi in una sola richiesta.
            calls = [{"methodName": field.rstrip("="), "params": [target]} for field in FIELDS]
            results = self._call("system.multicall", calls) or []
            if any(isinstance(r, dict) for r in results):  # un fault per campo: hash sconosciuto
                return []
            raw = [[r[0] for r in results]]
        return [dict(zip(KEYS, values, strict=True)) for values in raw]

    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        rows = self._rows(info_hash.upper())
        if not rows:
            raise ValueError(f"Torrent {info_hash} non trovato nel client")
        row = rows[0]
        state = _state(row)
        size = int(row["size_bytes"] or 0)
        progress = 1.0 if row["complete"] else (int(row["completed_bytes"] or 0) / size if size else 0.0)
        if state == CHECKING:
            recheck_status = "pending"
        elif row["complete"]:
            recheck_status = "ok"
        else:
            recheck_status = "failed"
        return TorrentStatus(
            info_hash=row["hash"].lower(), state=state, recheck_status=recheck_status, progress=progress,
            incomplete=recheck_status == "failed", amount_left=int(row["left_bytes"] or 0),
        )

    def get_torrent_info(self, info_hash: str) -> ClientTorrentInfo | None:
        rows = self._rows(info_hash.upper())
        return self._info(rows[0]) if rows else None

    def list_torrents(self, on_progress: Callable[[int, int], None] | None = None) -> list[ClientTorrentInfo]:
        rows = self._rows()
        result = []
        for i, row in enumerate(rows):
            result.append(self._info(row))
            if on_progress is not None:
                on_progress(i + 1, len(rows))
        return result

    def _info(self, row: dict) -> ClientTorrentInfo:
        target = row["hash"]
        directory = (row["directory"] or "").rstrip("/")
        # d.directory di un torrent multi-file è la sua cartella (save path +
        # nome): la save path è la cartella che la contiene, e i percorsi dei
        # file partono dal nome di quella cartella, come in qBittorrent.
        if row["is_multi_file"]:
            save_path, root = os.path.dirname(directory), os.path.basename(directory)
        else:
            save_path, root = directory, ""
        files = [
            ClientTorrentFileInfo(path_in_torrent=f"{root}/{path}" if root else path, size_bytes=int(size or 0))
            for path, size in self._call("f.multicall", target, "", "f.path=", "f.size_bytes=") or []
        ]
        trackers = self._call("t.multicall", target, "", "t.url=") or []
        finished = int(row["finished"] or 0)
        return ClientTorrentInfo(
            info_hash=target.lower(),
            name=row["name"] or "",
            save_path=save_path or "/",
            state=_state(row),
            category=unquote(row["custom1"] or "") or None,
            tracker_url=next((t[0] for t in trackers if t and t[0] and t[0] != "dht://"), None),
            files=files,
            ratio=int(row["ratio"] or 0) / 1000.0,
            seeding_time_seconds=max(int(time.time()) - finished, 0) if row["complete"] and finished else None,
            added_on=int(row["load_date"] or 0) or None,
        )
