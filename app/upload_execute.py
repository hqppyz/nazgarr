"""Esecuzione di un job di upload approvato (docs/SPEC.md §9 "Upload flow
v2"), nel worker "heavy", un job alla volta nell'ordine della coda.

L'approvazione al secondo punto è la conferma umana obbligatoria: da qui si
va fino in fondo senza chiedere altro. Una volta per job:
- gli hash dei piece (torf), riusati per il .torrent di ogni tracker: stesso
  contenuto, announce e campo source diversi, quindi info hash diversi;
- screenshot e upload sull'image host, mediainfo (già letto nell'analisi).

Poi per ogni tracker, in ordine, la sua azione:
- upload: .torrent del tracker, descrizione dal suo template, invio, e il
  torrent aggiunto al client del tracker con recheck forzato;
- reseed: il .torrent già sul tracker, i file sistemati con i nomi che si
  aspetta, e l'aggiunta al client con recheck forzato. Mai skip_checking.

Dove seedano: hardlink nella cartella per gli upload del disco
(disk.effective_upload_rel_path: upload_rel_path, o torrents_rel_path),
decisione dell'utente del 2026-09-30. Se la sorgente è già lì dentro con lo
stesso layout del torrent, si fa seed sul posto. Stesso filesystem o errore
esplicito, come nel reseeding. Un tracker che fallisce non ferma gli altri.
"""

import json
import logging
import os
import re
from datetime import UTC, datetime

import torf
from sqlalchemy.orm import Session

from app import adapter_factory, screenshots, settings_repo, upload_jobs
from app.adapter_factory import ImageHostConfigError
from app.adapters.image_host.base import ImageHostError
from app.adapters.tracker.base import UploadFields
from app.executor import client_visible_path
from app.file_types import is_video
from app.fs_scope import ScopeViolation, resolve_scoped
from app.models import TorrentClient, TrackerUploadProfile, UploadJob, UploadTarget
from app.torrent_file import parse_torrent_info
from app.upload import render_description
from app.upload_jobs import UploadJobError
from app.upload_verify import build_locator

logger = logging.getLogger(__name__)

# File che non finiscono mai nel torrent di un upload.
EXCLUDE_GLOBS = [".*", "*.part", "*.!qB", "*.!ut", "Thumbs.db", "desktop.ini", "*sample*", "*Sample*"]
PROGRESS_EVERY_SECONDS = 1.0
SD_RESOLUTIONS = {"480p", "480i", "576p", "576i"}


# --- dove seedare -------------------------------------------------------------


def seed_root(job: UploadJob) -> str:
    disk = job.disk
    if disk is None:
        raise UploadJobError("upload_disk_missing")
    rel = disk.effective_upload_rel_path
    if not rel:
        raise UploadJobError("upload_no_seed_folder", disk=disk.label)
    try:
        root = resolve_scoped(disk.root_path, rel)
    except ScopeViolation as exc:
        raise UploadJobError("path_outside_scope", path=exc.candidate) from exc
    if not os.path.isdir(root):
        raise UploadJobError("upload_seed_folder_missing", path=root)
    return root


def seeding_area(job: UploadJob) -> str | None:
    """La cartella di seeding del disco (torrents_rel_path), se configurata."""
    disk = job.disk
    if disk is None or not disk.torrents_rel_path:
        return None
    try:
        return resolve_scoped(disk.root_path, disk.torrents_rel_path)
    except ScopeViolation:
        return None


def _inside(path: str, folder: str | None) -> bool:
    if folder is None:
        return False
    real, base = os.path.realpath(path), os.path.realpath(folder)
    return real.startswith(base + os.sep)


def link_files(pairs: list[tuple[str, str]], root: str) -> int:
    """Crea gli hardlink (sorgente, destinazione); una destinazione che è già
    lo stesso file (un tentativo precedente) va bene, un file diverso no.
    Restituisce quanti hardlink ha creato."""
    root_dev = os.stat(root).st_dev
    for source, _target in pairs:
        if os.stat(source).st_dev != root_dev:
            raise UploadJobError("upload_cross_device", path=source)
    created = 0
    for source, target in pairs:
        resolve_scoped(root, os.path.relpath(target, root))  # mai fuori dalla cartella di seed
        if os.path.exists(target):
            if os.path.samefile(source, target):
                continue
            raise UploadJobError("upload_seed_path_exists", path=target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.link(source, target)
        created += 1
    return created


# --- una volta per job --------------------------------------------------------


def _job_dir(worker, job: UploadJob) -> str:
    path = os.path.join(worker.data_dir, "uploads", str(job.id))
    os.makedirs(path, exist_ok=True)
    return path


def _progress(session: Session, job: UploadJob, stage: str, done: int | None = None, total: int | None = None):
    job.stage, job.progress_done, job.progress_total = stage, done, total
    session.commit()


def hash_pieces(session: Session, job: UploadJob) -> torf.Torrent:
    torrent = torf.Torrent(path=job.source_path, private=True, exclude_globs=EXCLUDE_GLOBS)
    if not torrent.files:
        raise UploadJobError("no_video_files")

    def callback(_torrent, _path, done, total):
        _progress(session, job, "hashing", done, total)
        session.refresh(job)
        # Annullato a metà: torf si ferma se il callback restituisce qualcosa.
        return True if job.status == "cancelled" else None

    _progress(session, job, "hashing", 0, None)
    torrent.generate(callback=callback, interval=PROGRESS_EVERY_SECONDS)
    session.refresh(job)
    if job.status == "cancelled":
        raise _Cancelled()
    return torrent


def take_screenshots(session: Session, job: UploadJob, worker, count: int) -> list[str]:
    if count <= 0:
        return []
    layout = json.loads(job.layout_json or "{}")
    main_video = layout.get("main_video") or job.source_path
    tonemap = (settings_repo.get_setting(session, "upload_tonemap_hdr") or "").lower() == "true"
    _progress(session, job, "screenshots", 0, count)
    try:
        chain = adapter_factory.build_image_host_chain(session)
    except ImageHostConfigError as exc:
        raise UploadJobError(exc.code, **exc.params) from exc
    try:
        paths = screenshots.generate_screenshots(
            main_video, os.path.join(_job_dir(worker, job), "screenshots"), count=count, tonemap=tonemap
        )
    except screenshots.ScreenshotError as exc:
        raise UploadJobError("upload_screenshots_failed", error=str(exc)) from exc
    urls = []
    for i, path in enumerate(paths, start=1):
        try:
            urls.append(chain.upload(path))
        except ImageHostError:
            logger.warning("Upload dello screenshot %r fallito", path, exc_info=True)
        _progress(session, job, "screenshots", i, count)
    if not urls:
        raise UploadJobError("upload_screenshots_failed", error="image host")
    return urls


# --- per tracker --------------------------------------------------------------


def _imdb_number(imdb_id: str | None) -> str:
    match = re.search(r"(\d+)", imdb_id or "")
    return match.group(1) if match else "0"


def upload_fields(job: UploadJob, target: UploadTarget, description: str, resolution_key: str | None) -> UploadFields:
    flags = json.loads(target.flags_json or "{}")
    seasons = json.loads(job.seasons_json or "[]")
    tv = job.content_type == "tv"
    return UploadFields(
        name=target.approved_name,
        description=description,
        mediainfo=job.mediainfo_text or "",
        category_id=target.category_id,
        type_id=target.type_id,
        resolution_id=target.resolution_id,
        tmdb_id=job.tmdb_id,
        imdb_id=_imdb_number(job.imdb_id),
        tvdb_id=job.tvdb_id or 0,
        mal_id=job.mal_id or 0,
        season_number=(min(seasons) if seasons else 0) if tv else None,
        episode_number=(job.episode if job.kind == "episode" else 0) if tv else None,
        anonymous=bool(flags.get("anonymous")),
        personal_release=bool(flags.get("personal_release")),
        internal=bool(flags.get("internal")),
        stream=bool(flags.get("stream")),
        free=int(flags.get("freeleech") or 0),
        sd=resolution_key in SD_RESOLUTIONS,
    )


def _client(session: Session, target: UploadTarget):
    if target.torrent_client_id is None:
        return None, None
    row = session.get(TorrentClient, target.torrent_client_id)
    if row is None or not row.enabled:
        return None, None
    return adapter_factory.build_torrent_client_adapter(row), row.id


def _add_to_client(session: Session, job: UploadJob, target: UploadTarget, torrent_file: str, save_path: str):
    adapter, client_id = _client(session, target)
    if adapter is None:
        target.error_message = "no_client"
        upload_jobs.log_event(session, job, "no_client", level="warning", target=target)
        return None
    visible = client_visible_path(session, job.disk, client_id, save_path)
    info_hash = adapter.add_torrent(torrent_file, save_path=visible, force_recheck=True)
    upload_jobs.log_event(session, job, "added_to_client", target=target, client=target.torrent_client.label)
    return info_hash


def _upload_pairs(job: UploadJob, torrent: torf.Torrent, root: str) -> list[tuple[str, str]]:
    """(file locale, destinazione) per ogni file del torrent. Vuoto se la
    sorgente è già nella cartella di seeding (o in quella per gli upload):
    il torrent ha il suo stesso nome, quindi seed sul posto."""
    if _inside(job.source_path, seeding_area(job)) or _inside(job.source_path, root):
        return []
    pairs = []
    for file in torrent.files:
        relative = os.path.join(*file.parts[1:]) if job.is_dir else ""
        source = os.path.join(job.source_path, relative) if relative else job.source_path
        pairs.append((source, os.path.join(root, *file.parts)))
    return pairs


def run_upload(session: Session, job: UploadJob, target: UploadTarget, ctx: dict) -> None:
    tracker = target.tracker
    if not tracker.announce_url:
        raise UploadJobError("tracker_missing_announce_url", tracker=tracker.label)
    profile = session.get(TrackerUploadProfile, tracker.id)
    if profile is None:
        raise UploadJobError("tracker_no_upload_profile", tracker=tracker.label)

    target.status = "preparing"
    session.commit()
    torrent: torf.Torrent = ctx["torrent"]
    torrent.trackers = [tracker.announce_url]
    torrent.source = tracker.label
    torrent_path = os.path.join(ctx["dir"], f"tracker-{tracker.id}.torrent")
    torrent.write(torrent_path, overwrite=True)
    target.torrent_path, target.info_hash = torrent_path, torrent.infohash
    overrides = ctx["overrides"]
    description = render_description(
        session, profile, job.mediainfo_text or "", ctx["screenshots"], notes=overrides.get("notes", "")
    )
    target.description_rendered = description
    resolutions = json.loads(profile.resolution_id_map_json or "{}")
    resolution_key = next((k for k, v in resolutions.items() if v == target.resolution_id), None)

    target.status = "uploading"
    session.commit()
    adapter = adapter_factory.build_tracker_adapter(tracker)
    fields = upload_fields(job, target, description, resolution_key)
    target.torrent_id_remote = adapter.upload_torrent(fields, torrent_path)
    upload_jobs.log_event(session, job, "uploaded", target=target, torrent=target.torrent_id_remote)
    session.commit()

    if overrides.get("no_seed"):
        upload_jobs.log_event(session, job, "not_seeded", target=target)
        return
    target.status = "seeding"
    session.commit()
    try:
        root = ctx["seed_root"]()
        pairs = _upload_pairs(job, torrent, root)
        link_files(pairs, root)
        save_path = root if pairs else os.path.dirname(job.source_path.rstrip(os.sep))
        _add_to_client(session, job, target, torrent_path, save_path)
    except Exception as exc:
        # L'upload è andato: mai ripeterlo per un problema del client.
        logger.warning("Upload %s su %s riuscito ma il seed no", job.id, tracker.label, exc_info=True)
        target.error_message = "seed_failed"
        upload_jobs.log_event(
            session, job, "seed_failed", level="error", target=target, error=getattr(exc, "code", None) or str(exc)
        )


def run_reseed(session: Session, job: UploadJob, target: UploadTarget, ctx: dict) -> None:
    dupes = json.loads(target.dupes_json or "[]")
    dupe = next((d for d in dupes if d["torrent_id_remote"] == target.reseed_torrent_id), None)
    if dupe is None or not dupe.get("download_link"):
        raise UploadJobError("upload_dupe_no_download_link")
    target.status = "preparing"
    session.commit()
    adapter = adapter_factory.build_tracker_adapter(target.tracker)
    content = adapter.download_torrent(dupe["download_link"])
    torrent_path = os.path.join(ctx["dir"], f"reseed-{target.tracker_id}.torrent")
    with open(torrent_path, "wb") as f:
        f.write(content)
    parsed = parse_torrent_info(content)
    target.torrent_path = torrent_path

    target.status = "seeding"
    session.commit()
    locate = build_locator(job, parsed)
    located = []
    for entry in parsed.files:
        local, _where = locate(entry)
        if local is None:
            if is_video(entry.path):
                raise UploadJobError("upload_reseed_missing_video", path=entry.path)
            continue  # un extra mancante lo scarica il client dopo il recheck
        located.append((local, entry.path))

    def destinations(base: str) -> list[tuple[str, str]]:
        name = os.path.join(base, parsed.name)
        return [(local, os.path.join(name, path) if parsed.is_multi_file else name) for local, path in located]

    # Sul posto se la sorgente, dentro la cartella di seeding, ha già il nome
    # e il layout del torrent del tracker; altrimenti hardlink.
    parent = os.path.dirname(job.source_path.rstrip(os.sep))
    in_place = _inside(job.source_path, seeding_area(job)) and all(
        os.path.exists(dst) and os.path.samefile(src, dst) for src, dst in destinations(parent)
    )
    if in_place:
        save_path = parent
    else:
        save_path = ctx["seed_root"]()
        link_files(destinations(save_path), save_path)
    target.info_hash = _add_to_client(session, job, target, torrent_path, save_path)
    upload_jobs.log_event(session, job, "reseeded", target=target, torrent=target.reseed_torrent_id)


class _Cancelled(Exception):
    pass


def handle(session: Session, job: UploadJob, worker) -> None:
    if not upload_jobs.transition(session, job, "queued", "running", queue_position=None):
        return
    upload_jobs.log_event(session, job, "execution_started")
    session.commit()
    targets = [t for t in job.targets if t.status == "approved"]
    overrides = json.loads(job.overrides_json or "{}")
    ctx: dict = {"dir": _job_dir(worker, job), "overrides": overrides, "screenshots": []}

    root_cache: list[str] = []

    def lazy_seed_root() -> str:
        if not root_cache:
            root_cache.append(seed_root(job))
        return root_cache[0]

    ctx["seed_root"] = lazy_seed_root

    try:
        if any(t.action == "upload" for t in targets):
            ctx["torrent"] = hash_pieces(session, job)
            # Per la barra degli step (ProgressStep): i passaggi conclusi restano segnati.
            upload_jobs.log_event(session, job, "torrent_created")
            session.commit()
            count = overrides.get("screenshot_count")
            if count is None:
                count = int(settings_repo.get_setting(session, "upload_screenshot_count") or "4")
            ctx["screenshots"] = take_screenshots(session, job, worker, count)
            job.screenshot_urls_json = json.dumps(ctx["screenshots"])
            upload_jobs.log_event(session, job, "screenshots_done", count=len(ctx["screenshots"]))
            session.commit()
    except _Cancelled:
        return
    except UploadJobError as exc:
        # Senza torrent o screenshot nessun upload può partire; i reseed sì.
        for target in targets:
            if target.action == "upload":
                target.status, target.error_message = "failed", exc.code
                upload_jobs.log_event(session, job, exc.code, level="error", target=target, **exc.params)
        session.commit()

    for target in targets:
        session.refresh(job)
        if job.status == "cancelled":
            return
        if target.status != "approved":
            continue
        _progress(session, job, f"tracker:{target.tracker.label}")
        try:
            if target.action == "upload":
                run_upload(session, job, target, ctx)
            else:
                run_reseed(session, job, target, ctx)
            target.status = "done"
        except Exception as exc:
            session.rollback()
            logger.warning("Upload %s: %s fallito su %s", job.id, target.action, target.tracker.label, exc_info=True)
            target.status = "failed"
            target.error_message = getattr(exc, "code", None) or str(exc)
            params = getattr(exc, "params", None) or {"error": str(exc)}
            upload_jobs.log_event(session, job, f"{target.action}_failed", level="error", target=target,
                                  error=target.error_message, **{k: v for k, v in params.items() if k != "error"})
        target.finished_at = datetime.now(UTC)
        session.commit()

    outcomes = [t.status for t in job.targets if t.action != "skip"]
    if all(s == "done" for s in outcomes):
        final = "done"
    elif all(s == "failed" for s in outcomes):
        final = "failed"
    else:
        final = "partial"
    if upload_jobs.transition(session, job, "running", final, stage=None, progress_done=None, progress_total=None):
        upload_jobs.log_event(session, job, f"job_{final}", level="info" if final == "done" else "warning")
        session.commit()
