"""Secondo punto di approvazione del flusso di upload v2 (docs/SPEC.md §9):
per ogni tracker l'azione (upload, reseed, salta), il nome della release,
i flag e gli id di categoria/tipo/risoluzione del profilo.

L'approvazione è la conferma umana obbligatoria di §9: da qui il worker
porta il job fino in fondo senza chiedere altro (decisione dell'utente,
2026-09-29). Per questo si approvano tutti i tracker insieme, ognuno con
la sua decisione esplicita, mai uno per default.
"""

import json
import os

from sqlalchemy.orm import Session

from app import upload_jobs
from app.models import TrackerUploadProfile, UploadJob, UploadTarget
from app.upload_jobs import UploadJobError
from app.upload_naming import DETECTED_FIELDS, build_name, detect, name_values

FLAG_KEYS = ("anonymous", "personal_release", "internal", "stream")
# Override oltre ai valori rilevati: anno del nome, numero di screenshot,
# note in fondo alla descrizione, e non aggiungere il torrent al client.
EXTRA_OVERRIDES = {"year": int, "screenshot_count": int, "notes": str, "no_seed": bool}
MAX_SCREENSHOTS = 12


def _profile(session: Session, target: UploadTarget) -> TrackerUploadProfile | None:
    return session.get(TrackerUploadProfile, target.tracker_id)


def _maps(profile: TrackerUploadProfile | None) -> tuple[dict, dict, dict]:
    if profile is None:
        return {}, {}, {}
    return (
        json.loads(profile.category_id_map_json or "{}"),
        json.loads(profile.type_id_map_json or "{}"),
        json.loads(profile.resolution_id_map_json or "{}"),
    )


def detected_values(job: UploadJob) -> dict:
    """Dal nome scelto dall'analisi (torrent in hardlink, nome originale di
    Radarr/Sonarr, o il nome della sorgente: app/upload_analysis.py)."""
    source = (json.loads(job.analysis_json or "{}").get("name_source") or {}).get("name")
    return detect(source or os.path.basename(job.source_path.rstrip(os.sep)))


def clean_overrides(raw: dict | None) -> dict:
    cleaned: dict = {}
    for key, value in (raw or {}).items():
        if value is None or value == "":
            continue
        if key in DETECTED_FIELDS:
            cleaned[key] = str(value).strip()
        elif key in EXTRA_OVERRIDES:
            kind = EXTRA_OVERRIDES[key]
            try:
                cleaned[key] = kind(value) if kind is not bool else bool(value)
            except (TypeError, ValueError) as exc:
                raise UploadJobError("upload_invalid_override", field=key) from exc
        else:
            raise UploadJobError("upload_unknown_override", field=key)
    if "screenshot_count" in cleaned and not 0 <= cleaned["screenshot_count"] <= MAX_SCREENSHOTS:
        raise UploadJobError("upload_invalid_override", field="screenshot_count")
    return cleaned


def propose(session: Session, job: UploadJob) -> None:
    """Nome, id del profilo e flag proposti per ogni tracker, dai valori
    rilevati e dagli override. Rifatto a ogni cambio di override; non tocca
    mai quello che l'utente ha già approvato."""
    detected = detected_values(job)
    overrides = json.loads(job.overrides_json or "{}")
    seasons = json.loads(job.seasons_json or "[]")
    values = name_values(job, detected, overrides, seasons)
    analysis = json.loads(job.analysis_json or "{}")
    analysis["detected"] = detected
    job.analysis_json = json.dumps(analysis)
    for target in job.targets:
        profile = _profile(session, target)
        categories, types, resolutions = _maps(profile)
        target.proposed_name = build_name(profile.naming_convention if profile else None, values)
        target.category_id = categories.get(job.content_type or "movie")
        target.type_id = types.get(values.get("type") or "")
        target.resolution_id = resolutions.get(values.get("resolution") or "")
        if target.flags_json is None:
            target.flags_json = json.dumps({
                "anonymous": bool(profile and profile.default_anonymous),
                "personal_release": bool(profile and profile.default_personal_release),
                "internal": False,
                "stream": False,
            })
    session.commit()


def update_overrides(session: Session, job: UploadJob, overrides: dict | None) -> None:
    if job.status != "awaiting_decision":
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    job.overrides_json = json.dumps(clean_overrides(overrides))
    propose(session, job)


def _validate(target: UploadTarget, decision: dict) -> dict:
    action = decision.get("action")
    if action not in ("upload", "reseed", "skip"):
        raise UploadJobError("upload_invalid_action", tracker=target.tracker.label)
    out = {"action": action}
    if action == "upload":
        name = (decision.get("name") or "").strip()
        if not name:
            raise UploadJobError("upload_name_required", tracker=target.tracker.label)
        ids = {key: decision.get(key) for key in ("category_id", "type_id", "resolution_id")}
        if any(not isinstance(v, int) for v in ids.values()):
            raise UploadJobError("upload_ids_required", tracker=target.tracker.label)
        flags = decision.get("flags") or {}
        out.update(ids, name=name, flags={key: bool(flags.get(key)) for key in FLAG_KEYS})
    if action == "reseed":
        dupes = json.loads(target.dupes_json or "[]")
        torrent_id = decision.get("reseed_torrent_id") or target.reseed_torrent_id
        identical = {d["torrent_id_remote"] for d in dupes if d["verdict"] == "identical"}
        if torrent_id not in identical:
            raise UploadJobError("upload_reseed_needs_identical", tracker=target.tracker.label)
        out["reseed_torrent_id"] = torrent_id
    return out


def approve(session: Session, job: UploadJob, decisions: list[dict]) -> None:
    """Tutti i tracker insieme, ognuno con la sua decisione. Porta il job in
    coda ('queued'), o direttamente a 'done' se ogni tracker è saltato."""
    if job.status != "awaiting_decision":
        raise UploadJobError("upload_job_wrong_status", status=job.status)
    busy = [t for t in job.targets if t.status != "awaiting_decision"]
    if busy:
        raise UploadJobError("upload_target_busy", tracker=busy[0].tracker.label, status=busy[0].status)
    by_target = {d.get("target_id"): d for d in decisions}
    missing = [t for t in job.targets if t.id not in by_target]
    if missing:
        raise UploadJobError("upload_decision_missing", tracker=missing[0].tracker.label)
    validated = {t.id: _validate(t, by_target[t.id]) for t in job.targets}

    for target in job.targets:
        decision = validated[target.id]
        target.action = decision["action"]
        if decision["action"] == "upload":
            target.approved_name = decision["name"]
            target.flags_json = json.dumps(decision["flags"])
            target.category_id = decision["category_id"]
            target.type_id = decision["type_id"]
            target.resolution_id = decision["resolution_id"]
        if decision["action"] == "reseed":
            target.reseed_torrent_id = decision["reseed_torrent_id"]
        target.status = "skipped" if decision["action"] == "skip" else "approved"
        upload_jobs.log_event(
            session, job, "target_approved", target=target, action=decision["action"],
            name=decision.get("name"), torrent=decision.get("reseed_torrent_id"),
        )
    session.commit()

    if all(t.action == "skip" for t in job.targets):
        upload_jobs.transition(session, job, "awaiting_decision", "done")
        upload_jobs.log_event(session, job, "all_skipped")
    else:
        upload_jobs.transition(
            session, job, "awaiting_decision", "queued", queue_position=upload_jobs.next_queue_position(session)
        )
        upload_jobs.log_event(session, job, "job_queued", position=job.queue_position)
    session.commit()
