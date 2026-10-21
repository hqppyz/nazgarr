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
    """Host di un URL senza porta e senza "www.": l'host dell'announce di un
    torrent confrontato con announce_url e base_url del tracker, che spesso
    non hanno la porta dell'announce. La stessa regola per la scheda di
    dettaglio e la pagina dei torrent (prima una copia in library/detail.py).
    I controlli di sicurezza del tracker tengono la porta (host_of_url in
    nazgarr/adapters/tracker/base.py): mai questa."""
    host = urlsplit(url).hostname if url else None
    return host.removeprefix("www.") if host else None


# Un id di tracker è un intero di SQLite: oltre queste cifre non è un id
# (int() rifiuta più di 4300 cifre, SQLite più di 2**63).
MAX_ID_DIGITS = 9


def normalize(scope: str | None) -> str:
    """Un filtro valido, o "all": un valore sconosciuto non restringe nulla.
    Un id ha una forma sola (audit 2026-10-18): '01' e '1' sono lo stesso
    tracker, quindi la stessa risposta in cache (nazgarr/web/response_cache.py),
    e una cifra non ASCII ('²', che str.isdigit accetta) vale "all", non un 500."""
    if scope in (None, "", ALL):
        return ALL
    if scope == CONFIGURED:
        return scope
    if scope.isascii() and scope.isdigit() and len(scope) <= MAX_ID_DIGITS:
        return str(int(scope))
    return ALL


def resolve(session: Session, scope: str | None) -> str:
    """Come normalize, e un tracker che non c'è (tolto, o un id a caso) vale
    "all" come ogni valore sconosciuto: prima ogni id inventato calcolava e
    teneva in memoria una vista intera, con ogni file orfano."""
    scope = normalize(scope)
    if scope not in (ALL, CONFIGURED) and session.get(Tracker, int(scope)) is None:
        return ALL
    return scope


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
