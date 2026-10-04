"""Filtro per tracker delle viste della libreria e della dashboard.

Un filtro è "all" (tutti i torrent, com'è sempre stato), "configured" (solo
i torrent dei tracker configurati e abilitati: un tracker pubblico non
conta) o l'id di un tracker. Il tracker di un torrent si riconosce
dall'host del suo announce (client_torrent.tracker_url), confrontato con
announce_url e base_url dei tracker configurati.

Con un filtro, i torrent dei client disattivati non contano (decisione
dell'utente, 2026-09-30): un file in seed solo lì è, per quel filtro, come
se non fosse in seed. Con "all" nulla cambia rispetto a prima.
"""

from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from nazgarr.core.models import ClientTorrent, TorrentClient, Tracker

ALL = "all"
CONFIGURED = "configured"


def torrent_host(url: str | None) -> str | None:
    """Host di un URL senza porta e senza "www.", come in nazgarr/library/detail.py."""
    host = urlsplit(url).hostname if url else None
    return host.removeprefix("www.") if host else None


def normalize(scope: str | None) -> str:
    """Un filtro valido, o "all": un valore sconosciuto non restringe nulla."""
    if scope in (None, "", ALL):
        return ALL
    if scope == CONFIGURED or scope.isdigit():
        return scope
    return ALL


def _trackers(session: Session, scope: str) -> list[Tracker]:
    if scope == CONFIGURED:
        return session.query(Tracker).filter(Tracker.enabled.is_(True)).all()
    tracker = session.get(Tracker, int(scope))
    return [tracker] if tracker is not None else []


def scoped_torrent_ids(session: Session, scope: str | None) -> set[int] | None:
    """I client_torrent che rientrano nel filtro; None = nessun filtro."""
    scope = normalize(scope)
    if scope == ALL:
        return None
    hosts = {torrent_host(url) for t in _trackers(session, scope) for url in (t.announce_url, t.base_url)} - {None}
    rows = (
        session.query(ClientTorrent.id, ClientTorrent.tracker_url)
        .join(TorrentClient, TorrentClient.id == ClientTorrent.torrent_client_id)
        .filter(TorrentClient.enabled.is_(True))
        .all()
    )
    return {torrent_id for torrent_id, url in rows if torrent_host(url) in hosts}


def tracker_torrent_ids(session: Session, tracker: Tracker) -> set[int]:
    """I client_torrent di questo tracker su tutti i client, anche quelli
    disattivati: per il matching un torrent fermo in un client spento è
    comunque un seed che esiste (nazgarr/library/seeding.py)."""
    hosts = {torrent_host(url) for url in (tracker.announce_url, tracker.base_url)} - {None}
    rows = session.query(ClientTorrent.id, ClientTorrent.tracker_url).all()
    return {torrent_id for torrent_id, url in rows if torrent_host(url) in hosts}


def enabled_torrent_ids(session: Session) -> set[int]:
    """I torrent dei client abilitati: con un filtro, gli unici che esistono."""
    rows = (
        session.query(ClientTorrent.id)
        .join(TorrentClient, TorrentClient.id == ClientTorrent.torrent_client_id)
        .filter(TorrentClient.enabled.is_(True))
        .all()
    )
    return {torrent_id for (torrent_id,) in rows}


def snapshot_scopes(session: Session) -> list[str]:
    """I filtri di cui salvare lo storico a ogni scansione: ogni tracker
    abilitato e "configured"."""
    ids = [str(t.id) for t in session.query(Tracker).filter(Tracker.enabled.is_(True)).order_by(Tracker.id)]
    return [CONFIGURED, *ids] if ids else []
