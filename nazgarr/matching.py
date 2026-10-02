"""Motore di matching: per ogni file orfano (media_file o seed_file),
cerca candidati sul tracker e scrive righe `candidate` con confidence
esplicita e spiegabile (mai un punteggio ML opaco). Vedi docs/SPEC.md
sezioni 3, 6, 8.

Ogni candidato è un torrent intero, valutato file per file da
nazgarr/torrent_layout.py: un film a file singolo, un film col suo .nfo, un
season pack. Un pack si ricrea solo se ogni suo episodio ha un file locale
verificato ("season_pack_partial" altrimenti, confidence 0).

Le due direzioni (docs/SPEC.md sezione 3) condividono la stessa
valutazione, cambia solo da quale lato si cercano i file locali e quale
soglia si applica poi in fase di revisione (nazgarr/review.py).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from nazgarr import settings_repo
from nazgarr.adapters.tracker.base import (
    NotSupportedError,
    TrackerAdapter,
    TrackerRateLimitedError,
    UploadError,
)
from nazgarr.arr import ArrGrab, ArrIndex, host_of
from nazgarr.exclusions import CompiledExclusions, load_exclusions
from nazgarr.file_types import is_video
from nazgarr.hardlinks import seed_copies_by_inode
from nazgarr.mediainfo_util import compute_unique_id
from nazgarr.models import (
    Candidate,
    CandidateFile,
    ClientTorrentFile,
    MatchAttempt,
    MediaFile,
    SeedFile,
    Tracker,
)
from nazgarr.run_progress import NULL_PROGRESS
from nazgarr.scan_state import is_current, latest_scan_by_disk
from nazgarr.seeding import seeding_media_file_ids
from nazgarr.torrent_file import TorrentInfo, TorrentMetainfoError, compute_info_hash, parse_torrent_info
from nazgarr.torrent_layout import (
    CONFIDENCE_NO_MATCH,
    CONFIDENCE_PIECE_VERIFIED,  # noqa: F401  (riesportate: le soglie vivono in torrent_layout)
    CONFIDENCE_SIZE_AND_MEDIAINFO_MATCH,  # noqa: F401
    CONFIDENCE_SIZE_ONLY,  # noqa: F401
    Layout,
    LayoutEvaluation,
    LocalFiles,
    evaluate,
    layout_from_catalog,
    layout_from_torrent,
    map_media_side,
    map_seed_side,
)

logger = logging.getLogger(__name__)

# Ogni quanto un file orfano già cercato su un tracker viene ricercato
# comunque, anche se nulla è cambiato (nuovi upload sul tracker). Setting
# app_settings "rematch_interval_days", 0 = ricerca a ogni run come prima.
DEFAULT_REMATCH_INTERVAL_DAYS = 7

# Motivi per cui un torrent non riguarda proprio il file cercato (es. il
# pack di un'altra stagione, trovato cercando per tmdb_id della serie):
# nessuna riga di audit, sarebbe solo rumore moltiplicato per ogni episodio.
_UNRELATED_REASONS = {"anchor_not_in_torrent"}


@dataclass
class MatchContext:
    """Stato di UN tracker per UNA run di matching, condiviso fra tutti gli
    orfani: indici dei file locali, .torrent già scaricati, torrent multi-
    video già valutati (un pack di 10 episodi orfani si valuta e scarica una
    volta sola, non dieci)."""

    session: Session
    tracker_row: Tracker
    tracker_adapter: TrackerAdapter
    direction: str
    arr_index: ArrIndex | None = None
    local: LocalFiles | None = None
    evaluated_packs: set[str] = field(default_factory=set)
    _torrents: dict[str, TorrentInfo | None] = field(default_factory=dict)
    _info_hashes: dict[str, str] = field(default_factory=dict)

    def local_files(self) -> LocalFiles:
        if self.local is None:
            self.local = LocalFiles.load(self.session)
        return self.local

    def fetch_torrent(self, url: str | None) -> TorrentInfo | None:
        """Scarica e analizza un .torrent tramite l'adapter (rate limit del
        tracker), al massimo una volta per URL per run. None su qualunque
        problema di rete/formato; TrackerRateLimitedError risale."""
        if not url:
            return None
        if url not in self._torrents:
            try:
                content = self.tracker_adapter.download_torrent(url)
                self._torrents[url] = parse_torrent_info(content)
                self._info_hashes[url] = compute_info_hash(content)
            except TrackerRateLimitedError:
                raise
            except (UploadError, NotSupportedError, TorrentMetainfoError):
                logger.warning("Download/parsing del .torrent fallito: %s", url, exc_info=True)
                self._torrents[url] = None
        return self._torrents[url]

    def info_hash(self, url: str | None) -> str | None:
        return self._info_hashes.get(url) if url else None


def _map(ctx: MatchContext, layout: Layout, anchor: MediaFile | SeedFile):
    if ctx.direction == "media_to_torrent":
        return map_media_side(layout, anchor, ctx.local_files(), ctx.arr_index)
    return map_seed_side(layout, anchor, ctx.local_files())


def _evaluate(ctx: MatchContext, layout: Layout, anchor, *, download_link: str | None,
              unique_ids: dict[str, str] | None, single_unique_id: str | None) -> LayoutEvaluation:
    return evaluate(
        _map(ctx, layout, anchor), layout,
        anchor_id=anchor.id,
        unique_ids=unique_ids,
        single_unique_id=single_unique_id,
        # lambda, non il riferimento diretto: i test sostituiscono matching.compute_unique_id
        compute_unique_id=lambda path: compute_unique_id(path),
        fetch_torrent=lambda: ctx.fetch_torrent(download_link),
    )


def _persist(
    ctx: MatchContext,
    *,
    media_item_id: int,
    torrent_id_remote: str,
    name: str,
    size_bytes: int,
    layout: Layout,
    evaluation: LayoutEvaluation,
    download_link: str | None,
    info_hash: str | None,
    source: str,
) -> Candidate:
    candidate = Candidate(
        media_item_id=media_item_id,
        tracker_id=ctx.tracker_row.id,
        torrent_id_remote=torrent_id_remote,
        info_hash=info_hash or ctx.info_hash(download_link),
        name=name,
        size_bytes=size_bytes,
        file_list_json=json.dumps([f.path for f in layout.files]),
        folder=layout.folder,
        download_link=download_link,
        source=source,
        direction=ctx.direction,
        size_match=evaluation.size_match,
        mediainfo_match=evaluation.mediainfo_match,
        piece_verified=evaluation.piece_verified,
        piece_boundary_count=evaluation.piece_boundary_count,
        confidence=evaluation.confidence,
        ambiguity_reason=evaluation.ambiguity_reason,
        piece_length=layout.piece_length,
    )
    for m in evaluation.files:
        local = m.local
        candidate.files.append(CandidateFile(
            torrent_path=m.layout_file.path,
            size_bytes=m.layout_file.size,
            is_video=m.layout_file.is_video,
            media_file_id=local.id if local is not None and local.kind == "media" else None,
            seed_file_id=local.id if local is not None and local.kind == "seed" else None,
            size_match=m.size_match,
            mediainfo_match=m.mediainfo_match,
            piece_verified=m.piece_verified,
        ))
    ctx.session.add(candidate)
    return candidate


def match_file(ctx: MatchContext, anchor: MediaFile | SeedFile, media_item_id: int, tmdb_id: int) -> list[Candidate]:
    """Cerca sul catalogo del tracker per tmdb_id e valuta ogni torrent
    trovato contro i file locali. Persiste anche i candidati a confidence 0
    (audit trail), tranne quelli che non riguardano affatto questo file."""
    persisted = []
    for tc in ctx.tracker_adapter.search_by_tmdb(tmdb_id):
        layout = layout_from_catalog(tc.file_list, tc.file_sizes, tc.folder, tc.size_bytes, tc.name)
        multi_video = len(layout.videos) > 1
        if multi_video and tc.torrent_id_remote in ctx.evaluated_packs:
            continue  # già valutato in questa run per un altro episodio dello stesso pack
        evaluation = _evaluate(
            ctx, layout, anchor, download_link=tc.download_link,
            unique_ids=tc.mediainfo_unique_ids_by_filename, single_unique_id=tc.mediainfo_unique_id,
        )
        if evaluation.ambiguity_reason in _UNRELATED_REASONS:
            continue
        if evaluation.confidence > CONFIDENCE_NO_MATCH and len(layout.files) > 1:
            # Il catalogo UNIT3D spesso non riporta la cartella del torrent (né
            # sempre gli stessi percorsi): ricreare il seed con quei dati mette
            # i file nel posto sbagliato e il recheck fallisce. Per un
            # candidato plausibile con più file la struttura vera la dà solo il
            # .torrent — un download per pack, mai per quelli non pertinenti.
            parsed = layout.torrent or ctx.fetch_torrent(tc.download_link)
            if parsed is not None:
                layout = layout_from_torrent(parsed)
                evaluation = _evaluate(
                    ctx, layout, anchor, download_link=tc.download_link,
                    unique_ids=tc.mediainfo_unique_ids_by_filename, single_unique_id=tc.mediainfo_unique_id,
                )
            else:
                evaluation.confidence = CONFIDENCE_NO_MATCH
                evaluation.ambiguity_reason = "torrent_structure_unknown"
        if multi_video:
            ctx.evaluated_packs.add(tc.torrent_id_remote)
        persisted.append(_persist(
            ctx, media_item_id=media_item_id, torrent_id_remote=tc.torrent_id_remote, name=tc.name,
            size_bytes=tc.size_bytes, layout=layout, evaluation=evaluation, download_link=tc.download_link,
            info_hash=tc.info_hash, source="catalog_search",
        ))
    ctx.session.commit()
    return persisted


def match_from_history(ctx: MatchContext, anchor: MediaFile | SeedFile, media_item_id: int,
                       grab: ArrGrab) -> list[Candidate] | None:
    """Candidato dal torrent che Radarr/Sonarr ricordano per questo file
    (nazgarr/arr.py): un solo download del .torrent al posto della ricerca sul
    catalogo. Stesse regole di confidence — la provenienza dalla history non
    alza da sola la confidence: un file può essere stato sostituito dopo
    l'import, sono size e piece hash a dirlo. None se il .torrent non è
    scaricabile/leggibile o il pack è già stato valutato in questa run: il
    chiamante decide se ripiegare sulla ricerca."""
    if grab.torrent_id_remote in ctx.evaluated_packs:
        return []
    # Prima il link della history con la chiave attuale (se il tracker la
    # conosce: nessuna chiamata in più), poi, se rifiutato, il dettaglio.
    rewrite = getattr(ctx.tracker_adapter, "rewrite_download_link", None)
    download_link = rewrite(grab.download_url) if rewrite else grab.download_url
    parsed = ctx.fetch_torrent(download_link)
    if parsed is None:
        # Il link della history contiene la chiave di quando è stato fatto il
        # grab: se nel frattempo è cambiata il tracker lo rifiuta. Il
        # dettaglio del torrent (una chiamata) dà il link con la chiave
        # attuale — ed è quello che deve finire nel candidato, perché è il
        # link che poi scaricherà il client.
        download_link = _current_download_link(ctx, grab.torrent_id_remote)
        parsed = ctx.fetch_torrent(download_link) if download_link else None
    if parsed is None:
        return None
    layout = layout_from_torrent(parsed)
    evaluation = _evaluate(ctx, layout, anchor, download_link=download_link, unique_ids=None,
                           single_unique_id=None)
    if len(layout.videos) > 1:
        ctx.evaluated_packs.add(grab.torrent_id_remote)
    candidate = _persist(
        ctx, media_item_id=media_item_id, torrent_id_remote=grab.torrent_id_remote, name=parsed.name,
        size_bytes=parsed.total_length, layout=layout, evaluation=evaluation, download_link=download_link,
        info_hash=grab.info_hash, source="history",
    )
    ctx.session.commit()
    return [candidate]


def _current_download_link(ctx: MatchContext, torrent_id_remote: str) -> str | None:
    get_detail = getattr(ctx.tracker_adapter, "get_torrent_detail", None)
    if get_detail is None:
        return None
    try:
        return get_detail(torrent_id_remote).download_link
    except TrackerRateLimitedError:
        raise
    except (UploadError, NotSupportedError, KeyError, ValueError):
        logger.warning("Dettaglio del torrent %s non disponibile", torrent_id_remote, exc_info=True)
        return None


def _anchor_path(anchor: MediaFile | SeedFile) -> str:
    return f"{anchor.disk.root_path}/{anchor.relative_path}"


def find_candidates(ctx: MatchContext, anchor: MediaFile | SeedFile, media_item_id: int,
                    tmdb_id: int) -> tuple[list[Candidate], bool]:
    """(candidati, da_history). Prima la history di Radarr/Sonarr se ricorda
    un torrent di QUESTO tracker per il file; ricerca sul catalogo solo se
    non c'è o non ha dato un candidato plausibile."""
    grab = ctx.arr_index.grab_for(_anchor_path(anchor), anchor.size_bytes) if ctx.arr_index is not None else None
    if grab is not None and grab.tracker_host == host_of(ctx.tracker_row.base_url):
        candidates = match_from_history(ctx, anchor, media_item_id, grab)
        if candidates is not None and (
            not candidates or any(c.confidence > CONFIDENCE_NO_MATCH for c in candidates)
        ):
            return candidates, True
    return match_file(ctx, anchor, media_item_id, tmdb_id), False


def orphan_media_files(
    session: Session, exclusions: CompiledExclusions | None = None, tracker: Tracker | None = None
) -> list[MediaFile]:
    """media_file con identità risolta e non in seed (orphan_media, docs/SPEC.md
    sezione 3): stessa regola della Library (nazgarr/seeding.py), un hardlink che
    nessun client segue non conta. Con un tracker e la ricerca dei cross-seed
    accesa, "non in seed su questo tracker". Solo quelli risolvibili e non
    esclusi (Configuration > Exclusions)."""
    linked_ids = seeding_media_file_ids(session, tracker)
    latest = latest_scan_by_disk(session, MediaFile)
    return [
        mf
        for mf in session.query(MediaFile).filter(MediaFile.media_item_id.isnot(None)).all()
        if mf.id not in linked_ids
        and is_current(mf, latest)  # un file sparito dal disco non si cerca più
        and is_video(mf.relative_path)
        and not (exclusions and exclusions.is_excluded(mf.relative_path))
    ]


def orphan_seed_files_with_identity(
    session: Session, exclusions: CompiledExclusions | None = None
) -> list[SeedFile]:
    """seed_file non tracciato da alcun client (orphan_torrent) il cui
    media_file collegato ha già un'identità risolta (docs/SPEC.md sezione 3,
    direzione torrent->client), esclusi i file esclusi.

    Semplificazione esplicita di questa fase: un seed_file senza
    media_file_id (mai stato organizzato nella libreria, quindi mai
    passato dal resolver) non viene risolto qui — richiederebbe girare il
    resolver anche sul lato torrent, non ancora fatto (docs/ROADMAP.md
    Fase 4)."""
    tracked_ids = {
        row[0]
        for row in session.query(ClientTorrentFile.seed_file_id)
        .filter(ClientTorrentFile.seed_file_id.isnot(None))
        .all()
    }
    # Un'altra copia (hardlink) di un file in seed da un altro percorso: gli
    # stessi byte sono già in seed, niente da cercare (nazgarr/library.py).
    for group in seed_copies_by_inode(session).values():
        if group & tracked_ids:
            tracked_ids |= group
    result = []
    latest = latest_scan_by_disk(session, SeedFile)
    for sf in session.query(SeedFile).filter(SeedFile.media_file_id.isnot(None)).all():
        if sf.id in tracked_ids or not is_current(sf, latest):
            continue
        if not is_video(sf.relative_path):
            continue
        if exclusions and exclusions.is_excluded(sf.relative_path):
            continue
        if sf.media_file is not None and sf.media_file.media_item_id is not None:
            result.append(sf)
    return result


def get_rematch_interval(session: Session) -> timedelta:
    raw = settings_repo.get_setting(session, "rematch_interval_days")
    try:
        days = float(raw) if raw is not None else DEFAULT_REMATCH_INTERVAL_DAYS
    except ValueError:
        days = DEFAULT_REMATCH_INTERVAL_DAYS
    return timedelta(days=max(days, 0))


def _as_utc(value: datetime) -> datetime:
    # SQLite restituisce datetime naive anche se salvati aware.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _attempt_for(
    session: Session, tracker_row: Tracker, *, media_file_id: int | None = None, seed_file_id: int | None = None
) -> MatchAttempt | None:
    query = session.query(MatchAttempt).filter_by(tracker_id=tracker_row.id)
    if media_file_id is not None:
        return query.filter_by(media_file_id=media_file_id).one_or_none()
    return query.filter_by(seed_file_id=seed_file_id).one_or_none()


def _is_fresh(attempt: MatchAttempt | None, size_bytes: int, tmdb_id: int, interval: timedelta) -> bool:
    """Un tentativo precedente vale ancora se il file e la sua identità non
    sono cambiati e non è passato rematch_interval_days — in quel caso i
    candidati e la review già salvati restano validi, nessuna nuova ricerca."""
    if attempt is None or interval <= timedelta(0):
        return False
    if attempt.size_bytes != size_bytes or attempt.tmdb_id != tmdb_id:
        return False
    return datetime.now(UTC) - _as_utc(attempt.attempted_at) < interval


def _record_attempt(
    session: Session,
    attempt: MatchAttempt | None,
    tracker_row: Tracker,
    size_bytes: int,
    tmdb_id: int,
    *,
    media_file_id: int | None = None,
    seed_file_id: int | None = None,
) -> None:
    if attempt is None:
        attempt = MatchAttempt(tracker_id=tracker_row.id, media_file_id=media_file_id, seed_file_id=seed_file_id)
        session.add(attempt)
    attempt.size_bytes = size_bytes
    attempt.tmdb_id = tmdb_id
    attempt.attempted_at = datetime.now(UTC)
    session.commit()


def _new_totals() -> dict:
    return {
        "files": 0, "from_history": 0, "candidates": 0, "skipped_fresh": 0, "failed": 0, "rate_limited": False,
    }


def run_media_to_torrent_matching(
    session: Session, tracker_row: Tracker, tracker_adapter: TrackerAdapter, arr_index: ArrIndex | None = None,
    progress=NULL_PROGRESS, only_media_file_ids: set[int] | None = None, force: bool = False,
) -> dict:
    """Un errore su un singolo file lo salta (loggato, contato in "failed")
    senza fermare gli altri; un TrackerRateLimitedError invece ferma il
    matching su questo tracker per il resto della run ("rate_limited"),
    lasciando i file rimanenti al prossimo giro — la ricerca di quelli
    completati è già registrata in match_attempt, quindi non si ripete."""
    from nazgarr.review import create_review_for_media_file  # import qui: evita un ciclo review<->matching

    totals = _new_totals()
    interval = get_rematch_interval(session)
    ctx = MatchContext(session, tracker_row, tracker_adapter, "media_to_torrent", arr_index)
    orphans = orphan_media_files(session, load_exclusions(session), tracker_row)
    if only_media_file_ids is not None:
        # "Cerca ora" dalla scheda di dettaglio: solo i file di quel contenuto.
        orphans = [mf for mf in orphans if mf.id in only_media_file_ids]
    progress.add_total(len(orphans))
    for media_file in orphans:
        tmdb_id = media_file.media_item.tmdb_id
        attempt = _attempt_for(session, tracker_row, media_file_id=media_file.id)
        if not force and _is_fresh(attempt, media_file.size_bytes, tmdb_id, interval):
            totals["skipped_fresh"] += 1
            progress.advance(skipped=1)
            continue
        try:
            candidates, from_history = find_candidates(ctx, media_file, media_file.media_item_id, tmdb_id)
            create_review_for_media_file(session, media_file, candidates)
        except TrackerRateLimitedError:
            logger.warning("Tracker %r in rate limit: matching interrotto per questa run", tracker_row.label)
            session.rollback()
            totals["rate_limited"] = True
            break
        except Exception:
            logger.exception("Matching fallito per media_file %s su tracker %r", media_file.id, tracker_row.label)
            session.rollback()
            totals["failed"] += 1
            progress.advance()
            continue
        _record_attempt(
            session, attempt, tracker_row, media_file.size_bytes, tmdb_id, media_file_id=media_file.id
        )
        totals["files"] += 1
        totals["from_history"] += int(from_history)
        totals["candidates"] += len(candidates)
        progress.advance()
        progress.result(candidates=len(candidates))
    return totals


def run_torrent_to_client_matching(
    session: Session, tracker_row: Tracker, tracker_adapter: TrackerAdapter, arr_index: ArrIndex | None = None,
    progress=NULL_PROGRESS,
) -> dict:
    """Stesse regole di run_media_to_torrent_matching, direzione opposta."""
    from nazgarr.review import create_review_for_seed_file  # import qui: evita un ciclo review<->matching

    totals = _new_totals()
    interval = get_rematch_interval(session)
    ctx = MatchContext(session, tracker_row, tracker_adapter, "torrent_to_client", arr_index)
    orphans = orphan_seed_files_with_identity(session, load_exclusions(session))
    progress.add_total(len(orphans))
    for seed_file in orphans:
        media_item = seed_file.media_file.media_item
        attempt = _attempt_for(session, tracker_row, seed_file_id=seed_file.id)
        if _is_fresh(attempt, seed_file.size_bytes, media_item.tmdb_id, interval):
            totals["skipped_fresh"] += 1
            progress.advance(skipped=1)
            continue
        try:
            candidates, from_history = find_candidates(ctx, seed_file, media_item.id, media_item.tmdb_id)
            create_review_for_seed_file(session, seed_file, candidates)
        except TrackerRateLimitedError:
            logger.warning("Tracker %r in rate limit: matching interrotto per questa run", tracker_row.label)
            session.rollback()
            totals["rate_limited"] = True
            break
        except Exception:
            logger.exception("Matching fallito per seed_file %s su tracker %r", seed_file.id, tracker_row.label)
            session.rollback()
            totals["failed"] += 1
            progress.advance()
            continue
        _record_attempt(
            session, attempt, tracker_row, seed_file.size_bytes, media_item.tmdb_id, seed_file_id=seed_file.id
        )
        totals["files"] += 1
        totals["from_history"] += int(from_history)
        totals["candidates"] += len(candidates)
        progress.advance()
        progress.result(candidates=len(candidates))
    return totals
