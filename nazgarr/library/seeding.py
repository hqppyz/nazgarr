"""Quali file della libreria sono già "in seed", per il matching e per la
coda di review: in un torrent tracciato da un client, come nella Library
(nazgarr/library/states.py) — un hardlink nella cartella torrent che nessun client
segue (es. un file scaricato a mano e importato da Radarr) non conta.

Con la ricerca dei cross-seed (decisione dell'utente, 2026-10-02, accesa di
default) un file è in seed per un tracker solo se è in un torrent di QUEL
tracker: un file in seed su A si cerca anche su B.

Pack e singoli (decisione dell'utente, 2026-10-08, spenta di default): un
episodio in seed su un tracker in un formato solo, nel pack della stagione o
da solo, si cerca su quel tracker anche nell'altro. Un torrent con più video è
un pack (stagione o serie), uno con un video solo, anche con extra, un singolo."""

from collections import defaultdict

from sqlalchemy.orm import Session

from nazgarr.core import settings_registry
from nazgarr.core.file_types import is_video
from nazgarr.core.models import ClientTorrent, ClientTorrentFile, MediaItem, Tracker
from nazgarr.library.hardlinks import media_links
from nazgarr.library.states import _tracking
from nazgarr.torrents.tracker_scope import torrent_host, tracker_torrent_ids

CROSS_SEED_SETTING = "cross_seed_search"
PACK_AND_SINGLES_SETTING = "reseed_pack_and_singles"

PACK = "pack"
SINGLE = "single"
FORMATS = frozenset({PACK, SINGLE})


def cross_seed_enabled(session: Session) -> bool:
    return settings_registry.get_bool(session, CROSS_SEED_SETTING)


def pack_and_singles_enabled(session: Session) -> bool:
    return settings_registry.get_bool(session, PACK_AND_SINGLES_SETTING)


def torrent_format(video_count: int) -> str:
    return PACK if video_count > 1 else SINGLE


def is_episode(item: MediaItem | None) -> bool:
    return item is not None and item.season_number is not None and item.episode_number is not None


def seeding_formats(
    session: Session, tracker: Tracker, media_file_ids: list[int] | None = None,
) -> dict[int, set[str]]:
    """media_file -> i formati in cui è in seed su questo tracker, nei torrent
    che un client segue (come seeding_media_file_ids). media_file_ids: solo
    questi file (la coda di review), None = tutti (il matching)."""
    links = media_links(session, media_file_ids)
    if not links:
        return {}
    torrent_ids = tracker_torrent_ids(session, tracker)
    videos: dict[int, int] = defaultdict(int)
    torrents_of: dict[int, set[int]] = defaultdict(set)
    rows = session.query(
        ClientTorrentFile.client_torrent_id, ClientTorrentFile.seed_file_id, ClientTorrentFile.path_in_torrent)
    for torrent_id, seed_file_id, path in rows:
        if torrent_id not in torrent_ids:
            continue
        if is_video(path):
            videos[torrent_id] += 1
        if seed_file_id is not None:
            torrents_of[seed_file_id].add(torrent_id)
    formats = {}
    for media_file_id, seeds in links.items():
        found = {torrent_format(videos[t]) for sf_id, _ in seeds for t in torrents_of.get(sf_id, ())}
        if found:
            formats[media_file_id] = found
    return formats


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
