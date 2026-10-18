"""Una stagione incompleta divisa in episodi (decisione dell'utente,
2026-10-09): un season pack che non ha tutti gli episodi della stagione (es.
i primi 2 di 8 usciti insieme) non si carica come pack, ma con un upload per
episodio, come quelli usciti uno alla volta. Anche con un solo episodio
mancante.

Dalla cartella osservata succede da solo, dopo il match automatico
(impostazione upload_watch_split_incomplete, accesa di default); al match a
mano c'è "Dividi in episodi". L'upload originale si chiude (annullato, con
l'elenco dei nuovi, e non si riprende); ogni episodio ha gli stessi tracker,
lo stesso match e lo stesso ordinamento degli episodi, riparte dall'analisi
e si ferma alla decisione come sempre. Quando l'ultimo è in seed, la
cartella osservata rimasta (nfo, sample...) si toglie
(nazgarr/upload/execute.py).

Prima ancora, una cartella con più stagioni (decisione dell'utente,
2026-10-11: una serie intera arrivata nella cartella osservata) diventa un
upload per stagione, ognuno con i soli file della sua
(nazgarr/upload/pack.py season_selection); impostazione
upload_watch_split_seasons, accesa di default. Una di quelle stagioni, se
incompleta, si divide poi in episodi come sopra."""

import json
import logging
import posixpath

from sqlalchemy.orm import Session

from nazgarr.core import settings_registry
from nazgarr.core.models import UploadJob
from nazgarr.library import episode_orders
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload import pack as upload_pack
from nazgarr.upload.source import scan_source

logger = logging.getLogger(__name__)

SPLIT_SETTING = "upload_watch_split_incomplete"
SEASONS_SETTING = "upload_watch_split_seasons"


def enabled(session: Session) -> bool:
    return settings_registry.get_bool(session, SPLIT_SETTING)


def seasons_enabled(session: Session) -> bool:
    return settings_registry.get_bool(session, SEASONS_SETTING)


UNKNOWN = "unknown"


def _count(job: UploadJob, details: dict | None) -> tuple[int, int] | str | None:
    """season_count, con UNKNOWN quando la traduzione nell'ordinamento
    scelto perde episodi."""
    seasons = json.loads(job.seasons_json or "[]")
    if job.kind != "season_pack" or len(seasons) != 1:
        return None
    season = seasons[0]
    found = episode_orders.found_in_layout(job.layout_json)
    parent = _orders_of(job)
    if parent is not None:
        _snapshot, chosen, files = parent
        numbers = {e.number for e in chosen.seasons.get(season, [])}
        known = files.episodes()
        lookup = episode_orders.translator(files, chosen)
        targets: set[tuple[int, int]] = set()
        inputs = 0
        for file_season, eps in found.items():
            for e in eps:
                if (file_season, e) not in known:
                    continue  # un E00 o un extra: non è un episodio di quell'ordinamento
                refs = lookup(file_season, e)
                if not refs:
                    return UNKNOWN  # un episodio che non si traduce non è un episodio mancante
                inputs += 1
                targets.update(refs)
        have, expected = len({e for s, e in targets if s == season} & numbers), len(numbers)
        if len(targets) < inputs and have < expected:
            return UNKNOWN  # due file sullo stesso episodio: forse uno è finito nel posto sbagliato
    else:
        expected = next((s.get("episode_count") or 0 for s in (details or {}).get("seasons") or []
                         if s.get("season_number") == season), 0)
        have = len(set(found.get(season, [])) & set(range(1, expected + 1)))
    return (have, expected) if expected else None


def season_count(job: UploadJob, details: dict | None) -> tuple[int, int] | None:
    """(episodi trovati, episodi della stagione) di un season pack
    confermato, nella numerazione scelta al match; None se non si sa.
    Contano solo gli episodi che la stagione ha (audit 2026-10-18: un E00 o
    un E13 di una stagione da 12 coprivano l'episodio mancante), e un
    episodio dei file che non si traduce nell'ordinamento scelto rende il
    conto incerto invece di contare come mancante (dividendo in episodi una
    stagione completa)."""
    count = _count(job, details)
    return count if isinstance(count, tuple) else None


def untranslated(job: UploadJob, details: dict | None) -> bool:
    """Il conto della stagione non si sa perché la traduzione perde episodi:
    niente divisione automatica, e il registro lo dice."""
    return _count(job, details) == UNKNOWN


def is_incomplete(job: UploadJob, details: dict | None) -> bool:
    count = season_count(job, details)
    return count is not None and 0 < count[0] < count[1]


def _orders_of(job: UploadJob) -> tuple[dict, episode_orders.EpisodeOrder, episode_orders.EpisodeOrder] | None:
    """L'ordinamento scelto al match di un job e quello dei file (il suo
    snapshot), se ne ha uno."""
    snapshot = json.loads(job.episode_order_json or "null")
    if not job.episode_order or not snapshot or (snapshot.get("chosen") or {}).get("seasons") is None:
        return None
    files = snapshot.get("files") or snapshot["chosen"]
    return ({"chosen": snapshot["chosen"], "files": files}, episode_orders.EpisodeOrder.from_dict(snapshot["chosen"]),
            episode_orders.EpisodeOrder.from_dict(files))


def _child_orders(parent, child: UploadJob) -> dict | None:
    """Gli ordinamenti di un episodio diviso: quelli del pack, con i numeri
    del suo file tradotti come nel pack (audit 2026-10-18). Ricalcolati dal
    suo file solo, ogni ordinamento combaciava e la numerazione dei file
    diventava quella che vince a parità (preferenza, TVDB aired, TMDB): la
    Parte 2 S02E01-03 diventava S03E01-03."""
    if parent is None:
        return None
    snapshot, chosen, files = parent
    found = episode_orders.found_in_layout(child.layout_json)
    return {"orders": [snapshot["chosen"], snapshot["files"]], "files_order": files.key,
            "found": {chosen.key: episode_orders.translate_found(files, chosen, found)}}


def _child_overrides(job: UploadJob) -> dict:
    """Le correzioni valgono per ogni parte, il nome scritto a mano no: è
    il file o la cartella di quel torrent."""
    overrides = json.loads(job.overrides_json or "{}")
    overrides.pop("content_name", None)
    return overrides


def _tracker_choices(job: UploadJob) -> dict[int, dict]:
    choices = {}
    for target in job.targets:
        freeleech = json.loads(target.flags_json or "{}").get("freeleech")
        if freeleech:
            choices[target.tracker_id] = {"freeleech": freeleech}
    return choices


def split(session: Session, job: UploadJob, details: dict | None) -> list[UploadJob]:
    """Un upload per video del pack, già confermato (job in 'analyzing',
    dopo il match). Quelli il cui episodio non si legge dal nome restano al
    match, da confermare a mano. Il job si chiude. Restituisce i nuovi."""
    from nazgarr.upload import identify  # import qui: identify chiama split

    if job.status != "analyzing" or job.kind != "season_pack" or job.disk is None:
        raise upload_jobs.UploadJobError("upload_split_not_a_pack")
    layout = json.loads(job.layout_json or "{}")
    candidates = json.loads(job.candidates_json or "[]")
    overrides = _child_overrides(job)
    forced = json.loads(job.forced_ids_json or "{}")
    tracker_ids = [t.tracker_id for t in job.targets]
    choices = _tracker_choices(job)
    # Le stagioni scelte di una cartella con più stagioni (nazgarr/upload/pack.py):
    # nel layout i video hanno il nome nel pack, il percorso è nel pack.
    in_pack = {posixpath.basename(f): f for f in json.loads(job.pack_json or "{}").get("files", [])}
    parent_orders = _orders_of(job)
    children: list[UploadJob] = []
    try:
        for video in layout.get("videos") or []:
            relative = in_pack.get(video["relative_path"]) or posixpath.join(job.relative_path, video["relative_path"])
            child = upload_jobs.create_job(session, job.disk, relative, tracker_ids, forced, overrides, choices,
                                           origin=job.origin)
            children.append(child)
            child.split_from_id = job.id
            upload_jobs.log_event(session, child, "split_from", upload=job.id)
            session.commit()
            source = scan_source(child.source_path)
            identify.record_identification(session, child, source, candidates)
            episode = source.videos[0].episodes[0] if source.videos and source.videos[0].episodes else None
            try:
                identify.confirm(session, child, content_type="tv", tmdb_id=job.tmdb_id, kind=source.kind,
                                 seasons=source.seasons, episode=episode, details=details,
                                 order_key=job.episode_order, orders=_child_orders(parent_orders, child),
                                 translate=True)
            except (upload_jobs.UploadJobError, episode_orders.EpisodeOrderError) as exc:
                session.rollback()
                child = session.get(UploadJob, child.id)
                upload_jobs.log_event(session, child, "auto_match_failed", level="warning",
                                      reason=getattr(exc, "code", None) or "episode_order")
            session.commit()
        _close(session, job, "job_split", children)
    except Exception:
        _discard(session, children)
        raise
    logger.info("Upload %s: stagione incompleta divisa in %s upload (%s)", job.id, len(children),
                ", ".join(str(c.id) for c in children))
    return children


def _discard(session: Session, children: list[UploadJob]) -> None:
    """Una divisione fallita a metà non lascia upload vivi sugli stessi file
    del pack, che va avanti intero (audit 2026-10-18): arrivavano alla
    decisione insieme a lui, senza niente che lo dicesse. I nuovi creati
    fin lì si tolgono: non hanno fatto niente fuori da Nazgarr."""
    ids = [child.id for child in children if child.id is not None]
    session.rollback()
    for job_id in ids:
        child = session.get(UploadJob, job_id)
        if child is not None:
            session.delete(child)
    session.commit()


def _close(session: Session, job: UploadJob, code: str, children: list[UploadJob]) -> None:
    """Il job diviso si chiude (annullato, con l'elenco dei nuovi): si va
    avanti da quelli, e non si riprende."""
    if not upload_jobs.transition(session, job, "analyzing", "cancelled", emit=False, stage=None,
                                  queue_position=None):
        raise upload_jobs.UploadJobError("upload_job_wrong_status", status=job.status)
    upload_jobs.log_event(session, job, code, count=len(children), jobs=[c.id for c in children])
    session.commit()


def seasons_to_split(job: UploadJob) -> list[int]:
    """Le stagioni di un complete pack confermato che hanno dei video nella
    sua cartella, se sono almeno due. Vuoto per un pack di file scelti a mano
    o una cartella i cui video non dicono la stagione."""
    if job.kind != "complete_pack" or not job.is_dir or upload_pack.is_pack(job):
        return []
    seasons = sorted(upload_pack.seasons_in_source(job) & set(json.loads(job.seasons_json or "[]")))
    return seasons if len(seasons) > 1 else []


def split_seasons(session: Session, job: UploadJob, details: dict | None) -> list[UploadJob]:
    """Un upload per stagione di un complete pack già confermato (job in
    'analyzing', dopo il match): ognuno è la stessa cartella con la sua
    stagione, quindi un pack dei soli file di quella. Stessi tracker, stesso
    match e ordinamento degli episodi. Il job si chiude. Restituisce i nuovi."""
    from nazgarr.upload import identify  # import qui: identify chiama split

    seasons = seasons_to_split(job)
    if job.status != "analyzing" or not seasons or job.disk is None:
        raise upload_jobs.UploadJobError("upload_split_not_a_pack")
    candidates = json.loads(job.candidates_json or "[]")
    overrides = _child_overrides(job)
    forced = json.loads(job.forced_ids_json or "{}")
    tracker_ids = [t.tracker_id for t in job.targets]
    choices = _tracker_choices(job)
    source = scan_source(job.source_path)
    # L'ordinamento scelto per il complete pack, senza chiederlo di nuovo alle fonti.
    parent_orders = _orders_of(job)
    orders = None
    if parent_orders is not None:
        orders = {"orders": [parent_orders[0]["chosen"], parent_orders[0]["files"]],
                  "files_order": parent_orders[2].key}
    children: list[UploadJob] = []
    try:
        for season in seasons:
            child = upload_jobs.create_job(session, job.disk, job.relative_path, tracker_ids, forced, overrides,
                                           choices, origin=job.origin)
            children.append(child)
            child.split_from_id = job.id
            upload_jobs.log_event(session, child, "split_from_seasons", upload=job.id, season=f"S{season:02d}")
            session.commit()
            identify.record_identification(session, child, source, candidates)
            try:
                identify.confirm(session, child, content_type="tv", tmdb_id=job.tmdb_id, kind="season_pack",
                                 seasons=[season], episode=None, details=details, order_key=job.episode_order,
                                 orders=orders)
            except (upload_jobs.UploadJobError, episode_orders.EpisodeOrderError) as exc:
                # Resta al match, con la cartella intera: si sceglie a mano.
                session.rollback()
                child = session.get(UploadJob, child.id)
                upload_jobs.log_event(session, child, "auto_match_failed", level="warning",
                                      reason=getattr(exc, "code", None) or "episode_order")
            session.commit()
        _close(session, job, "job_split_seasons", children)
    except Exception:
        _discard(session, children)
        raise
    logger.info("Upload %s: %s stagioni divise in %s upload (%s)", job.id, len(seasons), len(children),
                ", ".join(str(c.id) for c in children))
    return children
