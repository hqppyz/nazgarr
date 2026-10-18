"""Finti e fabbriche comuni a più file di test."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from nazgarr.adapters.torrent_client.base import (
    ClientTorrentInfo,
    TorrentClientAdapter,
    TorrentStatus,
    expected_hash,
    local_torrent_bytes,
    require_recheck,
)
from nazgarr.core.models import MediaFile


class FakeAdapter(TorrentClientAdapter):
    """Un client torrent che elenca i torrent ricevuti e non fa altro: per
    indicizzazione, stati della libreria, cambiamenti, non importati."""

    def __init__(self, torrents):
        self._torrents = torrents

    def add_torrent(self, *args, **kwargs):
        raise NotImplementedError

    def get_torrent_status(self, *args, **kwargs):
        raise NotImplementedError

    def list_torrents(self):
        return self._torrents


@dataclass
class AddedTorrent:
    """Un add_torrent ricevuto da RecordingClient."""

    source: str  # il percorso del .torrent locale o l'URL, come passato
    content: bytes | None  # i byte del .torrent locale; None per un URL
    save_path: str
    options: dict = field(default_factory=dict)  # gli altri argomenti di add_torrent, tutti


class RecordingClient(TorrentClientAdapter):
    """Un client torrent che rispetta il contratto come gli adapter inclusi
    (nazgarr/adapters/torrent_client/base.py), per i test dell'esecuzione:
    la stessa firma di add_torrent (tests/test_fakes.py lo controlla), il
    recheck sempre chiesto (require_recheck: force_recheck=False è un
    errore), e come loro sa saltare il recheck solo con skip_check_verified
    e aggiungere un torrent fermo (can_skip_recheck, can_add_stopped). Prima
    ogni test aveva il suo finto, quasi mai figlio del contratto: senza
    content_layout, stopped o can_skip_recheck l'esecutore prendeva strade
    che un adapter vero non prende mai (audit 2026-10-18).

    Registra ogni chiamata che cambia qualcosa nel client (added, started,
    stopped, rechecked, removed). add_torrent restituisce info_hash se dato,
    se no quello atteso o dei byte del .torrent mandato (expected_hash, come
    gli adapter inclusi); add_error lo fa fallire dopo averlo registrato;
    expect_info_hash fa fallire il test se il chiamante non aspetta proprio
    quell'info hash. Un test che lo estende non ridefinisce add_torrent con
    *args: layout_kwargs e stopped_kwargs leggono la sua firma, e senza
    content_layout l'esecutore non lo manderebbe.
    status è la risposta di get_torrent_status (di default un recheck in
    corso), torrents quelli che il client conosce (get_torrent_info,
    list_torrents): un torrent aggiunto non vi entra da solo."""

    can_skip_recheck = True
    can_add_stopped = True

    def __init__(self, *, info_hash: str | None = None, status: TorrentStatus | None = None,
                 torrents: list[ClientTorrentInfo] = (), layout: str = "Original",
                 add_error: Exception | None = None, expect_info_hash: str | None = None):
        self.info_hash = info_hash
        self.expect_info_hash = expect_info_hash
        self.status = status
        self.torrents = {t.info_hash: t for t in torrents}
        self.layout = layout
        self.add_error = add_error
        self.added: list[AddedTorrent] = []
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.rechecked: list[str] = []
        self.removed: list[tuple[str, bool]] = []

    def add_torrent(
        self, torrent_file_or_url: str, save_path: str, force_recheck: bool = True,
        expected_info_hash: str | None = None, skip_check_verified: bool = False,
        category: str | None = None, tags: list[str] | None = None, content_layout: str = "Original",
        stopped: bool = False,
    ) -> str:
        require_recheck(force_recheck)
        if self.expect_info_hash is not None:
            assert (expected_info_hash or "").lower() == self.expect_info_hash.lower(), expected_info_hash
        content = local_torrent_bytes(torrent_file_or_url)
        self.added.append(AddedTorrent(torrent_file_or_url, content, save_path, {
            "force_recheck": force_recheck, "expected_info_hash": expected_info_hash,
            "skip_check_verified": skip_check_verified, "category": category, "tags": tags,
            "content_layout": content_layout, "stopped": stopped,
        }))
        if self.add_error is not None:
            raise self.add_error
        return self.info_hash or expected_hash(expected_info_hash, content) or "0" * 40

    def content_layout(self) -> str:
        return self.layout

    def get_torrent_status(self, info_hash: str) -> TorrentStatus:
        return self.status or TorrentStatus(info_hash, "checkingUP", "pending", 0.0)

    def get_torrent_info(self, info_hash: str) -> ClientTorrentInfo | None:
        return self.torrents.get(info_hash)

    def list_torrents(self, on_progress=None) -> list[ClientTorrentInfo]:
        return list(self.torrents.values())

    def start(self, info_hash: str) -> None:
        self.started.append(info_hash)

    def stop(self, info_hash: str) -> None:
        self.stopped.append(info_hash)

    def recheck(self, info_hash: str) -> None:
        self.rechecked.append(info_hash)

    def remove_torrent(self, info_hash: str, delete_files: bool) -> None:
        self.removed.append((info_hash, delete_files))
        self.torrents.pop(info_hash, None)


def make_media_file(session, disk, relative_path, run, **values) -> MediaFile:
    """Un media_file visto dalla scansione `run` (dimensione e inode finti,
    sovrascrivibili con values)."""
    mf = MediaFile(
        disk_id=disk.id, relative_path=relative_path, last_scan_id=run.id, last_seen_at=datetime.now(UTC),
        **{"size_bytes": 1, "st_dev": 1, "inode": 1, **values},
    )
    session.add(mf)
    session.commit()
    return mf
