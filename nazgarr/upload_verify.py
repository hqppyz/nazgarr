"""Full hash check di un upload contro un torrent già presente su un
tracker (docs/SPEC.md §9 "Upload flow v2"): quando il dupe check trova una
release "identical", si legge ogni piece del .torrent del tracker contro i
file della sorgente. Se passa, per quel tracker conviene un reseed.

Stessa lettura di nazgarr/full_check.py (verify_all_pieces, verdict), con un
locator sulla sorgente dell'upload invece che sui file di un candidato del
reseeding. Sola lettura: nessun file e nessun client viene toccato.

Il risultato finisce nel risultato del dupe check (dupes_json[i].verification)
e, se passa, target.suggested_action diventa 'reseed' con quel torrent.
"""

import json
import logging
import os

from sqlalchemy.orm import Session

from nazgarr import adapter_factory, upload_jobs
from nazgarr.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.full_check import CheckResult, unreadable_pieces, verdict, verify_all_pieces
from nazgarr.models import UploadJob, UploadTarget
from nazgarr.torrent_file import TorrentFileEntry, TorrentInfo, compute_info_hash, parse_torrent_info

logger = logging.getLogger(__name__)


def build_locator(job: UploadJob, parsed: TorrentInfo):
    """Dove sta in locale ogni file del torrent del tracker: stesso percorso
    dentro la cartella sorgente, poi stesso nome e dimensione (il tracker
    può aver messo i file in una sottocartella diversa), infine la sola
    dimensione se un solo file locale ce l'ha (il tracker ha rinominato il
    file). Il full hash check dice poi se sono davvero gli stessi byte."""
    if not job.is_dir:
        return lambda entry: (job.source_path, "source")

    by_name: dict[tuple[str, int], str] = {}
    by_size: dict[int, list[str]] = {}
    for dirpath, _dirs, filenames in os.walk(job.source_path):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.isfile(path):
                size = os.path.getsize(path)
                by_name.setdefault((name.lower(), size), path)
                by_size.setdefault(size, []).append(path)

    def locate(entry: TorrentFileEntry) -> tuple[str | None, str | None]:
        # Il percorso viene dal .torrent del tracker: mai fuori dalla sorgente.
        try:
            direct = resolve_scoped(job.source_path, entry.path)
        except ScopeViolation:
            direct = None
        if direct and os.path.isfile(direct) and os.path.getsize(direct) == entry.length:
            return direct, "source"
        found = by_name.get((os.path.basename(entry.path).lower(), entry.length))
        if found is None and len(by_size.get(entry.length, [])) == 1:
            found = by_size[entry.length][0]
        return (found, "source") if found else (None, None)

    return locate


def run_check(job: UploadJob, torrent_bytes: bytes, on_progress=lambda _: None) -> dict:
    parsed = parse_torrent_info(torrent_bytes)
    files, bad = verify_all_pieces(parsed, build_locator(job, parsed), on_progress)
    bad_set = set(bad)
    unreadable = len(bad_set & unreadable_pieces(parsed, files))
    result = CheckResult(
        torrent_name=parsed.name, info_hash=compute_info_hash(torrent_bytes), expected_info_hash=None,
        piece_length=parsed.piece_length, pieces=len(parsed.pieces), ok=len(parsed.pieces) - len(bad_set),
        mismatched=len(bad_set) - unreadable, unreadable=unreadable, bad_pieces=bad[:20], files=files,
    )
    passed, reason = verdict(result)
    return {
        "status": "passed" if passed else "failed",
        "reason": reason,
        "pieces": result.pieces,
        "ok": result.ok,
        "mismatched": result.mismatched,
        "unreadable": result.unreadable,
        "info_hash": result.info_hash,
    }


def start(session: Session, job: UploadJob, target: UploadTarget, torrent_id_remote: str, worker) -> None:
    """Chiamato dall'API: segna il target e affida la lettura al worker."""
    if job.status != "awaiting_decision" or target.status != "awaiting_decision":
        raise upload_jobs.UploadJobError("upload_job_wrong_status", status=target.status)
    dupes = json.loads(target.dupes_json or "[]")
    if not any(d["torrent_id_remote"] == torrent_id_remote for d in dupes):
        raise upload_jobs.UploadJobError("upload_dupe_not_found", id=torrent_id_remote)
    target.status = "verifying"
    upload_jobs.log_event(session, job, "verify_started", target=target, torrent=torrent_id_remote)
    session.commit()
    worker.submit_verify(target.id, torrent_id_remote)


def execute(session: Session, target_id: int, torrent_id_remote: str) -> None:
    """Nel thread del worker: scarica il .torrent dal tracker e legge tutto."""
    target = session.get(UploadTarget, target_id)
    if target is None or target.status != "verifying":
        return
    job = target.job
    dupes = json.loads(target.dupes_json or "[]")
    dupe = next((d for d in dupes if d["torrent_id_remote"] == torrent_id_remote), None)
    try:
        if dupe is None or not dupe.get("download_link"):
            raise upload_jobs.UploadJobError("upload_dupe_no_download_link")
        adapter = adapter_factory.build_tracker_adapter(target.tracker)
        verification = run_check(job, adapter.download_torrent(dupe["download_link"]))
    except Exception as exc:
        logger.warning("Full hash check di %s su %s fallito", torrent_id_remote, target.tracker.label, exc_info=True)
        verification = {"status": "error", "reason": getattr(exc, "code", None) or str(exc)}

    session.refresh(target)
    dupes = json.loads(target.dupes_json or "[]")
    for d in dupes:
        if d["torrent_id_remote"] == torrent_id_remote:
            d["verification"] = verification
    target.dupes_json = json.dumps(dupes)
    if verification["status"] == "passed":
        target.suggested_action = "reseed"
        target.reseed_torrent_id = torrent_id_remote
    if target.status == "verifying":  # non annullato nel frattempo
        target.status = "awaiting_decision"
    level = "info" if verification["status"] == "passed" else "warning"
    upload_jobs.log_event(
        session, job, f"verify_{verification['status']}", level=level, target=target, torrent=torrent_id_remote,
        reason=verification.get("reason"), ok=verification.get("ok"), pieces=verification.get("pieces"),
    )
    session.commit()
