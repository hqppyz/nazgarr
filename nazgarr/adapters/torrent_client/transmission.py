"""Adapter Transmission, sulla sua RPC JSON (docs/SPEC.md sezione 5).

Perché httpx e non transmission-rpc: l'RPC di Transmission è un solo POST
JSON (`{"method", "arguments"}`) più l'handshake dell'header
X-Transmission-Session-Id (un 409 che lo porta, si ripete la richiesta).
Una ventina di righe con httpx, già nelle dipendenze: nessuna libreria in più
da tenere aggiornata e bloccata con gli hash.

base_url: l'indirizzo della Web UI (http://transmission:9091); l'RPC è
`/transmission/rpc`, salvo che base_url finisca già in `/rpc` (un
rpc-url personalizzato). Utente e password: l'autenticazione HTTP Basic
della RPC, se attiva.

Verificato contro un'istanza reale (lscr.io/linuxserver/transmission,
Transmission 4.1.3, RPC 19): tests/integration/test_real_clients.py.

- Un .torrent locale va col suo contenuto (`metainfo`, base64), mai col
  percorso: il client non vede la cartella dati di Nazgarr. Un URL
  (http/https/magnet) resta `filename`, lo scarica Transmission.
- `torrent-add` restituisce l'hash (`torrent-added`) o segnala un duplicato
  (`torrent-duplicate`, che diventa TorrentAlreadyInClientError). L'hash si
  conferma comunque sulla lista, atteso o per differenza, come negli altri
  adapter.
- Recheck: `torrent-verify` subito dopo l'aggiunta. Transmission non ha un
  modo per aggiungere un torrent già completo senza verificarlo
  (can_skip_recheck = False): skip_check_verified non salta niente, il
  recheck c'è sempre.
- Etichette: Transmission non ha categorie, solo `labels` (RPC 16+,
  Transmission 3.0). I tag diventano labels; una categoria passata comunque
  diventa la prima label. list_categories() è vuota e la categoria letta è
  sempre None.
- Stato nativo: il nome dello `status` numerico ("stopped", "checking",
  "seeding"...), "error" se `error` è 3 (errore locale, es. file mancanti:
  gli errori 1 e 2 sono del tracker e non dicono niente sui dati).
"""

import base64
import logging
from collections.abc import Callable
from urllib.parse import urlsplit

from nazgarr.adapters.torrent_client.base import (
    ClientTorrentFileInfo,
    ClientTorrentInfo,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    TorrentStatus,
    local_torrent_bytes,
    require_recheck,
    seeders,
    wait_for_hash,
)

logger = logging.getLogger(__name__)

SESSION_HEADER = "X-Transmission-Session-Id"
STATUS_NAMES = {
    0: "stopped", 1: "check_pending", 2: "checking", 3: "download_pending",
    4: "downloading", 5: "seed_pending", 6: "seeding",
}
CHECKING = {"check_pending", "checking"}
LOCAL_ERROR = 3  # tr_stat_errtype TR_STAT_LOCAL_ERROR
STATUS_FIELDS = ["hashString", "status", "error", "percentDone", "leftUntilDone"]
INFO_FIELDS = [
    "hashString", "name", "downloadDir", "status", "error", "labels", "trackers", "files",
    "uploadRatio", "secondsSeeding", "addedDate", "trackerStats",
]


class TransmissionError(Exception):
    pass


def _rpc_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if urlsplit(base).path.endswith("/rpc") else f"{base}/transmission/rpc"


def _state(torrent: dict) -> str:
    if torrent.get("error") == LOCAL_ERROR:
        return "error"
    return STATUS_NAMES.get(torrent.get("status"), str(torrent.get("status")))


class TransmissionAdapter(TorrentClientAdapter):
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
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._session_id: str | None = None
        if http_client is not None:
            self._client = http_client
        else:
            import httpx

            auth = (username, password or "") if username else None
            self._client = httpx.Client(auth=auth, timeout=30.0)

    def _rpc(self, method: str, arguments: dict | None = None) -> dict:
        body = {"method": method, "arguments": arguments or {}}
        for _ in range(2):
            headers = {SESSION_HEADER: self._session_id} if self._session_id else {}
            response = self._client.post(self.url, json=body, headers=headers)
            if response.status_code == 409 and SESSION_HEADER in response.headers:
                self._session_id = response.headers[SESSION_HEADER]
                continue
            response.raise_for_status()
            data = response.json()
            if data.get("result") != "success":
                raise TransmissionError(f"Transmission {method}: {data.get('result')}")
            return data.get("arguments") or {}
        raise TransmissionError("Transmission: session id handshake failed")

    def _torrents(self, fields: list[str], ids: list[str] | None = None) -> list[dict]:
        arguments: dict = {"fields": fields}
        if ids is not None:
            arguments["ids"] = ids
        return self._rpc("torrent-get", arguments).get("torrents") or []

    def _hashes(self) -> set[str]:
        return {t["hashString"] for t in self._torrents(["hashString"]) if t.get("hashString")}

    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
        category: str | None = None, tags: list[str] | None = None,
    ) -> str:
        require_recheck(force_recheck)
        before = self._hashes()
        expected = expected_info_hash.lower() if expected_info_hash else None
        if expected and expected in {h.lower() for h in before}:
            raise TorrentAlreadyInClientError(
                f"Torrent {expected} is already in the client (possibly with another save path): nothing added"
            )
        arguments: dict = {"download-dir": save_path, "paused": False}
        content = local_torrent_bytes(torrent_file_or_url)
        if content is not None:
            arguments["metainfo"] = base64.b64encode(content).decode("ascii")
        else:
            arguments["filename"] = torrent_file_or_url
        result = self._rpc("torrent-add", arguments)
        if "torrent-duplicate" in result:
            duplicate = result["torrent-duplicate"].get("hashString", "")
            raise TorrentAlreadyInClientError(
                f"Torrent {duplicate} is already in the client (possibly with another save path): nothing added"
            )
        added = (result.get("torrent-added") or {}).get("hashString")
        info_hash = wait_for_hash(
            self._hashes, before, expected or (added.lower() if added else None),
            self.poll_interval, self.poll_timeout, "Transmission",
        )
        labels = [label for label in [category, *(tags or [])] if label]
        if labels:
            self._rpc("torrent-set", {"ids": [info_hash], "labels": list(dict.fromkeys(labels))})
        # Sempre, anche con skip_check_verified: Transmission non sa saltarlo.
        self._rpc("torrent-verify", {"ids": [info_hash]})
        return info_hash

    def recheck(self, info_hash: str) -> None:
        self._rpc("torrent-verify", {"ids": [info_hash.lower()]})

    def remove_torrent(self, info_hash: str, delete_files: bool) -> None:
        self._rpc("torrent-remove", {"ids": [info_hash.lower()], "delete-local-data": delete_files})

    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        found = self._torrents(STATUS_FIELDS, [info_hash.lower()])
        if not found:
            raise ValueError(f"Torrent {info_hash} non trovato nel client")
        torrent = found[0]
        state = _state(torrent)
        progress = float(torrent.get("percentDone") or 0.0)
        if state in CHECKING:
            recheck_status = "pending"
        elif state == "error":
            recheck_status = "failed"
        elif progress >= 1.0:
            recheck_status = "ok"
        else:
            recheck_status = "failed"
        left = torrent.get("leftUntilDone")
        return TorrentStatus(
            info_hash=torrent["hashString"], state=state, recheck_status=recheck_status, progress=progress,
            incomplete=state not in CHECKING and state != "error" and progress < 1.0,
            amount_left=int(left) if left is not None else None,
        )

    def get_torrent_info(self, info_hash: str) -> ClientTorrentInfo | None:
        found = self._torrents(INFO_FIELDS, [info_hash.lower()])
        return self._info(found[0]) if found else None

    def list_torrents(self, on_progress: Callable[[int, int], None] | None = None) -> list[ClientTorrentInfo]:
        torrents = self._torrents(INFO_FIELDS)
        result = []
        for i, torrent in enumerate(torrents):
            result.append(self._info(torrent))
            if on_progress is not None:
                on_progress(i + 1, len(torrents))
        return result

    @staticmethod
    def _info(torrent: dict) -> ClientTorrentInfo:
        trackers = torrent.get("trackers") or []
        ratio = torrent.get("uploadRatio")
        return ClientTorrentInfo(
            info_hash=torrent["hashString"],
            name=torrent.get("name") or "",
            save_path=(torrent.get("downloadDir") or "").rstrip("/") or "/",
            state=_state(torrent),
            category=None,  # Transmission non ha categorie, solo labels
            tracker_url=next((t.get("announce") for t in trackers if t.get("announce")), None),
            files=[
                ClientTorrentFileInfo(path_in_torrent=f.get("name", ""), size_bytes=int(f.get("length") or 0))
                for f in torrent.get("files") or []
            ],
            # -1 / -2: nessun rapporto (niente scaricato) / infinito.
            ratio=float(ratio) if isinstance(ratio, (int, float)) and ratio >= 0 else None,
            seeding_time_seconds=torrent.get("secondsSeeding"),
            added_on=torrent.get("addedDate") or None,
            # Il più alto fra i tracker (-1: quel tracker non l'ha detto).
            swarm_seeders=seeders(max((t.get("seederCount", -1) for t in torrent.get("trackerStats") or []),
                                      default=None)),
        )
