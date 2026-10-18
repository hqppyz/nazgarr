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
(disk.effective_upload_rel_path: upload_rel_path, o la prima cartella di seeding),
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
import stat
import time
from datetime import UTC, datetime

import torf
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from nazgarr.adapters.image_host.base import ImageHostError
from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError
from nazgarr.adapters.tracker.base import UploadFields
from nazgarr.core import settings_registry
from nazgarr.core.errors import CodedError
from nazgarr.core.file_types import is_video
from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.core.models import TorrentClient, TrackerUploadProfile, UploadJob, UploadTarget
from nazgarr.core.version import CREATED_BY
from nazgarr.integrations import adapter_factory
from nazgarr.integrations.adapter_factory import ImageHostConfigError
from nazgarr.library import disk_folders, hardlinks
from nazgarr.library import mediainfo as mediainfo_util
from nazgarr.reseed.executor import client_visible_path
from nazgarr.torrents import client_labels
from nazgarr.torrents.metainfo import compute_info_hash, parse_torrent_info
from nazgarr.upload import file_names as upload_file_names
from nazgarr.upload import inventory as upload_inventory
from nazgarr.upload import jobs as upload_jobs
from nazgarr.upload import pack as upload_pack
from nazgarr.upload import screenshots
from nazgarr.upload import watch as upload_watch
from nazgarr.upload.decision import MAX_SCREENSHOTS
from nazgarr.upload.description import render_description
from nazgarr.upload.jobs import UploadJobError
from nazgarr.upload.verify import build_locator

logger = logging.getLogger(__name__)

# File che non finiscono mai nel torrent di un upload.
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


def seeding_area(job: UploadJob) -> list[str]:
    """Le cartelle di seeding del disco (nazgarr/library/disk_folders.py)."""
    if job.disk is None:
        return []
    return disk_folders.absolute(job.disk, "seeding")


def _inside(path: str, folder: str | list[str] | None) -> bool:
    if folder is None:
        return False
    if isinstance(folder, list):
        return any(_inside(path, one) for one in folder)
    real, base = os.path.realpath(path), os.path.realpath(folder)
    return real.startswith(base + os.sep)


def link_files(pairs: list[tuple[str, str]], root: str) -> list[str]:
    """Crea gli hardlink (sorgente, destinazione); una destinazione che è già
    lo stesso file (un tentativo precedente) va bene, un file diverso no.
    Tutto si controlla prima di creare il primo (hardlinks.check_link): dentro
    la cartella di seed, sorgenti che sono file veri sullo stesso disco. Se
    un hardlink fallisce a metà, quelli appena creati si tolgono.
    Restituisce gli hardlink creati."""
    codes = {"source_not_a_file": "upload_source_not_a_file", "cross_device": "upload_cross_device",
             "target_exists": "upload_seed_path_exists"}
    planned: list[tuple[str, str]] = []
    for source, target in pairs:
        try:
            resolved = hardlinks.check_link(source, target, root)
        except hardlinks.LinkProblem as problem:
            raise UploadJobError(codes[problem.code], path=problem.path) from problem
        if resolved is not None:
            planned.append((source, resolved))
    return hardlinks.create_links(planned)


# --- una volta per job --------------------------------------------------------


def _job_dir(worker, job: UploadJob) -> str:
    path = upload_jobs.job_folder(worker.data_dir, job.id)
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
    pubblicato e quello in seed sono per forza gli stessi file.

    Un file solo tolto dalla sua cartella (plan.single_file) va negli
    hardlink anche con i nomi originali: nella cartella di seed, dentro la
    sua cartella se resta (plan.folder). Se la sorgente è già nella cartella
    di seeding, seeda sul posto, dentro la sua cartella. ctx["save_path"] è
    dove il client lo cercherà."""
    plan = upload_file_names.plan(session, job)
    upload_jobs.log_event(session, job, "file_names", mode=plan.mode, name=plan.content_name,
                          **({"single_file": True, "folder": plan.folder} if plan.single_file else {}))
    session.commit()
    # Un pack di file scelti a mano non ha una cartella sua: sempre hardlink.
    # Dalla cartella osservata la release se ne va anche con i nomi originali
    # (decisione dell'utente, 2026-10-05): hardlink con quei nomi nella
    # cartella di seed, prima di pubblicare, come per i nomi nuovi.
    if not plan.renamed and not plan.single_file and not upload_pack.is_pack(job) and job.origin != "watch":
        refresh_mediainfo(session, job, plan, None)
        return job.source_path
    if not plan.renamed and _seeds_in_place(job, ctx):
        source = plan.files[0][0]
        ctx["save_path"] = os.path.dirname(source)
        refresh_mediainfo(session, job, plan, None)
        return source
    root = ctx["seed_root"]()
    base = os.path.join(root, *plan.folder.split("/")) if plan.folder else root
    pairs = [(source, os.path.join(base, *target.split("/"))) for source, target in plan.files]
    ctx["created_links"] = link_files(pairs, root)
    ctx["save_path"] = base
    # Nel torrent solo questi: la cartella può avere già altro (hash_pieces).
    ctx["planned"] = [target for _source, target in pairs]
    refresh_mediainfo(session, job, plan, base)
    return os.path.join(base, *plan.content_name.split("/"))


def _seeds_in_place(job: UploadJob, ctx: dict) -> bool:
    """La sorgente è già nella cartella di seeding (o in quella per gli
    upload). Mai per la cartella osservata: da lì la release se ne va."""
    if job.origin == "watch" or upload_pack.is_pack(job):
        return False
    if _inside(job.source_path, seeding_area(job)):
        return True
    try:
        return _inside(job.source_path, ctx["seed_root"]())
    except UploadJobError:
        return False


_COMPLETE_NAME = re.compile(r"^(Complete name\s*:\s*).*$", re.MULTILINE)


def refresh_mediainfo(session: Session, job: UploadJob, plan, root: str | None) -> None:
    """Il MediaInfo per il tracker, dal file del torrent: rinominare cambia
    solo "Complete name" (i flussi sono gli stessi byte), che ora è il
    percorso dentro il torrent, non quello locale (le tue cartelle non escono
    verso il tracker). Il testo dell'analisi con la sola riga corretta, senza
    rileggere il file; letto dal file solo se l'analisi non l'ha."""
    target = upload_file_names.main_video_target(job, plan)
    if target is None:
        return
    text = job.mediainfo_text
    if not text and root is not None:
        text = mediainfo_util.extract_full_text(os.path.join(root, *target.split("/")))
    if not text:
        return
    job.mediainfo_text = _COMPLETE_NAME.sub(lambda m: m.group(1) + target, text, count=1)
    session.commit()


# Thread di hashing di torf: di default uno per core dell'host (in Docker
# tutti, anche con --cpus), e ognuno tiene in memoria il suo piece da 16 MiB.
# Quattro leggono già più veloce di qualunque disco (audit 2026-10-18).
HASH_THREADS = 4


def _only_planned(session: Session, job: UploadJob, torrent: torf.Torrent, root: str, planned: list[str]) -> None:
    """Un torrent fatto dagli hardlink appena creati contiene esattamente
    quei file (audit 2026-10-18): la cartella con quel nome nella cartella di
    seed può avere già altro (la release originale con la promo di un altro
    tracker, un upload precedente con un sottotitolo tolto da allora), che
    finiva pubblicato e in seed senza che la decisione lo mostrasse. Quello
    in più resta fuori, e il registro lo dice."""
    parent = os.path.dirname(root.rstrip(os.sep))
    expected = {os.path.relpath(path, parent).replace(os.sep, "/") for path in planned}
    extras = sorted({"/".join(f.parts) for f in torrent.files} - expected)
    if extras:
        torrent.exclude_regexs = [*torrent.exclude_regexs, *("^" + re.escape(extra) + "$" for extra in extras)]
        upload_jobs.log_event(session, job, "upload_extra_files_left_out", level="warning", count=len(extras),
                              files=extras[:10])
        session.commit()
    missing = sorted(expected - {"/".join(f.parts) for f in torrent.files})
    if missing:
        raise UploadJobError("upload_planned_files_missing", files=", ".join(missing[:5]))


def hash_pieces(session: Session, job: UploadJob, path: str | None = None,
                planned: list[str] | None = None) -> torf.Torrent:
    """planned: i file (assoluti) degli hardlink appena creati da
    prepare_content, gli unici che entrano nel torrent."""
    root = path or job.source_path
    if planned is None and (os.path.islink(root.rstrip(os.sep)) or upload_jobs.has_symlinks(root)):
        # La sorgente stessa: torf segue i link simbolici, e il file a cui
        # puntano finirebbe nel torrent pubblicato. Controllato alla
        # creazione del job, e di nuovo qui: fra le due possono passare giorni.
        raise UploadJobError("upload_source_has_symlinks", path=job.relative_path)
    # Fuori i file che la regola di analisi e nomi esclude
    # (nazgarr/upload/inventory.py), uno per uno: mai dei glob sul percorso,
    # che toglievano un film con "Sample" nel titolo. Per nome esatto nel
    # torrent (cartella/percorso), così la struttura resta quella della
    # cartella anche se rimane un file solo.
    name = os.path.basename(root.rstrip(os.sep))
    excluded = [
        "^" + re.escape(f"{name}/{f.relative}") + "$"
        for f in (upload_inventory.walk(root) if os.path.isdir(root) else [])
        if not upload_inventory.in_torrent(f.relative, f.size)
    ]
    torrent = torf.Torrent(path=root, private=True, exclude_regexs=excluded, created_by=CREATED_BY)
    if planned is not None:
        _only_planned(session, job, torrent, root, planned)
    if not torrent.files:
        raise UploadJobError("no_video_files")

    def callback(_torrent, _path, done, total):
        _progress(session, job, "hashing", done, total)
        session.refresh(job)
        # Annullato a metà: torf si ferma se il callback restituisce qualcosa.
        return True if job.status == "cancelled" else None

    _progress(session, job, "hashing", 0, None)
    torrent.generate(threads=min(HASH_THREADS, os.cpu_count() or 1), callback=callback,
                     interval=PROGRESS_EVERY_SECONDS)
    session.refresh(job)
    if job.status == "cancelled":
        raise _Cancelled()
    return torrent


def take_screenshots(session: Session, job: UploadJob, worker, count: int) -> list[str]:
    if count <= 0:
        return []
    layout = json.loads(job.layout_json or "{}")
    main_video = layout.get("main_video") or job.source_path
    tonemap = settings_registry.get_bool(session, "upload_tonemap_hdr")
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


def _client_row(session: Session, target: UploadTarget) -> TorrentClient | None:
    if target.torrent_client_id is None:
        return None
    row = session.get(TorrentClient, target.torrent_client_id)
    return row if row is not None and row.enabled else None


def _client(session: Session, target: UploadTarget):
    """(adapter, id del client) da chiudere dopo l'uso, o (None, None)."""
    row = _client_row(session, target)
    if row is None:
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
    try:
        visible = client_visible_path(session, job.disk, client_id, save_path)
        # Transmission e rTorrent non sanno aggiungere un torrent senza
        # ricontrollarlo: lì il recheck c'è sempre.
        can_skip = getattr(adapter, "can_skip_recheck", True)
        skip = torrent is not None and can_skip and files_in_place(torrent, save_path)
        client = target.torrent_client.label
        # L'info hash di questi byte (audit 2026-10-18): senza, qBittorrent e
        # qui prendevano per il nostro un torrent qualunque comparso nel
        # frattempo (un *arr, cross-seed), e il controllo del percorso dopo
        # un'aggiunta senza recheck guardava quello.
        expected = _info_hash_of(torrent_file)
        try:
            info_hash = adapter.add_torrent(
                torrent_file, save_path=visible, force_recheck=True, expected_info_hash=expected,
                skip_check_verified=skip, **client_labels.add_kwargs(target.client_category, target.client_tags),
            )
        except TorrentAlreadyInClientError:
            return _keep_existing(session, job, target, adapter, expected, visible, client)
        if skip:
            info = adapter.get_torrent_info(info_hash)
            seen = os.path.normpath(info.save_path) if info is not None and info.save_path else None
            if seen != os.path.normpath(visible):
                adapter.recheck(info_hash)
                upload_jobs.log_event(session, job, "recheck_after_path_mismatch", level="warning", target=target,
                                      client=client, expected=visible, seen=seen)
                skip = False
        elif torrent is not None and can_skip:
            upload_jobs.log_event(session, job, "recheck_files_not_in_place", level="warning", target=target,
                                  path=save_path)
        # Due codici, due messaggi: con il recheck del client o senza.
        upload_jobs.log_event(session, job, "added_to_client_verified" if skip else "added_to_client", target=target,
                              client=client)
        return info_hash
    finally:
        adapter_factory.close_adapter(adapter)


def _info_hash_of(torrent_file: str) -> str:
    """Dai byte esatti del file (lo span grezzo di "info"), come lo calcola il client."""
    with open(torrent_file, "rb") as f:
        return compute_info_hash(f.read())


def _keep_existing(session: Session, job: UploadJob, target: UploadTarget, adapter, info_hash: str, visible: str,
                   client: str) -> str:
    """Il client ha già questo torrent: un tentativo precedente arrivato fin
    lì (un errore dopo l'aggiunta, un riavvio), o aggiunto a mano. Si tiene
    quello, con un recheck, se usa proprio il percorso di seed; altrove no:
    niente si sposta da solo."""
    info = adapter.get_torrent_info(info_hash)
    seen = os.path.normpath(info.save_path) if info is not None and info.save_path else None
    if seen != os.path.normpath(visible):
        raise UploadJobError("upload_already_in_client", client=client, path=seen or "?")
    adapter.recheck(info_hash)
    adapter.start(info_hash)
    upload_jobs.log_event(session, job, "already_in_client", target=target, client=client)
    return info_hash


# Gli errori di un upload pubblicato ma non in seed, da cui si può riprovare.
SEED_RETRYABLE = ("seed_failed", "no_client")


def _seeds_from_source(job: UploadJob) -> bool:
    """La sorgente è già nella cartella di seeding (o in quella per gli
    upload) e il torrent ha i suoi nomi: lì seeda anche nel flusso normale
    (_upload_pairs, _seeds_in_place). Mai una cartella della libreria."""
    if job.origin == "watch" or upload_pack.is_pack(job):
        return False
    if _inside(job.source_path, seeding_area(job)):
        return True
    try:
        return _inside(job.source_path, seed_root(job))
    except UploadJobError:
        return False


def _seed_candidates(session: Session, job: UploadJob) -> list[str]:
    """Dove possono stare i file di un upload pubblicato: la cartella di
    seed (con la cartella dei nomi nuovi, se c'è), o accanto alla sorgente
    solo se lì seeda anche il flusso normale. Prima accanto alla sorgente
    sempre: un nuovo tentativo poteva puntare il client alla cartella della
    libreria (audit 2026-10-18), e un "rimuovi con i file" nel client
    cancellava i file della libreria."""
    candidates = []
    with contextlib.suppress(UploadJobError):
        root = seed_root(job)
        with contextlib.suppress(Exception):
            folder = upload_file_names.plan(session, job).folder
            if folder:
                candidates.append(os.path.join(root, *folder.split("/")))
        candidates.append(root)
    if _seeds_from_source(job):
        candidates.append(os.path.dirname(job.source_path.rstrip(os.sep)))
    return candidates


def _relink_for_seed(session: Session, job: UploadJob, torrent: torf.Torrent) -> str:
    """Nessun posto ha più i file del torrent (gli hardlink tolti, o la
    cartella di seed creata dopo l'errore): si rifanno nella cartella di
    seed come all'upload, con gli stessi nomi. Restituisce dove seeda."""
    root = seed_root(job)
    if not os.path.exists(job.source_path):
        raise UploadJobError("upload_seed_files_missing")
    try:
        plan = upload_file_names.plan(session, job)
    except Exception as exc:  # la sorgente cambiata da allora: i nomi non si rifanno
        raise UploadJobError("upload_seed_files_missing") from exc
    if plan.renamed or plan.single_file or upload_pack.is_pack(job) or job.origin == "watch":
        base = os.path.join(root, *plan.folder.split("/")) if plan.folder else root
        pairs = [(source, os.path.join(base, *target.split("/"))) for source, target in plan.files]
    else:
        base, pairs = root, _upload_pairs(job, torrent, root)
    if not pairs or any(not os.path.isfile(source) for source, _target in pairs):
        raise UploadJobError("upload_seed_files_missing")
    created = link_files(pairs, root)
    if not files_in_place(torrent, base):
        hardlinks.remove_links(created)
        raise UploadJobError("upload_seed_files_missing")
    if created:
        upload_jobs.log_event(session, job, "seed_files_linked", count=len(created))
    return base


def _tracker_torrent(session: Session, job: UploadJob, target: UploadTarget, data_dir: str | None) -> str:
    """Il .torrent come l'ha salvato il tracker: il suo info hash è quello
    che il tracker conosce (UNIT3D riscrive il campo source). La copia
    scaricata dopo l'upload; se manca (il seed si è fermato prima, o un
    riavvio), si riscarica dal tracker. Quello creato da Nazgarr solo se il
    tracker non sa ridarlo, e il registro lo dice."""
    job_dir = upload_jobs.job_folder(data_dir, job.id) if data_dir else (
        os.path.dirname(target.torrent_path) if target.torrent_path else None)
    seed_copy = os.path.join(job_dir, f"tracker-{target.tracker_id}-seed.torrent") if job_dir else None
    if seed_copy and os.path.isfile(seed_copy):
        target.torrent_path = seed_copy
        return seed_copy
    if seed_copy and target.torrent_id_remote:
        with adapter_factory.tracker(target.tracker) as adapter:
            detail = getattr(adapter, "get_torrent_detail", None)
            if callable(detail):
                try:
                    link = detail(target.torrent_id_remote).download_link
                    if not link:
                        raise ValueError("no download link")
                    content = adapter.download_torrent(link)
                    torf.Torrent.read_stream(io.BytesIO(content))
                except Exception as exc:
                    raise UploadJobError("upload_tracker_torrent_unavailable", error=str(exc)) from exc
                os.makedirs(job_dir, exist_ok=True)
                with open(seed_copy, "wb") as f:
                    f.write(content)
                target.torrent_path = seed_copy
                return seed_copy
    if not target.torrent_path or not os.path.isfile(target.torrent_path):
        raise UploadJobError("upload_tracker_torrent_unavailable")
    upload_jobs.log_event(session, job, "seed_retry_own_torrent", level="warning", target=target)
    return target.torrent_path


def retry_seed(session: Session, job: UploadJob, target: UploadTarget, data_dir: str | None = None) -> None:
    """Di nuovo solo l'aggiunta al client di un upload già pubblicato (il
    .torrent salvato dal tracker), mai l'upload. Con il recheck del client:
    i file potrebbero essere cambiati da quando Nazgarr li ha letti."""
    if target.action != "upload" or target.status != "done" or target.error_message not in SEED_RETRYABLE:
        raise UploadJobError("upload_seed_retry_unavailable")
    if _client_row(session, target) is None:
        # Senza client all'upload (no_client) o con quello di allora tolto:
        # quello che il tracker userebbe oggi.
        target.torrent_client_id = upload_jobs.default_client_id(session, target.tracker)
    torrent_path = _tracker_torrent(session, job, target, data_dir)
    try:
        torrent = torf.Torrent.read(torrent_path)
    except torf.TorfError as exc:
        raise UploadJobError("upload_tracker_torrent_unavailable", error=str(exc)) from exc
    save_path = next((p for p in _seed_candidates(session, job) if files_in_place(torrent, p)), None)
    if save_path is None:
        save_path = _relink_for_seed(session, job, torrent)
    try:
        info_hash = _add_to_client(session, job, target, torrent_path, save_path)
    except Exception as exc:
        session.rollback()
        upload_jobs.log_event(session, job, "seed_failed", level="error", target=target,
                              error=upload_jobs.error_text(exc))
        session.commit()
        raise UploadJobError("upload_seed_retry_failed", error=upload_jobs.error_text(exc)) from exc
    if info_hash is None:  # nessun client: _add_to_client l'ha già scritto
        session.commit()
        raise UploadJobError("upload_seed_retry_failed", error="no_client")
    target.info_hash = info_hash
    target.error_message = None
    upload_jobs.log_event(session, job, "seed_retried", target=target, client=target.torrent_client.label)
    session.commit()


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

    upload_jobs.set_target_status(target, upload_jobs.TargetStatus.PREPARING)
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

    upload_jobs.set_target_status(target, upload_jobs.TargetStatus.UPLOADING)
    session.commit()
    with adapter_factory.tracker(tracker) as adapter:
        fields = upload_fields(job, target, description, resolution_key)
        uploaded = adapter.upload_torrent(fields, torrent_path)
        # Da qui il torrent è pubblicato: qualunque cosa succeda dopo, mai
        # più un target 'failed' né un secondo invio (handle, reset_interrupted).
        ctx.setdefault("published", {})[target.id] = uploaded.torrent_id_remote
        _journal_published(ctx["dir"], target, uploaded.torrent_id_remote)
        _commit_published(session, job, target, uploaded.torrent_id_remote)

        if overrides.get("no_seed"):
            upload_jobs.log_event(session, job, "not_seeded", target=target)
            return
        upload_jobs.set_target_status(target, upload_jobs.TargetStatus.SEEDING)
        session.commit()
        try:
            root = ctx["seed_root"]()
            if ctx.get("save_path"):  # già in seed con i nomi del torrent (prepare_content)
                save_path = ctx["save_path"]
            else:
                pairs = _upload_pairs(job, torrent, root)
                link_files(pairs, root)
                save_path = root if pairs else os.path.dirname(job.source_path.rstrip(os.sep))
            _remember_seeded(ctx, target, [os.path.join(save_path, *file.parts) for file in torrent.files])
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
            session.rollback()  # un errore del DB lascerebbe la sessione inutilizzabile
            target.error_message = "seed_failed"
            upload_jobs.log_event(session, job, "seed_failed", level="error", target=target,
                                  error=upload_jobs.error_text(exc))


# Un torrent appena pubblicato si scrive nel DB anche se è occupato: altri
# tentativi prima di arrendersi (ognuno aspetta già il busy_timeout di SQLite).
PUBLISHED_COMMIT_ATTEMPTS = 3


def _journal_published(job_dir: str, target: UploadTarget, torrent_id_remote: str) -> None:
    """L'id del torrent pubblicato anche in un file del job, prima del DB:
    se il processo si ferma (o il DB non si scrive) proprio adesso, al
    riavvio reset_interrupted sa che il tracker l'ha ricevuto. Solo l'id,
    mai il link di download (ha la passkey)."""
    with contextlib.suppress(OSError):
        with open(upload_jobs.published_journal(job_dir, target.id), "w") as f:
            json.dump({"torrent_id_remote": torrent_id_remote}, f)


def _commit_published(session: Session, job: UploadJob, target: UploadTarget, torrent_id_remote: str) -> None:
    for attempt in range(PUBLISHED_COMMIT_ATTEMPTS):
        target.torrent_id_remote = torrent_id_remote
        upload_jobs.log_event(session, job, "uploaded", target=target, torrent=torrent_id_remote)
        try:
            session.commit()
            return
        except OperationalError:
            session.rollback()
            if attempt == PUBLISHED_COMMIT_ATTEMPTS - 1:
                raise
            logger.warning("Upload %s: torrent %s pubblicato, il DB non si scrive: si riprova", job.id,
                           torrent_id_remote, exc_info=True)
            time.sleep(1 + attempt)


def run_reseed(session: Session, job: UploadJob, target: UploadTarget, ctx: dict) -> None:
    dupes = json.loads(target.dupes_json or "[]")
    dupe = next((d for d in dupes if d["torrent_id_remote"] == target.reseed_torrent_id), None)
    if dupe is None or not dupe.get("download_link"):
        raise UploadJobError("upload_dupe_no_download_link")
    upload_jobs.set_target_status(target, upload_jobs.TargetStatus.PREPARING)
    session.commit()
    with adapter_factory.tracker(target.tracker) as adapter:
        content = adapter.download_torrent(dupe["download_link"])
    # Il controllo completo vale per il .torrent che ha letto: quello che si
    # aggiunge al client dev'essere lo stesso, non uno riscaricato e cambiato
    # nel frattempo sul tracker.
    verified = (dupe.get("verification") or {})
    if verified.get("status") != "passed" or verified.get("info_hash") != compute_info_hash(content):
        raise UploadJobError("upload_reseed_torrent_changed", tracker=target.tracker.label)
    torrent_path = os.path.join(ctx["dir"], f"reseed-{target.tracker_id}.torrent")
    with open(torrent_path, "wb") as f:
        f.write(content)
    parsed = parse_torrent_info(content)
    target.torrent_path = torrent_path

    upload_jobs.set_target_status(target, upload_jobs.TargetStatus.SEEDING)
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
    # Mai dalla cartella osservata: da lì la release se ne va.
    in_place = job.origin != "watch" and not upload_pack.is_pack(job) and _inside(
        job.source_path, seeding_area(job)) and all(
        os.path.exists(dst) and os.path.samefile(src, dst) for src, dst in destinations(parent)
    )
    if in_place:
        save_path = parent
    else:
        save_path = ctx["seed_root"]()
        link_files(destinations(save_path), save_path)
    _remember_seeded(ctx, target, [dst for _src, dst in destinations(save_path)])
    target.info_hash = _add_to_client(session, job, target, torrent_path, save_path)
    upload_jobs.log_event(session, job, "reseeded", target=target, torrent=target.reseed_torrent_id)


def _remember_seeded(ctx: dict, target: UploadTarget, paths: list[str]) -> None:
    """I file che un tracker di questo job mette in seed (dispositivo, inode,
    percorso), per target: contano solo quelli dei tracker andati a buon
    fine (_seeded_by_done). Dalla cartella osservata si toglie solo un file
    la cui copia è fra questi (_clear_watch_source), e la pulizia degli
    hardlink non tocca mai un file che seedano (_cleanup_unused_links)."""
    seeded = ctx.setdefault("seeded", {}).setdefault(target.id, {})
    for path in paths:
        with contextlib.suppress(OSError):
            st = os.stat(path)
            seeded[(st.st_dev, st.st_ino)] = os.path.realpath(path)


def _seeded_by_done(job: UploadJob, ctx: dict) -> dict[tuple[int, int], set[str]]:
    """(dispositivo, inode) -> i percorsi da cui seedano i tracker di questo
    job finiti 'done' in questa esecuzione. Un reseed fallito dopo aver
    registrato i suoi file non conta."""
    seeded = ctx.get("seeded") or {}
    out: dict[tuple[int, int], set[str]] = {}
    for target in job.targets:
        if target.status != "done":
            continue
        for key, path in (seeded.get(target.id) or {}).items():
            out.setdefault(key, set()).add(path)
    return out


class _Cancelled(Exception):
    pass


def _cleanup_unused_links(session: Session, job: UploadJob, ctx: dict, overrides: dict) -> None:
    """Gli hardlink creati per dare al torrent i suoi nomi (prepare_content)
    si tolgono se non seedano niente: "non mettere in seed", o nessun
    upload riuscito. Solo quelli creati da questo job, e le cartelle che
    restano vuote.

    Mai uno da cui seeda un altro tracker del job (audit 2026-10-18): un
    reseed con lo stesso nome e lo stesso layout riusa proprio quel link
    (hardlinks.check_link), e toglierlo lasciava il suo torrent senza dati;
    dalla cartella osservata poi se ne andava anche l'originale."""
    created = ctx.get("created_links") or []
    uploaded = any(t.action == "upload" and t.status == "done" for t in job.targets)
    if not created or (uploaded and not overrides.get("no_seed")):
        return
    keep = {path for paths in _seeded_by_done(job, ctx).values() for path in paths}
    unused = [path for path in created if os.path.realpath(path) not in keep]
    if not unused:
        return
    root = os.path.realpath(ctx["seed_root"]())
    for path in unused:
        with contextlib.suppress(OSError):
            os.unlink(path)
        parent = os.path.dirname(path)
        while os.path.realpath(parent).startswith(root + os.sep):
            try:
                os.rmdir(parent)  # solo se vuota
            except OSError:
                break
            parent = os.path.dirname(parent)
    upload_jobs.log_event(session, job, "file_links_removed", count=len(unused))
    session.commit()


def _source_files(path: str) -> list[str]:
    if not os.path.isdir(path):
        return [path]
    return [os.path.join(folder, name) for folder, _dirs, files in os.walk(path, followlinks=False) for name in files]


# File che i sistemi operativi lasciano nelle cartelle: mai di un utente.
_SYSTEM_JUNK = ("Thumbs.db", "desktop.ini", ".DS_Store")


def _is_system_junk(name: str) -> bool:
    return name in _SYSTEM_JUNK or name.startswith("._")


def _has_seeding_copy(path: str, st: os.stat_result, copies: set[str] | None) -> bool:
    """Una delle copie registrate esiste ancora adesso: file regolare, stesso
    dispositivo e inode, percorso diverso; e il file ha davvero un secondo
    link. Mai fidarsi del solo registro: un link tolto nel frattempo (la
    pulizia, l'utente) lascerebbe l'originale come unica copia."""
    if st.st_nlink < 2:
        return False
    real = os.path.realpath(path)
    for copy in copies or ():
        try:
            cst = os.stat(copy, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(cst.st_mode) and (cst.st_dev, cst.st_ino) == (st.st_dev, st.st_ino) \
                and os.path.realpath(copy) != real:
            return True
    return False


def _clear_watch_source(session: Session, job: UploadJob, overrides: dict, ctx: dict | None = None) -> None:
    """La cartella osservata è solo di passaggio (decisione dell'utente,
    2026-10-02): a upload fatto la release resta solo nella cartella delle
    release, dove seeda con i nomi del torrent (gli hardlink di questo job),
    e dalla cartella osservata si toglie. Un "move" fatto con un hardlink e
    poi la rimozione, mai prima: se qualcosa va storto la release resta lì.

    Si tolgono solo i file la cui copia in seed l'ha messa questo job (stesso
    inode, altro percorso: _remember_seeded), e i file di sistema
    (Thumbs.db, .DS_Store...). Prima bastava un secondo link qualunque: un
    file già collegato altrove (es. dalla cartella dei download) si
    cancellava anche se a seedare era proprio lui. Quello che il torrent non
    ha preso (es. un sample) resta, elencato nel registro del job, e le
    cartelle vuote spariscono. Solo se almeno un tracker è andato, se si
    mette in seed e se la sorgente è davvero dentro la cartella osservata.

    La copia si ricontrolla subito prima di togliere l'originale (audit
    2026-10-18): deve esistere ancora, essere un file vero con lo stesso
    inode in un altro percorso, e seedare per un tracker andato a buon fine;
    se no l'originale resta."""
    if job.origin != "watch" or overrides.get("no_seed") or job.disk is None:
        return
    if not any(t.status == "done" and t.action != "skip" for t in job.targets):
        return
    watch = upload_watch.watch_root(job.disk)
    source = os.path.realpath(job.source_path)
    if watch is None or not source.startswith(os.path.realpath(watch) + os.sep):
        return
    seeded = _seeded_by_done(job, ctx or {})
    moved, kept = [], []
    for path in _source_files(source):
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            continue
        linked = not os.path.islink(path) and _has_seeding_copy(path, st, seeded.get((st.st_dev, st.st_ino)))
        if linked or _is_system_junk(os.path.basename(path)):
            with contextlib.suppress(OSError):
                os.unlink(path)
            if linked:
                moved.append(path)
        else:
            kept.append(os.path.relpath(path, os.path.dirname(source)))
    if os.path.isdir(source):
        for folder, _dirs, _files in sorted(os.walk(source), key=lambda entry: -len(entry[0])):
            with contextlib.suppress(OSError):
                os.rmdir(folder)  # solo se vuota
    if moved:
        upload_jobs.log_event(session, job, "watch_source_moved", count=len(moved))
    if kept:
        upload_jobs.log_event(session, job, "watch_source_leftovers", level="warning", count=len(kept),
                              files=kept[:10])
    session.commit()
    if job.split_from_id is not None:
        _remove_split_folder(session, job, watch)


def _remove_split_folder(session: Session, job: UploadJob, watch: str) -> None:
    """Un episodio di una stagione divisa, o una stagione di una cartella con
    più stagioni (nazgarr/upload/split.py): quando nella sua cartella della
    cartella osservata non resta più nessun episodio da caricare, la
    cartella si toglie con quello che resta (nfo, sample...), decisione
    dell'utente del 2026-10-09. Un video ancora lì (l'upload di un
    altro episodio non è finito, o è stato annullato) o un file ancora in
    scrittura la lasciano dov'è.

    Si tolgono solo i file appena controllati, poi le cartelle rimaste vuote
    (audit 2026-10-18): prima un rmtree, che cancellava anche un file
    arrivato nel frattempo e, se un file non si poteva togliere, faceva
    fallire un upload già pubblicato e in seed. Quello che resta si dice nel
    registro."""
    root = os.path.realpath(watch)
    relative = os.path.relpath(os.path.realpath(job.source_path), root)
    parts = relative.split(os.sep)
    if parts[0] in ("", ".", "..") or (len(parts) < 2 and not job.is_dir):
        return  # un file direttamente nella cartella osservata: nessuna cartella sua
    folder = os.path.join(root, parts[0])
    if os.path.islink(folder) or not os.path.isdir(folder):
        return
    left, paths = [], []
    for directory, _dirs, files in os.walk(folder, followlinks=False):
        for name in files:
            path = os.path.join(directory, name)
            inside = os.path.relpath(path, folder)
            try:
                size = os.lstat(path).st_size
            except OSError:
                continue
            if upload_watch.is_partial(name) or (is_video(name) and upload_inventory.in_torrent(inside, size)):
                return
            left.append(inside)
            paths.append(path)
    errors = []
    for path in paths:
        try:
            os.unlink(path)
        except OSError as exc:
            errors.append(str(exc))
    for directory, _dirs, _files in sorted(os.walk(folder, followlinks=False), key=lambda entry: -len(entry[0])):
        with contextlib.suppress(OSError):
            os.rmdir(directory)  # solo se vuota
    if os.path.lexists(folder):
        remaining = sorted(os.path.relpath(os.path.join(d, n), folder)
                           for d, dirs, files in os.walk(folder, followlinks=False) for n in (*files, *dirs))
        upload_jobs.log_event(session, job, "watch_folder_remove_failed", level="warning", folder=parts[0],
                              count=len(remaining), files=remaining[:10], error=errors[0] if errors else None)
    else:
        upload_jobs.log_event(session, job, "watch_folder_removed", folder=parts[0], count=len(left),
                              files=left[:10])
    session.commit()


def _recheck_dupes(session: Session, job: UploadJob, targets: list[UploadTarget]) -> None:
    """Un upload programmato parte ore o giorni dopo la decisione: prima di
    tutto il dupe check di ogni tracker si rifà, e un torrent comparso nel
    frattempo (identico, o nello stesso slot) ferma l'upload su quel tracker.
    Quelli che c'erano già alla decisione li ha visti l'utente. Un reseed no:
    il torrent è già quello del tracker. Se il tracker non risponde si va
    avanti: l'invio fallirebbe comunque, e il registro lo dice.

    Lo stesso per un nuovo tentativo (upload_jobs.retry_failed): anche il
    nostro torrent di un invio interrotto ferma quel tracker. Sempre i
    risultati di adesso, non quelli tenuti in cache dalla ricerca
    dell'analisi (10 minuti)."""
    from nazgarr.upload import analysis as upload_analysis
    from nazgarr.upload import dupes as upload_dupes

    uploads = [t for t in targets if t.action == "upload" and t.status == "approved"]
    if not uploads:
        return
    try:
        files = upload_analysis.source_files(job)
    except OSError:
        return  # se ne accorge la preparazione, con il suo errore
    summary = upload_analysis.summary_of(job, files, json.loads(job.analysis_json or "{}"))
    for target in uploads:
        known = {d.get("torrent_id_remote") for d in json.loads(target.dupes_json or "[]")}
        try:
            with adapter_factory.tracker(target.tracker) as adapter:
                _forget_search(adapter, job.tmdb_id)
                results, _suggested = upload_dupes.check(adapter.search_by_tmdb(job.tmdb_id), summary)
        except Exception as exc:
            logger.warning("Upload %s: dupe check prima dell'invio fallito su %s", job.id, target.tracker.label,
                           exc_info=True)
            upload_jobs.log_event(session, job, "dupe_recheck_failed", level="warning", target=target, error=str(exc))
            continue
        new = [r for r in results if r["verdict"] in ("identical", "same_slot") and r["torrent_id_remote"] not in known]
        if new:
            upload_jobs.set_target_status(target, upload_jobs.TargetStatus.FAILED)
            target.error_message = "upload_dupe_appeared"
            target.finished_at = datetime.now(UTC)
            upload_jobs.log_event(session, job, "upload_dupe_appeared", level="error", target=target,
                                  names=[r["name"] for r in new[:3]])
    session.commit()


def _forget_search(adapter, tmdb_id: int | None) -> None:
    """Toglie dalla cache dell'adapter (UNIT3D: _search_cache, comune agli
    adapter dello stesso tracker) la ricerca di questo contenuto."""
    cache = getattr(adapter, "_search_cache", None)
    if isinstance(cache, dict):
        cache.pop(tmdb_id, None)


def _prepare(session: Session, job: UploadJob, worker, ctx: dict, targets: list[UploadTarget]) -> None:
    """Una volta per job, se c'è almeno un upload: il torrent (hash dei
    piece) e gli screenshot. Senza, nessun upload può partire; i reseed sì."""
    if not any(t.action == "upload" and t.status == "approved" for t in targets):
        return
    overrides = ctx["overrides"]
    try:
        content = prepare_content(session, job, ctx)
        ctx["torrent"] = hash_pieces(session, job, content, ctx.get("planned"))
        # Per la barra degli step (ProgressStep): i passaggi conclusi restano segnati.
        upload_jobs.log_event(session, job, "torrent_created")
        session.commit()
        stored = json.loads(job.screenshot_urls_json or "[]") if ctx.get("retried") else []
        if stored:
            # Un nuovo tentativo: quelli già sull'image host valgono ancora,
            # niente di nuovo da caricare per un tracker che era giù.
            ctx["screenshots"] = stored
        else:
            ctx["screenshots"] = take_screenshots(session, job, worker, _screenshot_count(session, overrides))
            job.screenshot_urls_json = json.dumps(ctx["screenshots"])
        upload_jobs.log_event(session, job, "screenshots_done", count=len(ctx["screenshots"]),
                              **({"reused": True} if stored else {}))
        session.commit()
    except _Cancelled:
        raise
    except Exception as exc:
        # Un errore qualunque (un OSError creando gli hardlink, torf che non
        # legge il disco, un plugin dell'image host), non solo i nostri:
        # prima gli altri uscivano da qui e il job finiva senza dire perché.
        if not isinstance(exc, UploadJobError):
            logger.error("Upload %s: preparazione fallita", job.id, exc_info=exc)
        _fail_approved(session, job, targets, exc, actions=("upload",), default="upload_prepare_failed")


def _screenshot_count(session: Session, overrides: dict) -> int:
    count = overrides.get("screenshot_count")
    if count is None:
        return settings_registry.get_int(session, "upload_screenshot_count")
    try:
        return max(0, min(int(count), MAX_SCREENSHOTS))
    except (TypeError, ValueError):
        return settings_registry.get_int(session, "upload_screenshot_count")


def _fail_approved(session: Session, job: UploadJob, targets: list[UploadTarget], exc: Exception,
                   actions: tuple[str, ...], default: str) -> None:
    """I target ancora da fare (di quelle azioni) falliscono tutti con
    l'errore che li ferma, nel registro con i suoi parametri."""
    session.rollback()
    code, params = upload_jobs.error_of(exc)
    if not isinstance(exc, CodedError):
        code = default
    for target in targets:
        if target.action in actions and target.status == "approved":
            upload_jobs.set_target_status(target, upload_jobs.TargetStatus.FAILED)
            target.error_message = code
            target.finished_at = datetime.now(UTC)
            upload_jobs.log_event(session, job, code, level="error", target=target, **params)
    session.commit()


def _run_target(session: Session, job: UploadJob, target: UploadTarget, ctx: dict) -> None:
    _progress(session, job, f"tracker:{target.tracker.label}")
    try:
        if target.action == "upload":
            run_upload(session, job, target, ctx)
        else:
            run_reseed(session, job, target, ctx)
        upload_jobs.set_target_status(target, upload_jobs.TargetStatus.DONE)
    except Exception as exc:
        session.rollback()
        logger.warning("Upload %s: %s fallito su %s", job.id, target.action, target.tracker.label, exc_info=True)
        code, params = upload_jobs.error_of(exc)
        published = (ctx.get("published") or {}).get(target.id)
        if published is not None:
            # Il tracker l'ha ricevuto (anche se il DB non l'ha ancora
            # scritto): pubblicato, non in seed. Mai 'failed', che si potrebbe
            # riprovare con un secondo upload; il seed si riprova da solo.
            target.torrent_id_remote = published
            upload_jobs.set_target_status(target, upload_jobs.TargetStatus.DONE)
            target.error_message = "seed_failed"
            upload_jobs.log_event(session, job, "seed_failed", level="error", target=target, error=code)
        else:
            upload_jobs.set_target_status(target, upload_jobs.TargetStatus.FAILED)
            target.error_message = code
            upload_jobs.log_event(session, job, f"{target.action}_failed", level="error", target=target,
                                  error=code, **{k: v for k, v in params.items() if k != "error"})
    target.finished_at = datetime.now(UTC)
    session.commit()


def _housekeeping(session: Session, job: UploadJob, ctx: dict, overrides: dict, cancelled: bool = False) -> None:
    """Gli hardlink che non seedano niente e la cartella osservata. Mai un
    motivo per cambiare l'esito del job (audit 2026-10-18): un upload
    pubblicato e in seed finiva 'failed' se un file della cartella osservata
    non si poteva togliere. Annullato: solo gli hardlink (la cartella
    osservata resta com'è)."""
    steps = [("links", lambda: _cleanup_unused_links(session, job, ctx, overrides))]
    if not cancelled:
        steps.append(("watch", lambda: _clear_watch_source(session, job, overrides, ctx)))
    for what, step in steps:
        try:
            step()
        except Exception as exc:
            session.rollback()
            logger.warning("Upload %s: pulizia (%s) non riuscita", job.id, what, exc_info=True)
            with contextlib.suppress(Exception):
                upload_jobs.log_event(session, job, "upload_cleanup_failed", level="warning", step=what,
                                      error=upload_jobs.error_text(exc))
                session.commit()


def _context(session: Session, job: UploadJob, worker, overrides: dict) -> dict:
    ctx: dict = {"dir": _job_dir(worker, job), "overrides": overrides, "screenshots": []}
    root_cache: list[str] = []

    def lazy_seed_root() -> str:
        if not root_cache:
            root_cache.append(seed_root(job))
        return root_cache[0]

    ctx["seed_root"] = lazy_seed_root
    return ctx


def handle(session: Session, job: UploadJob, worker) -> None:
    if not upload_jobs.transition(session, job, "queued", "running", queue_position=None):
        return
    retried = upload_jobs.is_retry(job)
    upload_jobs.log_event(session, job, "execution_started")
    session.commit()
    targets = [t for t in job.targets if t.status == "approved"]
    if job.scheduled_at is not None or retried:
        _recheck_dupes(session, job, targets)
    overrides = json.loads(job.overrides_json or "{}")
    try:
        ctx = _context(session, job, worker, overrides)
        ctx["retried"] = retried
    except Exception as exc:  # la cartella del job non si crea: niente può partire
        logger.error("Upload %s: cartella del job non disponibile", job.id, exc_info=exc)
        _fail_approved(session, job, targets, exc, actions=("upload", "reseed"), default="upload_prepare_failed")
        ctx = {"overrides": overrides}
    else:
        try:
            _prepare(session, job, worker, ctx, targets)
            for target in targets:
                session.refresh(job)
                if job.status == "cancelled":
                    raise _Cancelled()
                if target.status == "approved":
                    _run_target(session, job, target, ctx)
        except _Cancelled:
            # Annullato a metà: gli hardlink creati e non usati si tolgono
            # come alla fine (audit 2026-10-18), prima restavano nella
            # cartella di seed senza che nessuno li seedasse.
            _housekeeping(session, job, ctx, overrides, cancelled=True)
            return
        _housekeeping(session, job, ctx, overrides)
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
