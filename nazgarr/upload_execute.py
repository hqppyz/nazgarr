"""Esecuzione di un job di upload approvato (docs/SPEC.md §9 "Upload flow
v2"), nel worker "heavy", un job alla volta nell'ordine della coda.

L'approvazione al secondo punto è la conferma umana obbligatoria: da qui si
va fino in fondo senza chiedere altro. Una volta per job:
- gli hash dei piece (torf), riusati per il .torrent di ogni tracker: stesso
  contenuto, announce e campo source diversi, quindi info hash diversi;
- screenshot e upload sull'image host, mediainfo (già letto nell'analisi).

Poi per ogni tracker, in ordine, la sua azione:
- upload: .torrent del tracker, descrizione dal suo template, invio, e il
  torrent aggiunto al client del tracker senza il suo recheck, dopo aver
  controllato che i file siano al loro posto (vedi _add_to_client);
- reseed: il .torrent già sul tracker, i file sistemati con i nomi che si
  aspetta, e l'aggiunta al client con recheck forzato.

Dove seedano: hardlink nella cartella per gli upload del disco
(disk.effective_upload_rel_path: upload_rel_path, o torrents_rel_path),
decisione dell'utente del 2026-09-30. Se la sorgente è già lì dentro con lo
stesso layout del torrent, si fa seed sul posto. Stesso filesystem o errore
esplicito, come nel reseeding. Un tracker che fallisce non ferma gli altri.
"""

import contextlib
import io
import json
import logging
import os
import re
from datetime import UTC, datetime

import torf
from sqlalchemy.orm import Session

from nazgarr import (
    adapter_factory,
    client_labels,
    mediainfo_util,
    screenshots,
    settings_repo,
    upload_file_names,
    upload_jobs,
    upload_watch,
)
from nazgarr.adapter_factory import ImageHostConfigError
from nazgarr.adapters.image_host.base import ImageHostError
from nazgarr.adapters.tracker.base import UploadFields
from nazgarr.executor import client_visible_path
from nazgarr.file_types import is_video
from nazgarr.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.models import TorrentClient, TrackerUploadProfile, UploadJob, UploadTarget
from nazgarr.torrent_file import parse_torrent_info
from nazgarr.upload import render_description
from nazgarr.upload_jobs import UploadJobError
from nazgarr.upload_verify import build_locator

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
    Tutto si controlla prima di creare il primo: destinazioni dentro la
    cartella di seed (sul percorso già risolto, niente symlink piazzati nel
    mezzo), sorgenti che sono file veri (non symlink) sullo stesso disco. Se
    un hardlink fallisce a metà, quelli appena creati si tolgono.
    Restituisce gli hardlink creati."""
    root_dev = os.stat(root).st_dev
    planned: list[tuple[str, str]] = []
    for source, target in pairs:
        if os.path.islink(source) or not os.path.isfile(source):
            raise UploadJobError("upload_source_not_a_file", path=source)
        if os.stat(source).st_dev != root_dev:
            raise UploadJobError("upload_cross_device", path=source)
        resolved = resolve_scoped(root, os.path.relpath(target, root))  # mai fuori dalla cartella di seed
        if os.path.lexists(resolved):
            if os.path.islink(resolved) or not os.path.samefile(source, resolved):
                raise UploadJobError("upload_seed_path_exists", path=target)
            continue
        planned.append((source, resolved))
    created: list[str] = []
    try:
        for source, target in planned:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.link(source, target, follow_symlinks=False)
            created.append(target)
    except OSError:
        for path in created:
            with contextlib.suppress(OSError):
                os.unlink(path)
        raise
    return created


# --- una volta per job --------------------------------------------------------


def _job_dir(worker, job: UploadJob) -> str:
    path = os.path.join(worker.data_dir, "uploads", str(job.id))
    os.makedirs(path, exist_ok=True)
    return path


def _progress(session: Session, job: UploadJob, stage: str, done: int | None = None, total: int | None = None):
    job.stage, job.progress_done, job.progress_total = stage, done, total
    session.commit()


def prepare_content(session: Session, job: UploadJob, ctx: dict) -> str:
    """Il percorso da cui creare il torrent. Con i nomi della sorgente
    (upload_file_names "original") è la sorgente stessa; con nomi nuovi
    (dal torrent in hardlink, o generati) si creano prima gli hardlink con
    quei nomi nella cartella di seed, e il torrent nasce da lì: quello
    pubblicato e quello in seed sono per forza gli stessi file."""
    plan = upload_file_names.plan(session, job)
    upload_jobs.log_event(session, job, "file_names", mode=plan.mode, name=plan.content_name)
    session.commit()
    if not plan.renamed:
        refresh_mediainfo(session, job, plan, None)
        return job.source_path
    root = ctx["seed_root"]()
    pairs = [(source, os.path.join(root, *target.split("/"))) for source, target in plan.files]
    ctx["created_links"] = link_files(pairs, root)
    ctx["prelinked"] = True
    refresh_mediainfo(session, job, plan, root)
    return os.path.join(root, *plan.content_name.split("/"))


_COMPLETE_NAME = re.compile(r"^(Complete name\s*:\s*).*$", re.MULTILINE)


def refresh_mediainfo(session: Session, job: UploadJob, plan, root: str | None) -> None:
    """Il MediaInfo per il tracker, dal file del torrent: rinominare cambia
    solo "Complete name" (i flussi sono gli stessi byte), che ora è il
    percorso dentro il torrent, non quello locale (le tue cartelle non escono
    verso il tracker). Rigenerato sul nome nuovo; se mediainfo non riesce, il
    testo dell'analisi con la sola riga corretta."""
    main_video = (json.loads(job.layout_json or "{}").get("main_video")) or job.source_path
    target = next((t for source, t in plan.files if source == main_video), None)
    if target is None:
        return
    text = None
    if root is not None:
        text = mediainfo_util.extract_full_text(os.path.join(root, *target.split("/")))
    text = text or job.mediainfo_text
    if not text:
        return
    job.mediainfo_text = _COMPLETE_NAME.sub(lambda m: m.group(1) + target, text, count=1)
    session.commit()


def hash_pieces(session: Session, job: UploadJob, path: str | None = None) -> torf.Torrent:
    torrent = torf.Torrent(path=path or job.source_path, private=True, exclude_globs=EXCLUDE_GLOBS)
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


def files_in_place(torrent: torf.Torrent, save_path: str) -> bool:
    """Ogni file del torrent è dove il client lo cercherà (save_path più il
    suo percorso nel torrent), con la sua dimensione esatta."""
    for file in torrent.files:
        path = os.path.join(save_path, *file.parts)
        if not os.path.isfile(path) or os.path.getsize(path) != file.size:
            return False
    return True


def _add_to_client(
    session: Session, job: UploadJob, target: UploadTarget, torrent_file: str, save_path: str,
    torrent: torf.Torrent | None = None,
):
    """Senza il recheck del client (decisione dell'utente, 2026-09-30): il
    torrent l'ha appena creato Nazgarr leggendo ogni piece di questi file (o
    dei loro hardlink, gli stessi byte), rileggerli tutti non verifica niente
    di nuovo. Quello che il recheck verificherebbe davvero è che il client li
    trovi: prima si controlla che ogni file sia nel percorso di seed con la
    sua dimensione, dopo che il client usi proprio quel percorso. Se una delle
    due non torna, il recheck normale, così un percorso sbagliato (mount
    diversi fra i container) risulta in file mancanti invece di un torrent
    annunciato completo senza i dati. Un reseed (torrent=None, il .torrent è
    del tracker) ha sempre il recheck."""
    adapter, client_id = _client(session, target)
    if adapter is None:
        target.error_message = "no_client"
        upload_jobs.log_event(session, job, "no_client", level="warning", target=target)
        return None
    visible = client_visible_path(session, job.disk, client_id, save_path)
    skip = torrent is not None and files_in_place(torrent, save_path)
    info_hash = adapter.add_torrent(
        torrent_file, save_path=visible, force_recheck=True, skip_check_verified=skip,
        **client_labels.add_kwargs(target.client_category, target.client_tags),
    )
    client = target.torrent_client.label
    if skip:
        info = adapter.get_torrent_info(info_hash)
        seen = os.path.normpath(info.save_path) if info is not None and info.save_path else None
        if seen != os.path.normpath(visible):
            adapter.recheck(info_hash)
            upload_jobs.log_event(session, job, "recheck_after_path_mismatch", level="warning", target=target,
                                  client=client, expected=visible, seen=seen)
            skip = False
    elif torrent is not None:
        upload_jobs.log_event(session, job, "recheck_files_not_in_place", level="warning", target=target,
                              path=save_path)
    # Due codici, due messaggi: con il recheck del client o senza.
    upload_jobs.log_event(session, job, "added_to_client_verified" if skip else "added_to_client", target=target,
                          client=client)
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


def _tracker_copy(adapter, uploaded, torrent: torf.Torrent, job_dir: str, tracker_id: int) -> tuple[str, bool]:
    """Il .torrent come l'ha salvato il tracker (UploadedTorrent: il suo info
    hash è quello che il tracker conosce), e se ha gli stessi piece e gli
    stessi file di quello creato da Nazgarr."""
    if not uploaded.download_link:
        raise UploadJobError("upload_tracker_torrent_unavailable")
    try:
        content = adapter.download_torrent(uploaded.download_link)
        theirs = torf.Torrent.read_stream(io.BytesIO(content))
    except Exception as exc:
        raise UploadJobError("upload_tracker_torrent_unavailable", error=str(exc)) from exc
    path = os.path.join(job_dir, f"tracker-{tracker_id}-seed.torrent")
    with open(path, "wb") as f:
        f.write(content)
    mine_info, their_info = torrent.metainfo["info"], theirs.metainfo["info"]
    keys = ("pieces", "piece length", "name", "files", "length")
    same = all(mine_info.get(key) == their_info.get(key) for key in keys)
    return path, same


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
    uploaded = adapter.upload_torrent(fields, torrent_path)
    target.torrent_id_remote = uploaded.torrent_id_remote
    upload_jobs.log_event(session, job, "uploaded", target=target, torrent=target.torrent_id_remote)
    session.commit()

    if overrides.get("no_seed"):
        upload_jobs.log_event(session, job, "not_seeded", target=target)
        return
    target.status = "seeding"
    session.commit()
    try:
        root = ctx["seed_root"]()
        if ctx.get("prelinked"):  # già in seed con i nomi del torrent (prepare_content)
            save_path = root
        else:
            pairs = _upload_pairs(job, torrent, root)
            link_files(pairs, root)
            save_path = root if pairs else os.path.dirname(job.source_path.rstrip(os.sep))
        seed_path, same_content = _tracker_copy(adapter, uploaded, torrent, ctx["dir"], tracker.id)
        target.torrent_path = seed_path
        target.info_hash = torf.Torrent.read(seed_path).infohash
        session.commit()
        # Gli stessi piece di quelli appena calcolati: niente recheck (vedi
        # _add_to_client); se il tracker ha cambiato il contenuto, recheck.
        _add_to_client(session, job, target, seed_path, save_path, torrent if same_content else None)
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


def _cleanup_unused_links(session: Session, job: UploadJob, ctx: dict, overrides: dict) -> None:
    """Gli hardlink creati per dare al torrent i suoi nomi (prepare_content)
    si tolgono se non seedano niente: "non mettere in seed", o nessun
    upload riuscito. Solo quelli creati da questo job, e le cartelle che
    restano vuote."""
    created = ctx.get("created_links") or []
    uploaded = any(t.action == "upload" and t.status == "done" for t in job.targets)
    if not created or (uploaded and not overrides.get("no_seed")):
        return
    root = os.path.realpath(ctx["seed_root"]())
    for path in created:
        with contextlib.suppress(OSError):
            os.unlink(path)
        parent = os.path.dirname(path)
        while os.path.realpath(parent).startswith(root + os.sep):
            try:
                os.rmdir(parent)  # solo se vuota
            except OSError:
                break
            parent = os.path.dirname(parent)
    upload_jobs.log_event(session, job, "file_links_removed", count=len(created))
    session.commit()


def _source_files(path: str) -> list[str]:
    if not os.path.isdir(path):
        return [path]
    return [os.path.join(folder, name) for folder, _dirs, files in os.walk(path, followlinks=False) for name in files]


def _clear_watch_source(session: Session, job: UploadJob, overrides: dict) -> None:
    """La cartella osservata è solo di passaggio (decisione dell'utente,
    2026-10-02): a upload fatto la release resta solo nella cartella delle
    release, dove seeda con i nomi del torrent (gli hardlink di questo job),
    e l'originale nella cartella osservata si toglie. Un "move" fatto con un
    hardlink e poi la rimozione, mai prima: se qualcosa va storto la release
    resta dov'era.

    Solo se almeno un tracker è andato, se si mette in seed, se la sorgente è
    davvero dentro la cartella osservata e se ogni suo file ha un altro link
    (la copia che seeda): se no non si tocca niente."""
    if job.origin != "watch" or overrides.get("no_seed") or job.disk is None:
        return
    if not any(t.status == "done" and t.action != "skip" for t in job.targets):
        return
    watch = upload_watch.watch_root(job.disk)
    source = os.path.realpath(job.source_path)
    if watch is None or not source.startswith(os.path.realpath(watch) + os.sep):
        return
    files = _source_files(source)
    try:
        unlinked = [f for f in files if os.path.islink(f) or os.stat(f, follow_symlinks=False).st_nlink < 2]
    except OSError:
        unlinked = files
    if unlinked:
        upload_jobs.log_event(session, job, "watch_source_kept", level="warning", count=len(unlinked))
        session.commit()
        return
    for path in files:
        with contextlib.suppress(OSError):
            os.unlink(path)
    if os.path.isdir(source):
        for folder, _dirs, _files in sorted(os.walk(source), key=lambda entry: -len(entry[0])):
            with contextlib.suppress(OSError):
                os.rmdir(folder)  # solo se vuota
    upload_jobs.log_event(session, job, "watch_source_moved", count=len(files))
    session.commit()


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
            ctx["torrent"] = hash_pieces(session, job, prepare_content(session, job, ctx))
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

    _cleanup_unused_links(session, job, ctx, overrides)
    _clear_watch_source(session, job, overrides)
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
