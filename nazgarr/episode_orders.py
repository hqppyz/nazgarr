"""Ordinamenti degli episodi di una serie (decisioni dell'utente, 2026-10-04):
le stagioni di default di TMDB, i suoi gruppi di episodi (digitale, DVD,
assoluto...), l'ordine "aired" di TVDB letto da Sonarr e, come ultima
risorsa, gli ordini di TVDB dalla sua API. Lo stesso episodio può avere
numeri diversi in ognuno; i file seguono quello che ha scelto chi li ha
pubblicati.

Ogni ordinamento ha la stessa forma: stagioni di episodi, e ogni episodio
rimanda a uno o più episodi di riferimento, quelli delle stagioni di default
di TMDB. Molti a molti: un episodio "doppio" (due episodi trasmessi insieme,
con due titoli) rimanda a due episodi di riferimento, e il contrario. Così
si traduce da un ordinamento all'altro passando dai riferimenti.

Usato al primo punto di approvazione dell'upload: quale ordinamento propone
Nazgarr (quello preferito per la serie, poi TVDB aired, poi TMDB), quale
combacia meglio con i file (con un avviso se non è lo stesso, mai una scelta
al posto dell'utente) e gli episodi trovati, tradotti in ognuno."""

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field

import httpx
from sqlalchemy.orm import Session

from nazgarr import net_guard, settings_repo

logger = logging.getLogger(__name__)

Ref = tuple[int, int]  # (stagione, episodio) nelle stagioni di default di TMDB

TMDB_DEFAULT = "tmdb:default"
TVDB_AIRED_KEYS = ("sonarr:aired", "tvdb:official", "tvdb:default")
# I tipi di gruppo di episodi di TMDB (https://developer.themoviedb.org).
TMDB_GROUP_TYPES = {
    1: "Original air date", 2: "Absolute", 3: "DVD", 4: "Digital", 5: "Story arc", 6: "Production", 7: "TV",
}
CACHE_SECONDS = 3600
# Combacia "meglio" solo con un margine: piccole differenze non fanno avvisi.
WARNING_MARGIN = 0.05


@dataclass
class OrderEpisode:
    number: int
    titles: list[str] = field(default_factory=list)
    air_date: str | None = None
    refs: list[Ref] = field(default_factory=list)


@dataclass
class EpisodeOrder:
    key: str
    label: str
    source: str  # tmdb | sonarr | tvdb
    seasons: dict[int, list[OrderEpisode]] = field(default_factory=dict)

    def episodes(self) -> dict[Ref, OrderEpisode]:
        return {(season, ep.number): ep for season, eps in self.seasons.items() for ep in eps}

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "source": self.source,
            "seasons": [
                {"season_number": s, "episodes": [{**asdict(e), "refs": [list(r) for r in e.refs]} for e in eps]}
                for s, eps in sorted(self.seasons.items())
            ],
        }

    @staticmethod
    def from_dict(data: dict) -> "EpisodeOrder":
        return EpisodeOrder(
            key=data["key"], label=data["label"], source=data["source"],
            seasons={
                s["season_number"]: [
                    OrderEpisode(number=e["number"], titles=list(e.get("titles") or []), air_date=e.get("air_date"),
                                 refs=[tuple(r) for r in e.get("refs") or []])
                    for e in s["episodes"]
                ]
                for s in data["seasons"]
            },
        )


# --- Traduzione ----------------------------------------------------------------


def translate(source: EpisodeOrder, target: EpisodeOrder, season: int, episode: int) -> list[Ref]:
    """(stagione, episodio) in `source` -> gli episodi di `target` con gli
    stessi riferimenti, in ordine. Vuoto se non si sa."""
    if source.key == target.key:
        return [(season, episode)]
    ep = source.episodes().get((season, episode))
    if ep is None or not ep.refs:
        return []
    wanted = set(ep.refs)
    return [ref for ref, other in sorted(target.episodes().items()) if wanted & set(other.refs)]


def align(episodes: list[tuple[int, OrderEpisode]], reference: list[tuple[int, OrderEpisode]]) -> None:
    """Riferimenti per un ordinamento che non ha gli id TMDB degli episodi
    (Sonarr, TVDB): stesso numero di episodi -> uno a uno; uno il doppio
    dell'altro -> a coppie (gli episodi accorpati); altrimenti per data di
    uscita. Le liste sono in ordine di uscita, gli speciali a parte."""
    for _season, ep in episodes:
        ep.refs = []
    if not episodes or not reference:
        return
    refs = [(season, ep.number) for season, ep in reference]
    n, m = len(episodes), len(refs)
    if n == m:
        for (_s, ep), ref in zip(episodes, refs, strict=True):
            ep.refs = [ref]
        return
    if m == 2 * n:
        for i, (_s, ep) in enumerate(episodes):
            ep.refs = refs[2 * i:2 * i + 2]
        return
    if n == 2 * m:
        for i, (_s, ep) in enumerate(episodes):
            ep.refs = [refs[i // 2]]
        return
    by_date: dict[str, list[Ref]] = defaultdict(list)
    for (season, ep), ref in zip(reference, refs, strict=True):
        if ep.air_date:
            by_date[ep.air_date].append(ref)
    mine: dict[str, list[OrderEpisode]] = defaultdict(list)
    for _s, ep in episodes:
        if ep.air_date:
            mine[ep.air_date].append(ep)
    for date, eps in mine.items():
        theirs = by_date.get(date) or []
        if not theirs:
            continue
        for i, ep in enumerate(eps):
            # Ripartiti in proporzione: due episodi lo stesso giorno contro
            # uno solo dall'altra parte vanno tutti e due su quello.
            start = i * len(theirs) // len(eps)
            end = max(start + 1, (i + 1) * len(theirs) // len(eps))
            ep.refs = theirs[start:end]


def _in_airing_order(order: EpisodeOrder, specials: bool) -> list[tuple[int, OrderEpisode]]:
    return [
        (season, ep)
        for season, eps in sorted(order.seasons.items()) if (season == 0) == specials
        for ep in sorted(eps, key=lambda e: e.number)
    ]


def align_to(order: EpisodeOrder, reference: EpisodeOrder) -> None:
    align(_in_airing_order(order, False), _in_airing_order(reference, False))
    align(_in_airing_order(order, True), _in_airing_order(reference, True))


# --- Fonti -------------------------------------------------------------------------

_cache: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, fetch):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fetch()
    _cache[key] = (time.monotonic(), value)
    return value


def tmdb_orders(client, tmdb_id: int) -> list[EpisodeOrder]:
    """Le stagioni di default (con gli episodi: una chiamata ogni 20
    stagioni) e i gruppi di episodi, che portano i numeri di default."""
    def fetch() -> list[EpisodeOrder]:
        show = client.get(f"/tv/{tmdb_id}")
        numbers = [s["season_number"] for s in show.get("seasons") or []]
        default = EpisodeOrder(TMDB_DEFAULT, "TMDB", "tmdb")
        for start in range(0, len(numbers), 20):
            chunk = numbers[start:start + 20]
            body = client.get(f"/tv/{tmdb_id}", append_to_response=",".join(f"season/{n}" for n in chunk))
            for n in chunk:
                season = body.get(f"season/{n}") or {}
                default.seasons[n] = [
                    OrderEpisode(number=e["episode_number"], titles=[e.get("name") or ""],
                                 air_date=e.get("air_date"), refs=[(n, e["episode_number"])])
                    for e in season.get("episodes") or []
                ]
        orders = [default]
        for group in client.get(f"/tv/{tmdb_id}/episode_groups").get("results") or []:
            if not group.get("episode_count"):
                continue
            detail = client.get(f"/tv/episode_group/{group['id']}")
            order = EpisodeOrder(
                f"tmdb:group:{group['id']}",
                f"TMDB · {group.get('name') or TMDB_GROUP_TYPES.get(group.get('type'), 'Group')}", "tmdb",
            )
            for index, part in enumerate(sorted(detail.get("groups") or [], key=lambda g: g.get("order", 0))):
                season = part.get("order", index)
                order.seasons[season] = [
                    OrderEpisode(number=pos + 1, titles=[e.get("name") or ""], air_date=e.get("air_date"),
                                 refs=[(e["season_number"], e["episode_number"])])
                    for pos, e in enumerate(sorted(part.get("episodes") or [], key=lambda e: e.get("order", 0)))
                ]
            if order.seasons:
                orders.append(order)
        return orders

    return _cached(("tmdb", tmdb_id), fetch)


class TmdbApi:
    """GET verso TMDB con la chiave delle impostazioni."""

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self._client = client or httpx.Client(base_url="https://api.themoviedb.org/3", timeout=15.0)

    def get(self, path: str, **params) -> dict:
        response = self._client.get(path, params={"api_key": self.api_key, **params})
        response.raise_for_status()
        return response.json()


def sonarr_order(session: Session, tmdb_id: int, tvdb_id: int | None, api_factory=None) -> EpisodeOrder | None:
    """L'ordine "aired" di TVDB come lo usa Sonarr, se la serie è lì."""
    from nazgarr.arr import ArrApi
    from nazgarr.models import SonarrInstance

    factory = api_factory or ArrApi
    for instance in session.query(SonarrInstance).filter_by(enabled=True).order_by(SonarrInstance.priority):
        try:
            api = factory(instance)
            series = next(
                (s for s in api.get("/api/v3/series") or []
                 if s.get("tmdbId") == tmdb_id or (tvdb_id and s.get("tvdbId") == tvdb_id)),
                None,
            )
            if series is None:
                continue
            order = EpisodeOrder("sonarr:aired", f"TVDB · Aired ({instance.label})", "sonarr")
            for e in api.get("/api/v3/episode", seriesId=series["id"]) or []:
                if e.get("seasonNumber") is None or e.get("episodeNumber") is None:
                    continue
                order.seasons.setdefault(e["seasonNumber"], []).append(
                    OrderEpisode(number=e["episodeNumber"], titles=[e.get("title") or ""], air_date=e.get("airDate")))
            for eps in order.seasons.values():
                eps.sort(key=lambda ep: ep.number)
            return order
        except Exception:
            logger.warning("Episodi da %s non disponibili", instance.label, exc_info=True)
    return None


TVDB_API = "https://api4.thetvdb.com/v4"
TVDB_TYPE_LABELS = {
    "official": "Aired", "default": "Aired", "dvd": "DVD", "absolute": "Absolute", "alternate": "Alternate",
    "regional": "Regional", "altdvd": "Alternate DVD", "alttwo": "Alternate 2",
}


class TvdbApi:
    """API v4 di TVDB con la chiave delle impostazioni (tvdb_api_key):
    l'ultima risorsa, quando Sonarr non ha la serie o nessun altro
    ordinamento combacia con i file."""

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self._client = client or httpx.Client(base_url=TVDB_API, timeout=20.0)
        self._api_key = api_key
        self._token: str | None = None

    def _login(self) -> None:
        net_guard.check_url(TVDB_API)
        response = self._client.post("/login", json={"apikey": self._api_key})
        response.raise_for_status()
        self._token = (response.json().get("data") or {}).get("token")

    def get(self, path: str, **params) -> dict:
        if self._token is None:
            self._login()
        response = self._client.get(path, params=params or None, headers={"Authorization": f"Bearer {self._token}"})
        response.raise_for_status()
        return response.json().get("data") or {}


def tvdb_orders(api: TvdbApi, tvdb_id: int) -> list[EpisodeOrder]:
    """Ogni tipo di stagione della serie su TVDB (aired, DVD, assoluto,
    alternativi), con i suoi episodi."""
    def fetch() -> list[EpisodeOrder]:
        extended = api.get(f"/series/{tvdb_id}/extended", short="true")
        types = {t.get("type"): t.get("name") for t in extended.get("seasonTypes") or [] if t.get("type")}
        orders = []
        for kind, name in types.items():
            order = EpisodeOrder(f"tvdb:{kind}", f"TVDB · {name or TVDB_TYPE_LABELS.get(kind, kind)}", "tvdb")
            page = 0
            while page is not None and page < 50:
                body = api.get(f"/series/{tvdb_id}/episodes/{kind}", page=page)
                for e in body.get("episodes") or []:
                    if e.get("seasonNumber") is None or e.get("number") is None:
                        continue
                    order.seasons.setdefault(e["seasonNumber"], []).append(
                        OrderEpisode(number=e["number"], titles=[e.get("name") or ""], air_date=e.get("aired")))
                page = page + 1 if (body.get("episodes") and len(body["episodes"]) >= 500) else None
            for eps in order.seasons.values():
                eps.sort(key=lambda ep: ep.number)
            if order.seasons:
                orders.append(order)
        return orders

    return _cached(("tvdb", tvdb_id), fetch)


# --- Combacia con i file ------------------------------------------------------------


def fit(order: EpisodeOrder, found: dict[int, list[int]], pack: bool) -> dict:
    """Quanto i file (stagione -> episodi) combaciano con un ordinamento:
    quanti dei loro episodi esistono, e per un pack quanto sono complete le
    stagioni. score in [0, 1]."""
    files = {(s, e) for s, eps in found.items() for e in eps}
    known = order.episodes()
    matched = len(files & set(known))
    coverage = matched / len(files) if files else 0.0
    score = coverage
    complete = []
    if pack and files:
        for season, eps in found.items():
            numbers = {e.number for e in order.seasons.get(season) or []}
            complete.append(len(set(eps) & numbers) / len(numbers) if numbers else 0.0)
        score = 0.7 * coverage + 0.3 * (sum(complete) / len(complete))
    return {"score": round(score, 3), "matched": matched, "files": len(files),
            "complete_seasons": sum(1 for c in complete if c >= 1.0)}


def build(session: Session, tmdb_id: int, tvdb_id: int | None, found: dict[int, list[int]], pack: bool,
          tmdb_api=None, tvdb_api=None, sonarr_factory=None) -> dict:
    """Gli ordinamenti di una serie per il primo punto di approvazione."""
    from nazgarr.models import EpisodeOrderPreference

    orders: list[EpisodeOrder] = []
    tmdb_key = settings_repo.get_setting(session, "tmdb_api_key")
    if tmdb_api is None and tmdb_key:
        tmdb_api = TmdbApi(tmdb_key)
    if tmdb_api is not None:
        try:
            orders += tmdb_orders(tmdb_api, tmdb_id)
        except httpx.HTTPError:
            logger.warning("Ordinamenti TMDB non disponibili per %s", tmdb_id, exc_info=True)
    default = next((o for o in orders if o.key == TMDB_DEFAULT), None)
    sonarr = sonarr_order(session, tmdb_id, tvdb_id, sonarr_factory)
    if sonarr is not None:
        orders.append(sonarr)

    def best_score() -> float:
        return max((fit(o, found, pack)["score"] for o in orders), default=0.0)

    # TVDB, l'ultima risorsa: se Sonarr non ha la serie o niente combacia del tutto.
    if tvdb_id and (sonarr is None or (found and best_score() < 1.0)):
        key = settings_repo.get_setting(session, "tvdb_api_key")
        if tvdb_api is None and key:
            tvdb_api = TvdbApi(key)
        if tvdb_api is not None:
            try:
                orders += [o for o in tvdb_orders(tvdb_api, tvdb_id)
                           if not (sonarr is not None and o.key in ("tvdb:official", "tvdb:default"))]
            except httpx.HTTPError:
                logger.warning("Ordinamenti TVDB non disponibili per %s", tvdb_id, exc_info=True)
    if default is not None:
        for order in orders:
            if order.source in ("sonarr", "tvdb"):
                align_to(order, default)

    fits = {o.key: fit(o, found, pack) for o in orders}
    keys = [o.key for o in orders]
    preference = session.get(EpisodeOrderPreference, tmdb_id)
    recommended = (
        preference.order_key if preference is not None and preference.order_key in keys
        else next((k for k in TVDB_AIRED_KEYS if k in keys), TMDB_DEFAULT if TMDB_DEFAULT in keys else None)
    )
    best = max(keys, key=lambda k: fits[k]["score"], default=None)
    warning = None
    if found and best and recommended and fits[best]["score"] > fits[recommended]["score"] + WARNING_MARGIN:
        warning = {"code": "files_fit_other_order", "order": best}
    files_order = best if found and best and fits[best]["score"] > 0 else recommended
    by_key = {o.key: o for o in orders}
    return {
        "orders": [o.to_dict() for o in orders],
        "recommended": recommended,
        "files_order": files_order,
        "fits": fits,
        "warning": warning,
        # Gli episodi dei file, tradotti in ogni ordinamento: per i conteggi.
        "found": {
            key: _translate_found(by_key[files_order], by_key[key], found) if files_order else {}
            for key in keys
        },
    }


def _translate_found(source: EpisodeOrder, target: EpisodeOrder, found: dict[int, list[int]]) -> dict[int, list[int]]:
    out: dict[int, set[int]] = defaultdict(set)
    for season, eps in found.items():
        for e in eps:
            for s2, e2 in translate(source, target, season, e):
                out[s2].add(e2)
    return {s: sorted(eps) for s, eps in sorted(out.items())}


# --- Upload ------------------------------------------------------------------------


def found_in_layout(layout_json: str | None) -> dict[int, list[int]]:
    """Gli episodi trovati nei file (nazgarr/upload_source.py), stagione -> episodi."""
    layout = json.loads(layout_json or "{}")
    return {int(season): sorted(eps) for season, eps in (layout.get("episodes_by_season") or {}).items()}


def tvdb_id_for(session: Session, tmdb_id: int, tmdb_api=None) -> int | None:
    """L'id TVDB di una serie TMDB, dai suoi id esterni."""
    key = settings_repo.get_setting(session, "tmdb_api_key")
    api = tmdb_api or (TmdbApi(key) if key else None)
    if api is None:
        return None
    try:
        return _cached(("tvdb_id", tmdb_id), lambda: api.get(f"/tv/{tmdb_id}/external_ids").get("tvdb_id"))
    except httpx.HTTPError:
        logger.warning("Id esterni TMDB non disponibili per %s", tmdb_id, exc_info=True)
        return None


def for_job(session: Session, job, tmdb_id: int, tvdb_id: int | None = None, **sources) -> dict:
    """Gli ordinamenti per il match di un job: con gli episodi dei suoi file."""
    forced = json.loads(job.forced_ids_json or "{}").get("tvdb")
    tvdb_id = tvdb_id or (int(forced) if forced else None) or tvdb_id_for(session, tmdb_id, sources.get("tmdb_api"))
    pack = (job.kind or "") in ("season_pack", "complete_pack")
    return build(session, tmdb_id, tvdb_id, found_in_layout(job.layout_json), pack, **sources)


class EpisodeOrderError(ValueError):
    pass


def snapshot(result: dict, order_key: str) -> dict:
    """L'ordinamento scelto e quello dei file, salvati sul job: servono a
    tradurre i numeri degli episodi dei file (nei nomi generati)."""
    by_key = {o["key"]: o for o in result["orders"]}
    if order_key not in by_key:
        raise EpisodeOrderError(order_key)
    files = result.get("files_order") or order_key
    return {"chosen": by_key[order_key], "files": by_key.get(files, by_key[order_key])}


def remember(session: Session, tmdb_id: int, order_key: str) -> None:
    """La scelta diventa la proposta per la stessa serie la prossima volta."""
    from nazgarr.db_utils import bulk_upsert
    from nazgarr.models import EpisodeOrderPreference

    bulk_upsert(session, EpisodeOrderPreference.__table__, [{"tmdb_id": tmdb_id, "order_key": order_key}],
                conflict_cols=["tmdb_id"], update_cols=["order_key"])


def translate_files(job, season: int, episode: int) -> list[Ref]:
    """Un episodio come lo numerano i file -> come lo numera l'ordinamento
    scelto al match. Senza ordinamento scelto (o senza traduzione) resta com'è."""
    data = json.loads(job.episode_order_json or "{}")
    if not data.get("chosen") or not data.get("files"):
        return [(season, episode)]
    chosen, files = EpisodeOrder.from_dict(data["chosen"]), EpisodeOrder.from_dict(data["files"])
    return translate(files, chosen, season, episode) or [(season, episode)]
