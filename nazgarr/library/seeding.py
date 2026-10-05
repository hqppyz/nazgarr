"""Quali file della libreria sono già "in seed", per il matching e per la
coda di review: in un torrent tracciato da un client, come nella Library
(nazgarr/library/states.py) — un hardlink nella cartella torrent che nessun client
segue (es. un file scaricato a mano e importato da Radarr) non conta.

Con la ricerca dei cross-seed (decisione dell'utente, 2026-10-02, accesa di
default) un file è in seed per un tracker solo se è in un torrent di QUEL
tracker: un file in seed su A si cerca anche su B."""

from sqlalchemy.orm import Session

from nazgarr.core import settings_registry
from nazgarr.core.models import ClientTorrent, ClientTorrentFile, Tracker
from nazgarr.library.hardlinks import media_links
from nazgarr.library.states import _tracking
from nazgarr.torrents.tracker_scope import torrent_host, tracker_torrent_ids

CROSS_SEED_SETTING = "cross_seed_search"


def cross_seed_enabled(session: Session) -> bool:
    return settings_registry.get_bool(session, CROSS_SEED_SETTING)


def seeding_media_file_ids(session: Session, tracker: Tracker | None = None) -> set[int]:
    """I media_file con un hardlink in un torrent tracciato: di questo
    tracker, se c'è e la ricerca dei cross-seed è accesa, di qualunque se no."""
    torrent_ids = tracker_torrent_ids(session, tracker) if tracker is not None and cross_seed_enabled(session) else None
    tracked, _active = _tracking(session, torrent_ids)
    return {mf_id for mf_id, seeds in media_links(session).items() if any(sf_id in tracked for sf_id, _ in seeds)}


def seeding_on(session: Session, media_file_id: int) -> list[str]:
    """Dove questo file è già in seed: il nome del tracker configurato, o
    l'host dell'announce se non lo è. Per la coda di review: un cross-seed si
    distingue da un reseed di un file che non seeda da nessuna parte."""
    seed_ids = {sf_id for sf_id, _ in media_links(session, [media_file_id]).get(media_file_id, [])}
    if not seed_ids:
        return []
    urls = {
        url for (url,) in session.query(ClientTorrent.tracker_url)
        .join(ClientTorrentFile, ClientTorrentFile.client_torrent_id == ClientTorrent.id)
        .filter(ClientTorrentFile.seed_file_id.in_(seed_ids))
        .all()
    }
    labels = {}
    for tracker in session.query(Tracker).order_by(Tracker.id):
        for url in (tracker.announce_url, tracker.base_url):
            if torrent_host(url):
                labels.setdefault(torrent_host(url), tracker.label)
    hosts = {torrent_host(url) for url in urls} - {None}
    return sorted({labels.get(host, host) for host in hosts})
