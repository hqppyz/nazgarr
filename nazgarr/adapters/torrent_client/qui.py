"""Adapter qui (gestore multi-istanza per qBittorrent, getqui.com) —
docs/SPEC.md sezione 15.

Verificato contro lo swagger/OpenAPI reale del progetto (github.com/autobrr/qui,
internal/web/swagger/openapi.yaml), non solo dedotto — smentisce l'assunzione
pragmatica originale (vedi ancora qbittorrent.py in questo pacchetto):
- Auth: header `X-API-Key`, MAI username/password — un'unica chiave copre
  tutte le istanze qBittorrent gestite da un deployment qui.
- Un deployment qui espone più istanze dietro `GET /api/instances`; ogni
  altra chiamata vive sotto `/api/instances/{instanceID}/...` — qui NON è
  la WebUI API nativa di qBittorrent pointed elsewhere, ha una propria API
  di aggregazione con nomi di campo/percorsi diversi (es. `savepath` in
  ingresso). In uscita la lista torrent usa invece i nomi di qBittorrent
  (`save_path`, `amount_left`): lo swagger dice `savePath`, l'istanza vera
  (e Auditorr, che ci gira sopra) no — si leggono entrambi.
- `POST /api/instances/{id}/torrents` (multipart: `torrent` binario oppure
  `urls`) risponde 201 senza corpo — nessun info_hash restituito, stesso
  problema già risolto in qbittorrent.py con un diff prima/dopo sulla lista.
  L'endpoint dichiara SOLO multipart/form-data (mai form url-encoded): anche
  i campi testuali (`savepath`, `skip_checking`) vanno quindi passati come
  parti multipart con filename=None, non in un `data=` separato — altrimenti
  httpx non usa multipart quando non c'è nessun file reale da allegare
  (caso "urls"), violando il content-type che il server si aspetta.
- Nessun endpoint per leggere UN SOLO torrent per hash (confermato anche dal
  codice equivalente di Auditorr, sources/_qui.py, che scansiona sempre la
  lista paginata) — get_torrent_status() fa quindi una scansione paginata
  completa ad ogni chiamata, non solo per il nuovo hash dopo un add.
- Il recheck forzato passa da `POST /torrents/bulk-action` con
  `action: "recheck"` (SPEC.md sezione 8, mai skip_checking=True).

Un deployment qui gestisce più istanze qBittorrent dietro un solo host+api
token: un TorrentClient di nazgarr punta sempre a UNA istanza specifica
(TorrentClient.qui_instance_id) — add_torrent deve sapere esattamente dove
scrivere, non può sceglierla a runtime.
"""

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from nazgarr.adapters.torrent_client.base import (
    CHECKING_STATES,
    ERROR_STATES,
    ClientTorrentFileInfo,
    ClientTorrentInfo,
    TorrentAddTimeoutError,
    TorrentAlreadyInClientError,
    TorrentClientAdapter,
    TorrentStatus,
)

logger = logging.getLogger(__name__)

# Richieste di dettaglio in parallelo durante l'indicizzazione (rete locale).
DETAIL_WORKERS = 8


def _number(value, kind):
    try:
        return kind(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class QuiTorrentClientAdapter(TorrentClientAdapter):
    def __init__(
        self,
        base_url: str,
        api_token: str,
        instance_id: int,
        http_client=None,
        poll_interval: float = 0.5,
        poll_timeout: float = 60.0,
        page_limit: int = 2000,
    ):
        self.base_url = base_url.rstrip("/")
        self.instance_id = instance_id
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.page_limit = page_limit
        if http_client is not None:
            self._client = http_client
        else:
            import httpx

            self._client = httpx.Client(
                base_url=self.base_url, headers={"X-API-Key": api_token}, timeout=30.0
            )

    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
        category: str | None = None, tags: list[str] | None = None,
    ) -> str:
        if not force_recheck:
            raise ValueError(
                "force_recheck=False non è permesso: il recheck reale è "
                "un requisito funzionale, vedi docs/SPEC.md sezione 8."
            )

        before_hashes = {t["hash"] for t in self._fetch_all_torrents() if t.get("hash")}
        expected = expected_info_hash.lower() if expected_info_hash else None
        if expected and expected in {h.lower() for h in before_hashes}:
            raise TorrentAlreadyInClientError(
                f"Torrent {expected} is already in the client (possibly with another save path): nothing added"
            )

        # L'endpoint dichiara multipart/form-data come unico content-type
        # accettato (nessun application/json né form url-encoded) — anche i
        # campi testuali passano quindi per `files=`, con filename=None,
        # lo stesso trucco httpx/requests per forzare multipart pure quando
        # non c'è alcun file reale da allegare (caso "urls").
        files: dict = {
            "savepath": (None, save_path),
            "skip_checking": (None, "true" if skip_check_verified else "false"),
        }
        if category:
            files["category"] = (None, category)
        if tags:
            files["tags"] = (None, ",".join(tags))
        if os.path.isfile(torrent_file_or_url):
            with open(torrent_file_or_url, "rb") as f:
                torrent_bytes = f.read()
            files["torrent"] = ("torrent.torrent", torrent_bytes, "application/x-bittorrent")
        else:
            files["urls"] = (None, torrent_file_or_url)

        response = self._client.post(f"/api/instances/{self.instance_id}/torrents", files=files)
        response.raise_for_status()

        info_hash = self._wait_for_new_hash(before_hashes, expected)
        if not skip_check_verified:
            self._bulk_action([info_hash], "recheck")
        return info_hash

    def _wait_for_new_hash(self, before_hashes: set[str], expected: str | None = None) -> str:
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            current_hashes = {t["hash"] for t in self._fetch_all_torrents() if t.get("hash")}
            if expected is not None:
                found = next((h for h in current_hashes if h.lower() == expected), None)
                if found is not None:
                    return found
                time.sleep(self.poll_interval)
                continue
            new_hashes = current_hashes - before_hashes
            if new_hashes:
                return next(iter(new_hashes))
            time.sleep(self.poll_interval)
        raise TorrentAddTimeoutError(
            f"Nessun nuovo torrent rilevato sull'istanza qui {self.instance_id} "
            f"entro {self.poll_timeout}s dall'aggiunta"
        )

    def _bulk_action(self, hashes: list[str], action: str) -> None:
        response = self._client.post(
            f"/api/instances/{self.instance_id}/torrents/bulk-action",
            json={"hashes": hashes, "action": action},
        )
        response.raise_for_status()

    def list_categories(self) -> list[str]:
        # Come qBittorrent (/torrents/categories): un oggetto nome -> dettagli.
        response = self._client.get(f"/api/instances/{self.instance_id}/categories")
        response.raise_for_status()
        body = response.json()
        names = body.keys() if isinstance(body, dict) else [c.get("name") for c in body if isinstance(c, dict)]
        return sorted((name for name in names if name), key=str.lower)

    def recheck(self, info_hash: str) -> None:
        self._bulk_action([info_hash], "recheck")

    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        torrent = next((t for t in self._fetch_all_torrents() if t.get("hash") == info_hash), None)
        if torrent is None:
            raise ValueError(f"Torrent {info_hash} non trovato sull'istanza qui {self.instance_id}")

        state = torrent.get("state") or ""
        progress = float(torrent.get("progress") or 0.0)
        if state in CHECKING_STATES:
            recheck_status = "pending"
        elif state in ERROR_STATES:
            recheck_status = "failed"
        elif progress >= 1.0:
            recheck_status = "ok"
        else:
            recheck_status = "failed"

        amount_left = torrent.get("amount_left")
        return TorrentStatus(
            info_hash=torrent["hash"], state=state, recheck_status=recheck_status, progress=progress,
            incomplete=state not in ERROR_STATES and state not in CHECKING_STATES and progress < 1.0,
            amount_left=int(amount_left) if amount_left is not None else None,
        )

    def get_torrent_info(self, info_hash: str) -> ClientTorrentInfo | None:
        # Nessun endpoint per un solo torrent (vedi get_torrent_status): lista
        # completa, poi file e tracker del solo torrent cercato.
        torrent = next((t for t in self._fetch_all_torrents() if (t.get("hash") or "").lower() == info_hash.lower()),
                       None)
        return self._torrent_info(torrent) if torrent is not None else None

    def list_torrents(self, on_progress: Callable[[int, int], None] | None = None) -> list[ClientTorrentInfo]:
        logger.debug("qui[%s]: list_torrents() — recupero la lista paginata...", self.instance_id)
        torrents = self._fetch_all_torrents()
        logger.debug(
            "qui[%s]: %d torrent nella lista, ora recupero file/tracker per ciascuno",
            self.instance_id, len(torrents),
        )
        # File e tracker di ogni torrent: due GET indipendenti per torrent,
        # fatte DETAIL_WORKERS alla volta invece che una dopo l'altra (migliaia
        # di richieste in rete locale). httpx.Client è thread-safe; ordine del
        # risultato e callback di avanzamento restano nel thread chiamante.
        with_hash = [t for t in torrents if t.get("hash")]
        result: list[ClientTorrentInfo | None] = [None] * len(with_hash)
        pool = ThreadPoolExecutor(max_workers=DETAIL_WORKERS)
        try:
            futures = {pool.submit(self._torrent_info, t): i for i, t in enumerate(with_hash)}
            for done, future in enumerate(as_completed(futures), start=1):
                result[futures[future]] = future.result()
                if on_progress is not None:
                    on_progress(done, len(with_hash))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)  # stop o errore: niente richieste rimaste in coda
        logger.debug("qui[%s]: list_torrents() completato — %d torrent risolti", self.instance_id, len(result))
        return [r for r in result if r is not None]

    def _torrent_info(self, torrent: dict) -> ClientTorrentInfo:
        info_hash = torrent["hash"]
        files_resp = self._client.get(f"/api/instances/{self.instance_id}/torrents/{info_hash}/files")
        files_resp.raise_for_status()
        files = [
            ClientTorrentFileInfo(path_in_torrent=f.get("name", ""), size_bytes=f.get("size") or 0)
            for f in files_resp.json()
        ]
        return ClientTorrentInfo(
            info_hash=info_hash,
            name=torrent.get("name", ""),
            # La lista torrent di qui usa i nomi di campo di qBittorrent
            # (save_path), verificato sull'istanza reale e come fa Auditorr:
            # con il solo "savePath" il path restava vuoto per ogni torrent.
            save_path=(torrent.get("save_path") or torrent.get("savePath") or "").rstrip("/"),
            state=torrent.get("state") or "",
            category=torrent.get("category") or None,
            tracker_url=self._first_tracker_url(info_hash),
            files=files,
            ratio=_number(torrent.get("ratio"), float),
            seeding_time_seconds=_number(torrent.get("seeding_time"), int),
            added_on=_number(torrent.get("added_on"), int),
        )

    def _first_tracker_url(self, info_hash: str) -> str | None:
        response = self._client.get(f"/api/instances/{self.instance_id}/torrents/{info_hash}/trackers")
        response.raise_for_status()
        for entry in response.json():
            url = entry.get("url") or ""
            if url.startswith("http") or url.startswith("udp"):
                return url
        return None

    def _fetch_all_torrents(self) -> list[dict]:
        """Scarica tutta la lista paginata (0-indexed, max 2000/pagina) —
        deduplicata per hash per restare robusta a un'API che ignorasse
        l'offset e ripetesse la stessa pagina, stesso approccio verificato
        nell'adapter equivalente di Auditorr."""
        all_torrents: list[dict] = []
        seen_hashes: set[str] = set()
        page = 0
        while True:
            logger.debug("qui[%s]: GET .../torrents?page=%d&limit=%d", self.instance_id, page, self.page_limit)
            response = self._client.get(
                f"/api/instances/{self.instance_id}/torrents",
                params={"page": page, "limit": self.page_limit},
            )
            response.raise_for_status()
            batch = response.json().get("torrents") or []
            logger.debug("qui[%s]: pagina %d — %d torrent ricevuti", self.instance_id, page, len(batch))
            if not batch:
                break
            new_items = [t for t in batch if t.get("hash") and t["hash"] not in seen_hashes]
            seen_hashes.update(t["hash"] for t in new_items)
            all_torrents.extend(new_items)
            if len(batch) < self.page_limit or not new_items:
                break
            page += 1
        return all_torrents
